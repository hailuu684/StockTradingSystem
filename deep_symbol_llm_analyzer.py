#!/usr/bin/env python3
"""
Deep symbol LLM analyzer - structured BCTC edition.

Run this AFTER the heuristic/quant pipeline has produced top candidates.
This script does NOT OCR PDFs and does NOT download financial-statement PDFs.
It uses vnstock_data Fundamental structured tables through
scripts.get_fundamental_analysis_layer and caches the generated markdown by
quarter under --financial_cache_path.

Typical usage:

python deep_symbol_llm_analyzer.py \
  --symbols TCB,FPT,MBS \
  --heuristic_outputs ./outputs/trade_pipeline_integrate_llm \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --financial_cache_path ./data/financial_statements \
  --news_cache_path ./data/news_cache \
  --outputs ./outputs/deep_symbol_llm \
  --results ./results/deep_symbol_llm_report_{date}.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

JsonDict = Dict[str, Any]
ACTION_ORDER = ["BUY_CANDIDATE", "WATCHLIST", "HOLD_MONITOR", "REDUCE_OR_EXIT", "IGNORE"]
DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y%m%d",
)


# ---------------------------------------------------------------------------
# General utilities
# ---------------------------------------------------------------------------


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def today_stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def ensure_dir(path: Union[str, Path]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_text(path: Union[str, Path], default: str = "") -> str:
    p = Path(path)
    try:
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return default


def write_text(path: Union[str, Path], text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def write_json(path: Union[str, Path], data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_json(path: Union[str, Path], default: Optional[JsonDict] = None) -> JsonDict:
    p = Path(path)
    if not p.exists():
        return dict(default or {})
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_filename(value: Any, max_len: int = 160) -> str:
    # Avoid ambiguous pandas truth value when values originate from DataFrame rows.
    if isinstance(value, pd.Series):
        non_empty = [x for x in value.tolist() if str(x).strip().lower() not in {"", "nan", "none", "null", "nat", "<na>", "-"}]
        value = non_empty[0] if non_empty else ""
    elif isinstance(value, pd.DataFrame):
        flat = value.to_numpy().ravel().tolist() if not value.empty else []
        non_empty = [x for x in flat if str(x).strip().lower() not in {"", "nan", "none", "null", "nat", "<na>", "-"}]
        value = non_empty[0] if non_empty else ""
    value = "" if value is None else str(value).strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return (value or "file")[:max_len]


def clean_symbol(value: Any) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except Exception:
        pass
    return re.sub(r"[^A-Za-z0-9]", "", str(value).upper().strip())


def is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def truncate_text(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n...[TRUNCATED]...\n\n" + text[-half:]


def render_path_template(template: Union[str, Path], stamp: str) -> Path:
    text = str(template)
    today = datetime.now().strftime("%Y%m%d")
    rendered = (
        text.replace("{datetime}", stamp)
        .replace("{timestamp}", stamp)
        .replace("{stamp}", stamp)
        .replace("{date}", stamp)
        .replace("{today}", today)
    )
    return Path(rendered)


def parse_datetime_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(dtype="datetime64[ns]")
    src = series.astype("string")
    out = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    remaining = src.notna() & src.str.strip().ne("")
    for fmt in DATE_FORMATS:
        if not remaining.any():
            break
        parsed = pd.to_datetime(src[remaining], format=fmt, errors="coerce")
        ok = parsed.notna()
        if ok.any():
            out.loc[parsed.index[ok]] = parsed[ok]
            remaining.loc[parsed.index[ok]] = False
    if remaining.any():
        parsed = pd.to_datetime(src[remaining], errors="coerce", dayfirst=True)
        out.loc[parsed.index] = parsed
    return out


def first_existing_col(df: pd.DataFrame, candidates: Sequence[str], contains: bool = False) -> Optional[str]:
    if df is None or df.empty:
        return None
    cols = list(map(str, df.columns))
    lower_map = {c.lower(): c for c in cols}
    for cand in candidates:
        c = str(cand).lower()
        if c in lower_map:
            return lower_map[c]
    if contains:
        for col in cols:
            low = col.lower()
            if any(str(c).lower() in low for c in candidates):
                return col
    return None


def dataframe_to_markdown(df: pd.DataFrame, max_rows: int = 60, max_cols: int = 40) -> str:
    if df is None or df.empty:
        return "_Không có dữ liệu._"
    view = df.copy().head(max_rows)
    if len(view.columns) > max_cols:
        view = view.iloc[:, :max_cols].copy()
        view["..."] = "..."
    try:
        return view.to_markdown(index=False)
    except Exception:
        return view.to_string(index=False)


def mapping_to_markdown(mapping: Mapping[str, Any], max_items: int = 120) -> str:
    rows = []
    for i, (k, v) in enumerate(mapping.items()):
        if i >= max_items:
            break
        if isinstance(v, (dict, list)):
            value = json.dumps(v, ensure_ascii=False, default=str)[:1200]
        else:
            value = str(v)[:1200]
        rows.append({"field": k, "value": value})
    return dataframe_to_markdown(pd.DataFrame(rows), max_rows=max_items, max_cols=4)


def read_csv_safe(path: Union[str, Path]) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        try:
            return pd.read_csv(p, encoding="utf-8-sig")
        except Exception as exc:
            logging.warning("Could not read CSV %s: %s", p, exc)
            return pd.DataFrame()


# ---------------------------------------------------------------------------
# Symbols and heuristic context
# ---------------------------------------------------------------------------


def parse_symbols(symbols: Optional[str], symbols_file: Optional[Union[str, Path]]) -> List[str]:
    out: List[str] = []
    if symbols:
        for part in re.split(r"[,;\s]+", symbols):
            s = clean_symbol(part)
            if s:
                out.append(s)
    if symbols_file:
        p = Path(symbols_file)
        if p.exists():
            if p.suffix.lower() in {".csv", ".tsv"}:
                df = read_csv_safe(p)
                col = first_existing_col(df, ["symbol", "ticker", "code", "stock"], contains=True)
                if col:
                    out.extend(clean_symbol(x) for x in df[col].dropna().tolist())
                else:
                    # Fallback: first column.
                    if not df.empty:
                        out.extend(clean_symbol(x) for x in df.iloc[:, 0].dropna().tolist())
            else:
                text = p.read_text(encoding="utf-8")
                out.extend(clean_symbol(x) for x in re.split(r"[,;\s]+", text) if clean_symbol(x))
    # Preserve order, de-dupe.
    seen = set()
    result = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            result.append(s)
    if not result:
        raise ValueError("No symbols supplied. Use --symbols TCB,FPT or --symbols_file path.csv")
    return result


@dataclass
class HeuristicContext:
    symbol: str
    row: Dict[str, Any] = field(default_factory=dict)
    decision: Dict[str, Any] = field(default_factory=dict)
    research_markdown_path: Optional[str] = None
    research_markdown: str = ""
    files: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_prompt_markdown(self) -> str:
        lines = [f"# Heuristic / quant context - {self.symbol}", ""]
        if self.row:
            lines.extend(["## Ranked row", mapping_to_markdown(self.row), ""])
        else:
            lines.append("_Không tìm thấy row trong candidates_ranked_latest/watchlist_latest._\n")
        if self.decision:
            lines.extend(["## Previous heuristic/agent decision JSON", "```json", json.dumps(self.decision, ensure_ascii=False, indent=2, default=str), "```", ""])
        if self.research_markdown:
            lines.extend(["## Previous research markdown", truncate_text(self.research_markdown, 12000), ""])
        if self.errors:
            lines.extend(["## Heuristic context errors", *[f"- {e}" for e in self.errors]])
        return "\n".join(lines).strip() + "\n"


class HeuristicOutputLoader:
    def __init__(self, root: Union[str, Path]):
        self.root = Path(root)

    def load(self, symbol: str) -> HeuristicContext:
        symbol = clean_symbol(symbol)
        ctx = HeuristicContext(symbol=symbol)
        if not self.root.exists():
            ctx.errors.append(f"heuristic_outputs folder not found: {self.root}")
            return ctx
        # Candidate/watchlist CSV.
        for name in ["candidates_ranked_latest.csv", "watchlist_latest.csv"]:
            path = self.root / name
            df = read_csv_safe(path)
            if df.empty:
                continue
            sym_col = first_existing_col(df, ["symbol", "ticker", "code"], contains=True)
            if not sym_col:
                continue
            work = df.copy()
            work["__symbol__"] = work[sym_col].map(clean_symbol)
            rows = work[work["__symbol__"] == symbol]
            if not rows.empty:
                ctx.row = rows.iloc[0].drop(labels=["__symbol__"], errors="ignore").to_dict()
                ctx.files[name] = str(path)
                break
        # Previous decision JSON.
        dec_dir = self.root / "decisions"
        if dec_dir.exists():
            candidates = sorted(dec_dir.glob(f"{symbol}*_decision_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                candidates = sorted(dec_dir.glob(f"*{symbol}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                try:
                    ctx.decision = load_json(candidates[0])
                    ctx.files["decision_json"] = str(candidates[0])
                except Exception as exc:
                    ctx.errors.append(f"Could not read decision JSON: {exc}")
        # Previous research markdown.
        md_dir = self.root / "markdown"
        if md_dir.exists():
            candidates = sorted(md_dir.glob(f"{symbol}*_research_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                candidates = sorted(md_dir.glob(f"*{symbol}*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
            if candidates:
                ctx.research_markdown_path = str(candidates[0])
                ctx.research_markdown = read_text(candidates[0])
                ctx.files["research_markdown"] = str(candidates[0])
        return ctx


# ---------------------------------------------------------------------------
# Fundamental markdown cache manager. No PDF download.
# ---------------------------------------------------------------------------


@dataclass
class FinancialContext:
    symbol: str
    company_name: str
    period_label: str
    quarter: Optional[int]
    year: Optional[int]
    markdown_path: str
    audit_json_path: Optional[str]
    markdown: str
    used_cache: bool
    source_url: Optional[str] = None
    quarter_dir: Optional[str] = None
    errors: List[str] = field(default_factory=list)


class FinancialCacheManager:
    """Caches structured BCTC markdown by quarter. Never downloads PDFs."""

    def __init__(self, cache_root: Union[str, Path], *, filing_doc_type: str = "financial_report"):
        self.cache_root = ensure_dir(cache_root)
        self.filing_doc_type = filing_doc_type
        self.index_path = self.cache_root / "financial_report_index.json"

    def prepare(self, symbol: str, *, force_refresh: bool = False, skip_filing_check: bool = False) -> FinancialContext:
        # Backward-compatible alias for earlier deep analyzers/log traces.
        return self.get(symbol, force_refresh=force_refresh, skip_filing_check=skip_filing_check)

    def get(self, symbol: str, *, force_refresh: bool = False, skip_filing_check: bool = False) -> FinancialContext:
        symbol = clean_symbol(symbol)
        local = self._find_latest_local(symbol)
        latest_q: Optional[int] = None
        latest_y: Optional[int] = None
        filing_errors: List[str] = []
        filing_row: Dict[str, Any] = {}

        if not skip_filing_check:
            latest_y, latest_q, filing_row, filing_errors = self._latest_period_from_filing(symbol)

        # If filing works and local latest-period markdown exists, load it and avoid full BCTC calls.
        if latest_y and latest_q and not force_refresh:
            exact = self._find_local_for_period(symbol, latest_y, latest_q)
            if exact:
                return self._context_from_local(symbol, exact, used_cache=True, extra_errors=filing_errors, filing_row=filing_row)

        # If filing failed or user skips filing check, use local cache when available.
        if local and not force_refresh and (skip_filing_check or not latest_y or not latest_q):
            return self._context_from_local(symbol, local, used_cache=True, extra_errors=filing_errors, filing_row=filing_row)

        # Generate from structured Fundamental API tables only.
        try:
            from scripts.get_fundamental_analysis_layer import get_fundamental_analysis_layer  # type: ignore
        except Exception:
            # Running this file from outside package root.
            from get_fundamental_analysis_layer import get_fundamental_analysis_layer  # type: ignore

        result = get_fundamental_analysis_layer(
            symbol=symbol,
            output_root=self.cache_root,
            filing_doc_type=self.filing_doc_type,
            force_refresh=force_refresh,
        )
        md_path = Path(str(result.get("markdown_path") or ""))
        if not md_path.exists():
            raise RuntimeError(f"Fundamental analysis did not create markdown_path for {symbol}: {result}")
        self._update_index(symbol, result)
        return FinancialContext(
            symbol=symbol,
            company_name=str(result.get("company_name") or symbol),
            period_label=str(result.get("period_label") or "unknown"),
            quarter=result.get("quarter"),
            year=result.get("year"),
            markdown_path=str(md_path),
            audit_json_path=str(result.get("audit_json_path") or ""),
            markdown=read_text(md_path),
            used_cache=bool(result.get("used_cache", False)),
            source_url=result.get("source_url"),
            quarter_dir=str(result.get("quarter_dir") or md_path.parent),
            errors=list(result.get("errors") or []) + filing_errors,
        )

    def _find_latest_local(self, symbol: str) -> Optional[Path]:
        files = []
        for path in self.cache_root.glob(f"quarter_*/*{symbol}*_structured_financial_report.md"):
            if clean_symbol(path.name.split("_")[0]) == symbol:
                files.append(path)
        if not files:
            # Accept compact naming from older generated files.
            files = list(self.cache_root.glob(f"quarter_*/*{symbol}*.md"))
        if not files:
            return None
        return sorted(files, key=lambda p: (self._period_from_path(p), p.stat().st_mtime), reverse=True)[0]

    def _find_local_for_period(self, symbol: str, year: int, quarter: int) -> Optional[Path]:
        qdir = self.cache_root / f"quarter_{quarter}"
        patterns = [
            f"{symbol}_*_{year}_Q{quarter}_structured_financial_report.md",
            f"{symbol}_*_{year}_Q{quarter}.md",
            f"*{symbol}*{year}*Q{quarter}*.md",
        ]
        files: List[Path] = []
        for pat in patterns:
            files.extend(qdir.glob(pat))
        files = [p for p in files if "structured_financial_report" in p.name or re.search(rf"{year}.*Q{quarter}|Q{quarter}.*{year}", p.name, re.I)]
        if not files:
            return None
        return sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)[0]

    @staticmethod
    def _period_from_path(path: Path) -> Tuple[int, int]:
        text = path.name
        m = re.search(r"(20\d{2})[_-]?Q([1-4])", text, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r"Q([1-4])[_-]?(20\d{2})", text, re.I)
        if m:
            return int(m.group(2)), int(m.group(1))
        qmatch = re.search(r"quarter_([1-4])", str(path.parent), re.I)
        q = int(qmatch.group(1)) if qmatch else 0
        return 0, q

    def _context_from_local(
        self,
        symbol: str,
        md_path: Path,
        *,
        used_cache: bool,
        extra_errors: Optional[List[str]] = None,
        filing_row: Optional[Mapping[str, Any]] = None,
    ) -> FinancialContext:
        audit_path = md_path.with_name(md_path.name.replace("_structured_financial_report.md", "_structured_financial_audit.json"))
        audit = load_json(audit_path, default={}) if audit_path.exists() else {}
        year, q = self._period_from_path(md_path)
        period_label = str(audit.get("period_label") or (f"{year}-Q{q}" if year and q else "unknown"))
        company = str(audit.get("company_name") or self._company_from_filename(md_path.name, symbol))
        return FinancialContext(
            symbol=symbol,
            company_name=company,
            period_label=period_label,
            quarter=int(audit.get("quarter") or q or 0) or None,
            year=int(audit.get("year") or year or 0) or None,
            markdown_path=str(md_path),
            audit_json_path=str(audit_path) if audit_path.exists() else None,
            markdown=read_text(md_path),
            used_cache=used_cache,
            source_url=str(audit.get("source_url") or (filing_row or {}).get("doc_url") or "") or None,
            quarter_dir=str(md_path.parent),
            errors=list(audit.get("errors") or []) + list(extra_errors or []),
        )

    @staticmethod
    def _company_from_filename(name: str, symbol: str) -> str:
        stem = Path(name).stem
        stem = re.sub(r"_structured_financial_report$", "", stem)
        stem = re.sub(rf"^{re.escape(symbol)}_", "", stem, flags=re.I)
        stem = re.sub(r"_20\d{2}_Q[1-4].*$", "", stem, flags=re.I)
        return stem.replace("_", " ").strip() or symbol

    def _latest_period_from_filing(self, symbol: str) -> Tuple[Optional[int], Optional[int], Dict[str, Any], List[str]]:
        errors: List[str] = []
        try:
            from vnstock_data import Fundamental  # type: ignore
            eq = Fundamental().equity(symbol)
            try:
                filing = eq.filing(doc_type=self.filing_doc_type)
            except TypeError:
                filing = eq.filing()
            except Exception:
                filing = eq.filing()
            df = pd.DataFrame(filing)
            if df.empty:
                return None, None, {}, ["filing() returned empty; using local cache or full structured refresh fallback."]
            row, q, y = self._select_latest_filing_row(df)
            return y, q, row, errors
        except Exception as exc:
            errors.append(f"filing period check failed: {type(exc).__name__}: {exc}")
            return None, None, {}, errors

    @staticmethod
    def _select_latest_filing_row(df: pd.DataFrame) -> Tuple[Dict[str, Any], Optional[int], Optional[int]]:
        work = df.copy()
        text_cols = [c for c in work.columns if any(k in str(c).lower() for k in ["title", "name", "period", "type", "doc"])]
        if not text_cols:
            text_cols = list(work.columns)
        text = work[text_cols].astype(str).agg(" ".join, axis=1)
        q = text.str.extract(r"(?:qu[yý]\s*|q)([1-4])", flags=re.I, expand=False)
        y = text.str.extract(r"(20\d{2})", expand=False)
        work["__q__"] = pd.to_numeric(q, errors="coerce")
        work["__y__"] = pd.to_numeric(y, errors="coerce")
        # Prefer quarterly financial reports and rows with doc_url.
        is_fin = text.str.contains(r"bctc|báo cáo tài chính|bao cao tai chinh|financial", case=False, regex=True, na=False)
        work["__score__"] = 0
        work.loc[is_fin, "__score__"] += 10
        if "doc_url" in work.columns:
            work.loc[work["doc_url"].astype(str).str.startswith("http", na=False), "__score__"] += 1
        valid = work[work["__q__"].notna() & work["__y__"].notna()].copy()
        if valid.empty:
            return work.iloc[0].drop(labels=["__q__", "__y__", "__score__"], errors="ignore").to_dict(), None, None
        valid = valid.sort_values(["__y__", "__q__", "__score__"], ascending=[False, False, False])
        row = valid.iloc[0]
        clean = row.drop(labels=["__q__", "__y__", "__score__"], errors="ignore").to_dict()
        return clean, int(row["__q__"]), int(row["__y__"])

    def _update_index(self, symbol: str, result: Mapping[str, Any]) -> None:
        idx = load_json(self.index_path, default={})
        idx.setdefault(symbol, [])
        entry = {
            "updated_at": datetime.now().isoformat(),
            "symbol": symbol,
            "period_label": result.get("period_label"),
            "quarter": result.get("quarter"),
            "year": result.get("year"),
            "markdown_path": result.get("markdown_path"),
            "audit_json_path": result.get("audit_json_path"),
            "source_url": result.get("source_url"),
        }
        # Upsert by period_label.
        rows = [r for r in idx.get(symbol, []) if r.get("period_label") != entry.get("period_label")]
        rows.append(entry)
        idx[symbol] = sorted(rows, key=lambda r: str(r.get("period_label") or ""))
        write_json(self.index_path, idx)


# ---------------------------------------------------------------------------
# News cache manager
# ---------------------------------------------------------------------------


@dataclass
class NewsContext:
    symbol: str
    data_path: Optional[str]
    markdown: str
    rows: int
    used_cache: bool
    errors: List[str] = field(default_factory=list)


class NewsCacheManager:
    def __init__(self, cache_root: Union[str, Path], *, ttl_days: int = 10, news_config: Optional[Union[str, Path]] = None, enabled: bool = True):
        self.cache_root = ensure_dir(cache_root)
        self.raw_dir = ensure_dir(self.cache_root / "raw")
        self.symbol_dir = ensure_dir(self.cache_root / "symbols")
        self.ttl_days = ttl_days
        self.news_config = Path(news_config) if news_config else self._default_news_config()
        self.enabled = enabled

    @staticmethod
    def _default_news_config() -> Path:
        root = Path.cwd()
        preferred = root / "configs" / "news_deep_symbol.json"
        if preferred.exists():
            return preferred
        return root / "configs" / "news.json"

    def purge_old(self) -> None:
        cutoff = datetime.now() - timedelta(days=self.ttl_days)
        for path in list(self.raw_dir.glob("*.csv")) + list(self.symbol_dir.glob("*.csv")):
            try:
                if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                    path.unlink(missing_ok=True)
            except Exception:
                pass

    def get_for_symbol(self, symbol: str, aliases: Sequence[str], *, force_refresh: bool = False) -> NewsContext:
        symbol = clean_symbol(symbol)
        if not self.enabled:
            return NewsContext(symbol=symbol, data_path=None, markdown="_News disabled by --no_news._", rows=0, used_cache=False)
        self.purge_old()
        sym_cache = self._fresh_symbol_cache(symbol)
        if sym_cache and not force_refresh:
            df = read_csv_safe(sym_cache)
            return NewsContext(symbol=symbol, data_path=str(sym_cache), markdown=self._df_to_markdown(symbol, df), rows=len(df), used_cache=True)
        df_all, errors, raw_used_cache = self._load_or_fetch_raw(force_refresh=force_refresh)
        related = self._filter_for_symbol(df_all, symbol, aliases)
        out = self.symbol_dir / f"{symbol}_news_{today_stamp()}.csv"
        if not related.empty:
            related.to_csv(out, index=False)
        else:
            pd.DataFrame(columns=["source", "publish_time", "title", "url", "short_description", "content"]).to_csv(out, index=False)
        return NewsContext(symbol=symbol, data_path=str(out), markdown=self._df_to_markdown(symbol, related), rows=len(related), used_cache=raw_used_cache, errors=errors)

    def _fresh_symbol_cache(self, symbol: str) -> Optional[Path]:
        files = sorted(self.symbol_dir.glob(f"{symbol}_news_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        cutoff = datetime.now() - timedelta(days=self.ttl_days)
        for p in files:
            try:
                if datetime.fromtimestamp(p.stat().st_mtime) >= cutoff:
                    return p
            except Exception:
                continue
        return None

    def _fresh_raw_cache(self) -> Optional[Path]:
        files = sorted(self.raw_dir.glob("raw_news_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        cutoff = datetime.now() - timedelta(days=self.ttl_days)
        for p in files:
            try:
                if datetime.fromtimestamp(p.stat().st_mtime) >= cutoff:
                    return p
            except Exception:
                continue
        return None

    def _load_or_fetch_raw(self, *, force_refresh: bool = False) -> Tuple[pd.DataFrame, List[str], bool]:
        if not force_refresh:
            raw = self._fresh_raw_cache()
            if raw:
                return read_csv_safe(raw), [], True
        errors: List[str] = []
        try:
            from scripts.get_news_layer import get_news_layer  # type: ignore
        except Exception as exc:
            return pd.DataFrame(), [f"Could not import scripts.get_news_layer: {exc}"], False
        try:
            result = get_news_layer(str(self.news_config))
            df = pd.DataFrame(result.get("data", pd.DataFrame()))
            errors.extend([str(x) for x in result.get("errors", [])])
        except Exception as exc:
            return pd.DataFrame(), [f"get_news_layer failed: {type(exc).__name__}: {exc}"], False
        if not df.empty:
            path = self.raw_dir / f"raw_news_{today_stamp()}_{now_stamp()}.csv"
            df.to_csv(path, index=False)
        return df, errors, False

    @staticmethod
    def _filter_for_symbol(df: pd.DataFrame, symbol: str, aliases: Sequence[str]) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        text_cols = [c for c in ["title", "short_description", "content", "summary", "tags", "category"] if c in df.columns]
        if not text_cols:
            return pd.DataFrame()
        text = df[text_cols].fillna("").astype(str).agg(" ".join, axis=1)
        patterns = [re.escape(symbol)]
        for alias in aliases:
            alias = str(alias or "").strip()
            if len(alias) >= 3:
                patterns.append(re.escape(alias))
        pattern = r"\b(?:" + "|".join(sorted(set(patterns), key=len, reverse=True)) + r")\b"
        mask = text.str.contains(pattern, case=False, regex=True, na=False)
        out = df[mask].copy()
        if "publish_time" in out.columns:
            out["__dt__"] = parse_datetime_series(out["publish_time"])
            out = out.sort_values("__dt__", ascending=False).drop(columns=["__dt__"])
        return out.head(80)

    @staticmethod
    def _df_to_markdown(symbol: str, df: pd.DataFrame) -> str:
        if df is None or df.empty:
            return f"# News context - {symbol}\n\n_Không tìm thấy tin liên quan trong cache/crawl hiện tại._\n"
        keep = [c for c in ["source", "publish_time", "title", "short_description", "url", "category", "tags"] if c in df.columns]
        md = dataframe_to_markdown(df[keep].head(30), max_rows=30, max_cols=10) if keep else dataframe_to_markdown(df.head(30))
        return f"# News context - {symbol}\n\nSố bài liên quan: {len(df)}\n\n{md}\n"


# ---------------------------------------------------------------------------
# Prompt and LLM
# ---------------------------------------------------------------------------


DEFAULT_PROMPT_TEMPLATE = """# ROLE
Bạn là một Trưởng bộ phận phân tích cổ phiếu tổ chức kiêm quant trader. Bạn đánh giá cổ phiếu Việt Nam dựa trên dữ liệu định lượng đã được pipeline tính sẵn, BCTC cấu trúc từ vnstock Fundamental Layer, tin tức, insights tự feed của user và trading playbook/RAG nếu có.

# HARD RULES
1. Không được bịa số liệu. Nếu dữ liệu thiếu, ghi rõ trong `data_gaps`.
2. Không dùng OCR/PDF raw. BCTC đầu vào đã được chuẩn hóa từ `Fundamental().equity(symbol)`.
3. Phân biệt rõ tín hiệu kỹ thuật, chất lượng BCTC, catalyst tin tức, và rủi ro.
4. Nếu BCTC có red flag trọng yếu hoặc tin tức rủi ro nghiêm trọng, không được trả BUY_CANDIDATE dù technical tốt.
5. Nếu chưa có điểm mua rõ, dùng WATCHLIST hoặc HOLD_MONITOR, không ép mua.
6. Output phải là JSON hợp lệ, không markdown, không bình luận ngoài JSON.

# OUTPUT JSON SCHEMA
{
  "symbol": "${symbol}",
  "company_name": "${company_name}",
  "final_action": "BUY_CANDIDATE | WATCHLIST | HOLD_MONITOR | REDUCE_OR_EXIT | IGNORE",
  "confidence": 0.0,
  "investment_horizon": "3M | 1Y | BOTH",
  "thesis_summary": "Vietnamese short thesis",
  "key_drivers": [],
  "financial_statement_readthrough": {
    "period": "${period_label}",
    "positive_points": [],
    "negative_points": [],
    "red_flags": [],
    "quality_of_earnings": "",
    "balance_sheet_risk": "",
    "cash_flow_quality": ""
  },
  "technical_readthrough": {
    "setup": "breakout | pullback | accumulation | downtrend | unclear",
    "trend_state": "",
    "flow_confirmation": "",
    "invalidations": []
  },
  "news_readthrough": {
    "material_news": [],
    "risk_news": [],
    "catalyst_news": []
  },
  "insights_readthrough": {
    "important_points": [],
    "uncertainties": []
  },
  "buy_plan": {
    "strategy": "breakout | pullback | staged_accumulation | wait | reduce | exit",
    "entry_zone_low": null,
    "entry_zone_high": null,
    "stop_loss": null,
    "target_3m": null,
    "target_1y": null,
    "suggested_quantity": 0,
    "suggested_position_value": 0.0,
    "risk_notes": ""
  },
  "sell_or_reduce_rules": [],
  "what_to_monitor_next_10_days": [],
  "data_gaps": []
}

# SYMBOL
${symbol}

# COMPANY NAME
${company_name}

# HEURISTIC / QUANT CONTEXT FROM PREVIOUS PIPELINE
${heuristic_context}

# STRUCTURED FINANCIAL STATEMENT MARKDOWN
${financial_markdown}

# OPTIONAL USER-FED INSIGHTS
${user_insights}

# OPTIONAL NEWS CONTEXT
${news_markdown}

# OPTIONAL RAG / PLAYBOOK CONTEXT
${rag_context}

# TASK
Hãy đưa ra quyết định cuối cùng cho mã ${symbol}: mã này có đáng mua/theo dõi/giảm tỷ trọng trong horizon 3 tháng hoặc 1 năm không? Nếu đáng mua, nêu vùng mua, stop-loss, target, khối lượng đề xuất và chiến lược giải ngân. Nếu chưa đáng mua, nêu điều kiện cần theo dõi để chuyển trạng thái.
"""


class PromptBuilder:
    def __init__(self, template_path: Optional[Union[str, Path]], *, max_heuristic_chars: int = 14000, max_financial_chars: int = 32000, max_news_chars: int = 12000, max_extra_chars: int = 12000):
        self.template_path = Path(template_path) if template_path else None
        self.max_heuristic_chars = max_heuristic_chars
        self.max_financial_chars = max_financial_chars
        self.max_news_chars = max_news_chars
        self.max_extra_chars = max_extra_chars

    def build(
        self,
        *,
        symbol: str,
        company_name: str,
        period_label: str,
        heuristic_md: str,
        financial_md: str,
        news_md: str,
        user_insights: str,
        rag_context: str,
    ) -> str:
        template = read_text(self.template_path, default="") if self.template_path else ""
        if not template:
            template = DEFAULT_PROMPT_TEMPLATE
        values = {
            "symbol": symbol,
            "company_name": company_name,
            "period_label": period_label,
            "heuristic_context": truncate_text(heuristic_md, self.max_heuristic_chars),
            "financial_markdown": truncate_text(financial_md, self.max_financial_chars),
            "news_markdown": truncate_text(news_md, self.max_news_chars),
            "user_insights": truncate_text(user_insights or "_Không có user insights._", self.max_extra_chars),
            "rag_context": truncate_text(rag_context or "_Không có RAG/playbook context._", self.max_extra_chars),
        }
        out = template
        for k, v in values.items():
            out = out.replace("${" + k + "}", str(v))
        return out


class DeepLLMAnalyzer:
    def __init__(self, config: Mapping[str, Any], *, dry_run: bool = False):
        self.config = dict(config or {})
        self.dry_run = dry_run

    def analyze(self, prompt: str, *, symbol: str, fallback: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if self.dry_run:
            decision = dict(fallback)
            decision["llm_status"] = "dry_run"
            return decision, {"status": "dry_run"}
        try:
            from scripts.get_llm_layer import ask_llm  # type: ignore
        except Exception as exc:
            decision = dict(fallback)
            decision["llm_status"] = "import_failed"
            decision["llm_error"] = str(exc)
            return decision, {"status": "import_failed", "error": str(exc)}
        try:
            raw = ask_llm(
                prompt,
                self.config,
                output_format="json",
                return_json=True,
                raise_on_error=True,
            )
            decision = normalize_deep_decision(raw, fallback=fallback, symbol=symbol)
            decision["llm_status"] = "success"
            return decision, {"status": "success"}
        except Exception as exc:
            decision = dict(fallback)
            decision["llm_status"] = "failed"
            decision["llm_error"] = f"{type(exc).__name__}: {exc}"
            return decision, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "")
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "")
        return int(float(value))
    except Exception:
        return default


def _to_list(value: Any, max_len: int = 8) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()][:max_len]
    if isinstance(value, (tuple, set)):
        return [str(x) for x in value if str(x).strip()][:max_len]
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[;\n]+", value) if x.strip()][:max_len]
    return [str(value)][:max_len]


def normalize_action(action: Any) -> str:
    text = str(action or "").strip().upper()
    aliases = {
        "BUY": "BUY_CANDIDATE", "MUA": "BUY_CANDIDATE", "MUA_MOI": "BUY_CANDIDATE",
        "WATCH": "WATCHLIST", "THEO_DOI": "WATCHLIST", "THEO DÕI": "WATCHLIST",
        "HOLD": "HOLD_MONITOR", "NAM_GIU": "HOLD_MONITOR", "NẮM GIỮ": "HOLD_MONITOR",
        "SELL": "REDUCE_OR_EXIT", "REDUCE": "REDUCE_OR_EXIT", "BÁN": "REDUCE_OR_EXIT", "GIẢM": "REDUCE_OR_EXIT",
        "SKIP": "IGNORE", "IGNORE": "IGNORE", "BỎ QUA": "IGNORE",
    }
    text = aliases.get(text, text)
    if text not in ACTION_ORDER:
        return "IGNORE"
    return text


def normalize_deep_decision(raw: Mapping[str, Any], *, fallback: Mapping[str, Any], symbol: str) -> Dict[str, Any]:
    raw = dict(raw or {})
    out = dict(fallback or {})
    # Accept either final_action or action.
    out["symbol"] = clean_symbol(raw.get("symbol") or out.get("symbol") or symbol)
    out["company_name"] = str(raw.get("company_name") or out.get("company_name") or out["symbol"])
    out["final_action"] = normalize_action(raw.get("final_action") or raw.get("action") or out.get("final_action"))
    out["action"] = out["final_action"]
    conf = _to_float(raw.get("confidence"), _to_float(out.get("confidence"), 0.5))
    out["confidence"] = max(0.0, min(1.0, conf if conf is not None else 0.5))
    out["investment_horizon"] = str(raw.get("investment_horizon") or raw.get("horizon") or out.get("investment_horizon") or "3M")
    out["thesis_summary"] = str(raw.get("thesis_summary") or raw.get("reason") or out.get("thesis_summary") or "")
    out["key_drivers"] = _to_list(raw.get("key_drivers") or out.get("key_drivers"), max_len=8)
    fs = raw.get("financial_statement_readthrough") if isinstance(raw.get("financial_statement_readthrough"), Mapping) else {}
    out["financial_statement_readthrough"] = {
        "period": str(fs.get("period") or out.get("period_label") or "unknown"),
        "positive_points": _to_list(fs.get("positive_points"), max_len=8),
        "negative_points": _to_list(fs.get("negative_points"), max_len=8),
        "red_flags": _to_list(fs.get("red_flags"), max_len=8),
        "quality_of_earnings": str(fs.get("quality_of_earnings") or ""),
        "balance_sheet_risk": str(fs.get("balance_sheet_risk") or ""),
        "cash_flow_quality": str(fs.get("cash_flow_quality") or ""),
    }
    tech = raw.get("technical_readthrough") if isinstance(raw.get("technical_readthrough"), Mapping) else {}
    out["technical_readthrough"] = {
        "setup": str(tech.get("setup") or "unclear"),
        "trend_state": str(tech.get("trend_state") or ""),
        "flow_confirmation": str(tech.get("flow_confirmation") or ""),
        "invalidations": _to_list(tech.get("invalidations"), max_len=6),
    }
    news = raw.get("news_readthrough") if isinstance(raw.get("news_readthrough"), Mapping) else {}
    out["news_readthrough"] = {
        "material_news": _to_list(news.get("material_news"), max_len=8),
        "risk_news": _to_list(news.get("risk_news"), max_len=8),
        "catalyst_news": _to_list(news.get("catalyst_news"), max_len=8),
    }
    ins = raw.get("insights_readthrough") if isinstance(raw.get("insights_readthrough"), Mapping) else {}
    out["insights_readthrough"] = {
        "important_points": _to_list(ins.get("important_points"), max_len=8),
        "uncertainties": _to_list(ins.get("uncertainties"), max_len=8),
    }
    bp = raw.get("buy_plan") if isinstance(raw.get("buy_plan"), Mapping) else {}
    out["buy_plan"] = {
        "strategy": str(bp.get("strategy") or out.get("buy_strategy") or "wait"),
        "entry_zone_low": _to_float(bp.get("entry_zone_low"), _to_float(out.get("entry_price_low"))),
        "entry_zone_high": _to_float(bp.get("entry_zone_high"), _to_float(out.get("entry_price_high"))),
        "stop_loss": _to_float(bp.get("stop_loss"), _to_float(out.get("stop_loss"))),
        "target_3m": _to_float(bp.get("target_3m"), _to_float(out.get("base_target"))),
        "target_1y": _to_float(bp.get("target_1y"), _to_float(out.get("bull_target"))),
        "suggested_quantity": _to_int(bp.get("suggested_quantity"), _to_int(out.get("suggested_quantity"), 0)),
        "suggested_position_value": _to_float(bp.get("suggested_position_value"), _to_float(out.get("suggested_position_value"), 0.0)) or 0.0,
        "risk_notes": str(bp.get("risk_notes") or ""),
    }
    out["sell_or_reduce_rules"] = _to_list(raw.get("sell_or_reduce_rules") or out.get("sell_or_reduce_rules"), max_len=8)
    out["what_to_monitor_next_10_days"] = _to_list(raw.get("what_to_monitor_next_10_days") or raw.get("monitoring_triggers"), max_len=8)
    out["data_gaps"] = _to_list(raw.get("data_gaps"), max_len=10)
    return out


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


@dataclass
class SymbolResult:
    symbol: str
    company_name: str
    action: str
    confidence: float
    llm_status: str
    heuristic_path: Optional[str]
    financial_markdown_path: str
    news_path: Optional[str]
    prompt_path: str
    json_path: str
    markdown_path: str
    errors: List[str] = field(default_factory=list)


class DeepSymbolPipeline:
    def __init__(
        self,
        *,
        symbols: Sequence[str],
        heuristic_outputs: Union[str, Path],
        config_path: Optional[Union[str, Path]],
        financial_cache_path: Union[str, Path],
        news_cache_path: Union[str, Path],
        outputs: Union[str, Path],
        results_path: Union[str, Path],
        news_config: Optional[Union[str, Path]] = None,
        prompt_template: Optional[Union[str, Path]] = None,
        insights_path: Optional[str] = None,
        rag_context_path: Optional[Union[str, Path]] = None,
        no_news: bool = False,
        force_refresh_news: bool = False,
        force_refresh_financial: bool = False,
        skip_filing_check: bool = False,
        news_ttl_days: int = 10,
        dry_run: bool = False,
        llm_delay_sec: float = 8.0,
        filing_doc_type: str = "financial_report",
    ):
        self.symbols = [clean_symbol(s) for s in symbols if clean_symbol(s)]
        self.heuristic_loader = HeuristicOutputLoader(heuristic_outputs)
        self.config = load_json(config_path, default={}) if config_path else {}
        self.financial_manager = FinancialCacheManager(financial_cache_path, filing_doc_type=filing_doc_type)
        self.news_manager = NewsCacheManager(news_cache_path, ttl_days=news_ttl_days, news_config=news_config, enabled=not no_news)
        self.outputs = ensure_dir(outputs)
        self.results_path = Path(results_path)
        self.prompt_builder = PromptBuilder(prompt_template or self._default_prompt_template())
        self.insights_path = insights_path
        self.rag_context_path = Path(rag_context_path) if rag_context_path else self._default_rag_context_path()
        self.force_refresh_news = force_refresh_news
        self.force_refresh_financial = force_refresh_financial
        self.skip_filing_check = skip_filing_check
        self.dry_run = dry_run
        self.llm = DeepLLMAnalyzer(self.config, dry_run=dry_run)
        self.llm_delay_sec = llm_delay_sec
        self.stamp = now_stamp()
        ensure_dir(self.outputs / "prompts")
        ensure_dir(self.outputs / "json")
        ensure_dir(self.outputs / "markdown")
        ensure_dir(self.outputs / "raw")

    @staticmethod
    def _default_prompt_template() -> Optional[Path]:
        p = Path.cwd() / "configs" / "deep_symbol_trade_prompt_template.md"
        return p if p.exists() else None

    @staticmethod
    def _default_rag_context_path() -> Optional[Path]:
        p = Path.cwd() / "configs" / "rag_context.md"
        return p if p.exists() else None

    def run(self) -> List[SymbolResult]:
        results: List[SymbolResult] = []
        for idx, symbol in enumerate(self.symbols, start=1):
            logging.info("Deep analysis %s/%s: %s", idx, len(self.symbols), symbol)
            try:
                res = self._run_one(symbol)
            except Exception as exc:
                logging.exception("Deep analysis failed for %s", symbol)
                # Persist error record.
                err_decision = {
                    "symbol": symbol,
                    "final_action": "IGNORE",
                    "confidence": 0.0,
                    "llm_status": "failed_before_prompt",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                json_path = self.outputs / "json" / f"{symbol}_deep_decision_{self.stamp}.json"
                write_json(json_path, err_decision)
                md_path = self.outputs / "markdown" / f"{symbol}_deep_analysis_{self.stamp}.md"
                write_text(md_path, f"# Deep analysis failed - {symbol}\n\n{type(exc).__name__}: {exc}\n")
                res = SymbolResult(symbol, symbol, "IGNORE", 0.0, "failed", None, "", None, "", str(json_path), str(md_path), [f"{type(exc).__name__}: {exc}"])
            results.append(res)
            if idx < len(self.symbols) and self.llm_delay_sec > 0 and not self.dry_run:
                time.sleep(self.llm_delay_sec)
        self._save_manifest(results)
        self._write_report(results)
        return results

    def _run_one(self, symbol: str) -> SymbolResult:
        heuristic = self.heuristic_loader.load(symbol)
        financial = self.financial_manager.get(
            symbol,
            force_refresh=self.force_refresh_financial,
            skip_filing_check=self.skip_filing_check,
        )
        aliases = self._build_aliases(symbol, financial.company_name)
        news = self.news_manager.get_for_symbol(symbol, aliases, force_refresh=self.force_refresh_news)
        user_insights = self._load_user_insights(symbol)
        rag_context = read_text(self.rag_context_path) if self.rag_context_path and self.rag_context_path.exists() else ""
        heuristic_md = heuristic.to_prompt_markdown()
        prompt = self.prompt_builder.build(
            symbol=symbol,
            company_name=financial.company_name,
            period_label=financial.period_label,
            heuristic_md=heuristic_md,
            financial_md=financial.markdown,
            news_md=news.markdown,
            user_insights=user_insights,
            rag_context=rag_context,
        )
        prompt_path = self.outputs / "prompts" / f"{symbol}_deep_prompt_{self.stamp}.md"
        write_text(prompt_path, prompt)
        fallback = self._fallback_decision(symbol, financial, heuristic)
        decision, meta = self.llm.analyze(prompt, symbol=symbol, fallback=fallback)
        decision["paths"] = {
            "heuristic_outputs": str(self.heuristic_loader.root),
            "financial_markdown_path": financial.markdown_path,
            "financial_cache_path": str(self.financial_manager.cache_root),
            "news_path": news.data_path,
            "prompt_path": str(prompt_path),
        }
        decision["metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "financial_period": financial.period_label,
            "financial_used_cache": financial.used_cache,
            "news_rows": news.rows,
            "news_used_cache": news.used_cache,
            "llm_meta": meta,
        }
        all_errors = list(heuristic.errors) + list(financial.errors) + list(news.errors)
        if all_errors:
            decision["pipeline_errors"] = all_errors
        json_path = self.outputs / "json" / f"{symbol}_deep_decision_{self.stamp}.json"
        write_json(json_path, decision)
        md_path = self.outputs / "markdown" / f"{symbol}_deep_analysis_{self.stamp}.md"
        write_text(md_path, self._decision_markdown(decision, financial, heuristic, news, json_path))
        return SymbolResult(
            symbol=symbol,
            company_name=financial.company_name,
            action=str(decision.get("final_action") or decision.get("action") or "IGNORE"),
            confidence=float(decision.get("confidence") or 0.0),
            llm_status=str(decision.get("llm_status") or meta.get("status") or "unknown"),
            heuristic_path=heuristic.files.get("candidates_ranked_latest.csv") or heuristic.files.get("watchlist_latest.csv"),
            financial_markdown_path=financial.markdown_path,
            news_path=news.data_path,
            prompt_path=str(prompt_path),
            json_path=str(json_path),
            markdown_path=str(md_path),
            errors=all_errors,
        )

    @staticmethod
    def _build_aliases(symbol: str, company_name: str) -> List[str]:
        aliases = [symbol]
        for part in re.split(r"[_\-\s]+", company_name or ""):
            part = part.strip()
            if len(part) >= 3:
                aliases.append(part)
        # Keep company phrase too, but avoid too-long regex list.
        if company_name and len(company_name) <= 80:
            aliases.append(company_name)
        return list(dict.fromkeys(aliases))

    def _load_user_insights(self, symbol: str) -> str:
        if not self.insights_path:
            return ""
        path_str = self.insights_path.replace("{symbol}", symbol)
        path = Path(path_str)
        if path.exists():
            return read_text(path)
        return ""

    @staticmethod
    def _fallback_decision(symbol: str, financial: FinancialContext, heuristic: HeuristicContext) -> Dict[str, Any]:
        row = heuristic.row or {}
        action = row.get("action") or row.get("heuristic_action") or row.get("final_action") or row.get("decision") or "WATCHLIST"
        confidence = _to_float(row.get("confidence"), 0.55) or 0.55
        return {
            "symbol": symbol,
            "company_name": financial.company_name,
            "period_label": financial.period_label,
            "final_action": normalize_action(action),
            "action": normalize_action(action),
            "confidence": max(0.0, min(1.0, confidence)),
            "investment_horizon": "3M",
            "thesis_summary": "Fallback từ heuristic/structured BCTC vì LLM chưa chạy hoặc lỗi.",
            "key_drivers": [],
            "financial_statement_readthrough": {
                "period": financial.period_label,
                "positive_points": [],
                "negative_points": [],
                "red_flags": [],
                "quality_of_earnings": "",
                "balance_sheet_risk": "",
                "cash_flow_quality": "",
            },
            "technical_readthrough": {"setup": "unclear", "trend_state": "", "flow_confirmation": "", "invalidations": []},
            "news_readthrough": {"material_news": [], "risk_news": [], "catalyst_news": []},
            "insights_readthrough": {"important_points": [], "uncertainties": []},
            "buy_plan": {
                "strategy": "wait",
                "entry_zone_low": _to_float(row.get("entry_price_low") or row.get("entry_low")),
                "entry_zone_high": _to_float(row.get("entry_price_high") or row.get("entry_high")),
                "stop_loss": _to_float(row.get("stop_loss")),
                "target_3m": _to_float(row.get("base_target") or row.get("target_price")),
                "target_1y": _to_float(row.get("bull_target")),
                "suggested_quantity": _to_int(row.get("suggested_quantity"), 0),
                "suggested_position_value": _to_float(row.get("suggested_position_value"), 0.0) or 0.0,
                "risk_notes": "Fallback deterministic.",
            },
            "sell_or_reduce_rules": [],
            "what_to_monitor_next_10_days": [],
            "data_gaps": [],
        }

    @staticmethod
    def _decision_markdown(decision: Mapping[str, Any], financial: FinancialContext, heuristic: HeuristicContext, news: NewsContext, json_path: Path) -> str:
        bp = decision.get("buy_plan") if isinstance(decision.get("buy_plan"), Mapping) else {}
        fs = decision.get("financial_statement_readthrough") if isinstance(decision.get("financial_statement_readthrough"), Mapping) else {}
        key_drivers = [f"- {x}" for x in _to_list(decision.get("key_drivers"), max_len=12)] or ["- N/A"]
        positives = [f"- {x}" for x in _to_list(fs.get("positive_points"), max_len=12)] or ["- N/A"]
        negatives = [f"- {x}" for x in (_to_list(fs.get("negative_points"), max_len=8) + _to_list(fs.get("red_flags"), max_len=8))] or ["- N/A"]
        monitors = [f"- {x}" for x in _to_list(decision.get("what_to_monitor_next_10_days"), max_len=12)] or ["- N/A"]
        lines = [
            f"# Deep LLM Analysis - {decision.get('symbol', financial.symbol)}",
            "",
            f"- Company: {decision.get('company_name', financial.company_name)}",
            f"- Action: **{decision.get('final_action', decision.get('action', 'IGNORE'))}**",
            f"- Confidence: {decision.get('confidence', 0)}",
            f"- Horizon: {decision.get('investment_horizon', '')}",
            f"- Financial period: {financial.period_label}",
            f"- JSON: `{json_path}`",
            "",
            "## Thesis",
            str(decision.get("thesis_summary") or ""),
            "",
            "## Key drivers",
        ]
        lines.extend(key_drivers)
        lines.extend([
            "",
            "## Financial statement readthrough",
            f"- Quality of earnings: {fs.get('quality_of_earnings', '')}",
            f"- Balance sheet risk: {fs.get('balance_sheet_risk', '')}",
            f"- Cash flow quality: {fs.get('cash_flow_quality', '')}",
            "",
            "### Positive points",
        ])
        lines.extend(positives)
        lines.extend([
            "",
            "### Negative points / red flags",
        ])
        lines.extend(negatives)
        lines.extend([
            "",
            "## Buy / sell plan",
            f"- Strategy: {bp.get('strategy', '')}",
            f"- Entry zone: {bp.get('entry_zone_low')} - {bp.get('entry_zone_high')}",
            f"- Stop loss: {bp.get('stop_loss')}",
            f"- Target 3M: {bp.get('target_3m')}",
            f"- Target 1Y: {bp.get('target_1y')}",
            f"- Suggested quantity: {bp.get('suggested_quantity')}",
            f"- Suggested position value: {bp.get('suggested_position_value')}",
            f"- Risk notes: {bp.get('risk_notes', '')}",
            "",
            "## Monitoring next 10 days",
        ])
        lines.extend(monitors)
        lines.extend([
            "",
            "## Data files",
            f"- Financial structured markdown: `{financial.markdown_path}`",
            f"- News cache: `{news.data_path}`",
            f"- Heuristic research markdown: `{heuristic.research_markdown_path}`",
        ])
        if decision.get("pipeline_errors"):
            lines.extend(["", "## Pipeline warnings/errors"])
            lines.extend([f"- {e}" for e in decision.get("pipeline_errors", [])])
        return "\n".join(lines).strip() + "\n"

    def _save_manifest(self, results: Sequence[SymbolResult]) -> None:
        manifest = {
            "generated_at": datetime.now().isoformat(),
            "symbols": self.symbols,
            "outputs": str(self.outputs),
            "financial_cache_path": str(self.financial_manager.cache_root),
            "news_cache_path": str(self.news_manager.cache_root),
            "results_path": str(self.results_path),
            "dry_run": self.dry_run,
            "results": [r.__dict__ for r in results],
        }
        write_json(self.outputs / f"deep_symbol_manifest_{self.stamp}.json", manifest)

    def _write_report(self, results: Sequence[SymbolResult]) -> None:
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "DEEP SYMBOL LLM ANALYSIS REPORT",
            "=" * 80,
            f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
            f"Symbols: {', '.join(self.symbols)}",
            f"Financial cache path: {self.financial_manager.cache_root}",
            f"Outputs: {self.outputs}",
            "",
            "ACTION SUMMARY",
            "-" * 80,
        ]
        counts = {a: 0 for a in ACTION_ORDER}
        for r in results:
            counts[normalize_action(r.action)] = counts.get(normalize_action(r.action), 0) + 1
        for a in ACTION_ORDER:
            lines.append(f"{a:18s}: {counts.get(a, 0)}")
        lines.extend(["", "BUY CANDIDATES", "-" * 80])
        buys = [r for r in results if normalize_action(r.action) == "BUY_CANDIDATE"]
        if buys:
            for r in buys:
                lines.append(f"{r.symbol:8s} | {r.company_name[:36]:36s} | conf={r.confidence:.2f} | {r.markdown_path}")
        else:
            lines.append("Không có symbol nào đáng để BUY.")
        lines.extend(["", "WATCHLIST", "-" * 80])
        watch = [r for r in results if normalize_action(r.action) == "WATCHLIST"]
        if watch:
            for r in watch:
                lines.append(f"{r.symbol:8s} | {r.company_name[:36]:36s} | conf={r.confidence:.2f} | {r.markdown_path}")
        else:
            lines.append("Không có symbol nào đáng để WATCH.")
        lines.extend(["", "ALL RESULTS", "-" * 80])
        lines.append("symbol | action | confidence | llm_status | financial_markdown | news_cache | markdown")
        for r in results:
            lines.append(
                f"{r.symbol:8s} | {normalize_action(r.action):18s} | {r.confidence:.2f} | {r.llm_status:8s} | {r.financial_markdown_path} | {r.news_path or 'N/A'} | {r.markdown_path}"
            )
            for e in r.errors[:8]:
                lines.append(f"  ! {e}")
        text = "\n".join(lines).strip() + "\n"
        write_text(self.results_path, text)
        print(text)
        print(f"\nReport saved: {self.results_path}")
        print(f"Manifest saved: {self.outputs / ('deep_symbol_manifest_' + self.stamp + '.json')}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deep LLM analyzer for user-selected symbols using structured vnstock Fundamental BCTC markdown.")
    parser.add_argument("--symbols", default=None, help="Comma/space separated symbols, e.g. TCB,FPT,MBS")
    parser.add_argument("--symbols_file", default=None, help="CSV/TXT file containing symbols. CSV should have symbol/ticker column.")
    parser.add_argument("--heuristic_outputs", required=True, help="Folder from previous heuristic pipeline, e.g. ./outputs/trade_pipeline_integrate_llm")
    parser.add_argument("--config", default="./configs/trade_pipeline_integrate_llm.json", help="Pipeline/LLM config JSON")
    parser.add_argument("--financial_cache_path", default="./data/financial_statements", help="Root folder for structured BCTC markdown cache generated from vnstock Fundamental tables.")
    # Deprecated alias retained silently so old commands do not crash; it maps to financial_cache_path.
    parser.add_argument("--financial_statement_path", dest="financial_cache_path", help=argparse.SUPPRESS)
    parser.add_argument("--news_cache_path", default="./data/news_cache", help="Root folder for news cache")
    parser.add_argument("--news_config", default=None, help="News config path. Defaults to ./configs/news_deep_symbol.json if it exists, otherwise ./configs/news.json")
    parser.add_argument("--outputs", default="./outputs/deep_symbol_llm", help="Output folder for prompts/json/markdown")
    parser.add_argument("--results", default="./results/deep_symbol_llm_report_{date}.txt", help="Report path, supports {date}/{datetime}/{timestamp}/{stamp}")
    parser.add_argument("--prompt_template", default="./configs/deep_symbol_trade_prompt_template.md", help="Prompt template markdown path")
    parser.add_argument("--insights_path", default=None, help="Optional user insight markdown path; supports {symbol}")
    parser.add_argument("--rag_context_path", default="./configs/rag_context.md", help="Optional RAG/playbook markdown path")
    parser.add_argument("--no_news", action="store_true", help="Disable news crawling/cache and omit news context")
    parser.add_argument("--force_refresh_news", action="store_true", help="Ignore fresh news cache and crawl again")
    parser.add_argument("--force_refresh_financial", action="store_true", help="Regenerate structured BCTC markdown even when latest-quarter cache exists")
    parser.add_argument("--skip_filing_check", action="store_true", help="Do not call filing() to check for a newer quarter; use latest local cache if available")
    parser.add_argument("--news_ttl_days", type=int, default=10, help="Delete/refresh news cache older than N days")
    parser.add_argument("--dry_run", action="store_true", help="Build prompt/data but do not call LLM")
    parser.add_argument("--llm_delay_sec", type=float, default=8.0, help="Sleep between symbol LLM calls")
    parser.add_argument("--filing_doc_type", default="financial_report", help="doc_type passed to Fundamental().equity(symbol).filing(doc_type=...)")
    parser.add_argument("--log_level", default="INFO")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")
    symbols = parse_symbols(args.symbols, args.symbols_file)
    stamp = now_stamp()
    results_path = render_path_template(args.results, stamp)
    pipeline = DeepSymbolPipeline(
        symbols=symbols,
        heuristic_outputs=args.heuristic_outputs,
        config_path=args.config,
        financial_cache_path=args.financial_cache_path,
        news_cache_path=args.news_cache_path,
        outputs=args.outputs,
        results_path=results_path,
        news_config=args.news_config,
        prompt_template=args.prompt_template,
        insights_path=args.insights_path,
        rag_context_path=args.rag_context_path,
        no_news=args.no_news,
        force_refresh_news=args.force_refresh_news,
        force_refresh_financial=args.force_refresh_financial,
        skip_filing_check=args.skip_filing_check,
        news_ttl_days=args.news_ttl_days,
        dry_run=args.dry_run,
        llm_delay_sec=args.llm_delay_sec,
        filing_doc_type=args.filing_doc_type,
    )
    pipeline.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
