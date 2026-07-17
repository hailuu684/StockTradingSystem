"""
Production-oriented full trade pipeline for the existing Vnstock project.

This module is intentionally additive: copy it into your repo root, for example:

    Stocks/full_trade_pipeline_integrate_llm.py

It does not modify main.py, get_information.py, or any existing scripts. It uses the
syntax already verified in your repository and avoids unsupported Insights calls such
as Insights.sector('technology').members().

Supported modes
---------------
1. initial
   Build a bank + technology universe, collect market/fundamental/insights/analytics
   data, create Morgan-Stanley-style markdown research packs, run a trade analyzer,
   and save candidates/watchlist outputs.

2. daily_news
   Load the latest watchlist, fetch news through the existing scripts.get_news_layer
   when available, filter symbol-related articles, create daily monitoring markdown,
   and save alert-ready JSON for future Telegram integration.

CLI examples
------------
python full_trade_pipeline_integrate_llm.py --write-default-config ./configs/trade_pipeline_integrate_llm.json
python full_trade_pipeline_integrate_llm.py --mode initial --config ./configs/trade_pipeline_integrate_llm.json
python full_trade_pipeline_integrate_llm.py --mode daily_news --config ./configs/trade_pipeline_integrate_llm.json
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
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

JsonLike = Union[str, Path, Mapping[str, Any], SimpleNamespace]


DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "2.1.0-integrate-llm",
    "project_name": "vnstock_ms_style_integrate_llm_pipeline",
    "paths": {
        "repo_root": ".",
        "output_dir": "./outputs/trade_pipeline_integrate_llm",
        "news_config_path": "./configs/news.json",
        "insights_strategy_path": "./configs/insights_filter_strategy.json",
        "rag_markdown_path": "./configs/rag_context.md",
        "user_option_insights_path": "./configs/user_option_insights.md"
    },
    "reports": {
        "enabled": True,
        "dir": "./results",
        "file_path": "./results/reports_trade_pipeline_integrate_llm_{date}.txt",
        "print_to_console": True,
        "top_n": 20
    },
    "universe": {
        "target_sectors": ["bank", "technology"],
        "exchanges": ["hsx", "hnx", "upcom"],
        "limit_per_screener_call": 500,
        "max_symbols_after_universe": 120,
        "max_symbols_to_analyze": 30,
        "min_price_vnd": 5000,
        "min_adtv_vnd": 5000000000,
        "allow_static_fallback": True,
        "strict_sector_filter_after_screener": True,
        "enable_sector_filter_in_screener": False,
        "screener_strategies": [
            "GARP",
            "CANSLIM_William_O_Neil",
            "SEPA_Mark_Minervini",
            "breakout_strategy",
            "growth_strategy",
            "value_strategy"
        ],
        "sector_aliases": {
            "bank": [
                "bank", "banks", "banking", "ngan hang", "ngân hàng", "nganhang",
                "commercial bank", "financial services", "8350"
            ],
            "technology": [
                "technology", "information technology", "software", "it services", "it",
                "ict", "telecommunication", "telecom", "digital", "cloud", "ai",
                "cong nghe", "công nghệ", "9530", "9570"
            ]
        },
        "fallback_symbols_by_sector": {
            "bank": [
                "VCB", "BID", "CTG", "TCB", "VPB", "MBB", "ACB", "STB", "HDB",
                "VIB", "TPB", "SHB", "EIB", "MSB", "LPB", "OCB", "SSB", "NAB", "BAB", "ABB", "BVB", "KLB"
            ],
            "technology": [
                "FPT", "CMG", "ELC", "ITD", "ICT", "SAM", "VGI", "FOX", "CTR", "MFS", "YEG"
            ]
        }
    },
    "market": {
        "index_symbol": "VNINDEX",
        "length": "1Y",
        "interval": "1D",
        "ohlcv_price_multiplier": 1000.0,
        "use_bulk_quote": True,
        "collect_intraday": False,
        "intraday_limit": 500,
        "snapshot_methods": ["quote", "summary", "order_book", "price_board", "session_stats", "trading_stats"],
        "historical_methods": ["ohlcv", "history", "trade_history", "foreign_flow", "proprietary_flow", "volume_profile"]
    },
    "insights": {
        "enabled": True,
        "ranking": {"index": "VNINDEX", "limit": 10, "date": None},
        "screener": {"criteria_lang": "en"},
        "flow": {"enabled": True},
        "sentiment": {"enabled": True},
        "collect_unsupported_equity_sector_domains": False
    },
    "fundamental": {
        "enabled": True,
        "max_symbols_for_deep_fundamental": 20,
        "periods": {
            "income_statement": "year",
            "balance_sheet": "quarter",
            "cash_flow": "year",
            "ratio": "quarter",
            "note": "year"
        },
        "note_lang": "vi",
        "financial_health": {"scorecard": "auto", "limit": 4},
        "llm_note_analysis": False
    },
    "analytics": {
        "enabled": True,
        "index_symbol": "VNINDEX",
        "pe_duration": "1Y",
        "pb_duration": "3Y",
        "evaluation_duration": "5Y"
    },
    "technical_strategy": {
        "rsi_period": 14,
        "atr_period": 14,
        "ma_short": 20,
        "ma_mid": 50,
        "ma_long": 200,
        "breakout_windows": [20, 55],
        "volume_window": 20,
        "min_volume_ratio_breakout": 1.5,
        "max_rsi_for_new_entry": 78
    },
    "ms_style_scenario": {
        "horizons": {"3M": 63, "1Y": 252},
        "min_expected_return_3m": 0.10,
        "min_expected_return_1y": 0.18,
        "min_risk_reward": 2.0,
        "max_bear_probability": 0.40,
        "bank_target_pb_floor": 0.8,
        "bank_target_pb_cap": 2.4,
        "tech_target_pe_floor": 10.0,
        "tech_target_pe_cap": 35.0
    },
    "risk": {
        "portfolio_value_vnd": 1000000000,
        "risk_per_trade_pct": 0.0075,
        "max_position_pct": 0.15,
        "max_sector_pct": 0.30,
        "max_open_positions": 10,
        "atr_stop_multiplier": 1.8,
        "swing_low_window": 20,
        "entry_buffer_pct": 0.01,
        "min_liquidity_participation_pct": 0.05
    },
    "agent": {
        "enabled": True,
        "provider": "project_gemini",
        "mode": "compare",
        "llm_mode": "compare",
        "decision_source": "llm",
        "api_key_env": "GEMINI_API_KEY",
        "api_key": None,
        "endpoint_url": None,
        "model": "gemini-2.5-flash",
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "timeout": 60,
        "save_prompt": True,
        "require_json": True,
        "fallback_to_heuristic_on_error": True
    },
    "llm_config": {
        "provider": "gemini",
        "api_key_env": "GEMINI_API_KEY",
        "api_key": None,
        "llm_model": "gemini-2.5-flash",
        "temperature": 0.2,
        "max_output_tokens": 4096,
        "require_json": True
    },
    "daily_news": {
        "enabled": True,
        "watchlist_path": "./outputs/trade_pipeline_integrate_llm/watchlist_latest.csv",
        "lookback_days": 3,
        "max_articles_per_symbol": 20,
        "company_aliases": {
            "TCB": ["Techcombank", "Ngân hàng Kỹ thương", "Kỹ thương Việt Nam"],
            "FPT": ["FPT", "FPT Corporation", "Công ty FPT"]
        },
        "severe_risk_keywords": [
            "điều tra", "thanh tra", "khởi tố", "bắt", "hủy niêm yết", "kiểm soát", "cảnh báo",
            "trái phiếu", "vỡ nợ", "chậm trả", "lỗ", "suy giảm", "phạt", "fraud", "lawsuit"
        ],
        "positive_keywords": [
            "lãi kỷ lục", "tăng trưởng", "ký hợp đồng", "cổ tức", "chia thưởng", "mua lại cổ phiếu",
            "nâng hạng", "dự án mới", "lợi nhuận tăng", "đơn hàng", "ai", "cloud", "chuyển đổi số"
        ]
    },
    "runtime": {
        "log_level": "INFO",
        "fail_fast": False,
        "sleep_between_symbols": 0.2,
        "save_raw_data": False,
        "csv_encoding": "utf-8-sig",
        "deduplicate_news_by_url": True
    }
}


class PipelineConfigError(ValueError):
    """Raised when configuration is missing or malformed."""


class PipelineRuntimeError(RuntimeError):
    """Raised when a runtime dependency/API call fails in fail-fast mode."""


@dataclass
class SymbolAnalysis:
    symbol: str
    sector: str
    market_data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    fundamental_data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    insights_data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    analytics_data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    news_data: pd.DataFrame = field(default_factory=pd.DataFrame)
    option_markdown: str = ""
    technical: Dict[str, Any] = field(default_factory=dict)
    flow: Dict[str, Any] = field(default_factory=dict)
    fundamental_summary: Dict[str, Any] = field(default_factory=dict)
    insight_summary: Dict[str, Any] = field(default_factory=dict)
    scenario: Dict[str, Any] = field(default_factory=dict)
    scores: Dict[str, float] = field(default_factory=dict)
    decision: Dict[str, Any] = field(default_factory=dict)
    llm_decision: Dict[str, Any] = field(default_factory=dict)
    heuristic_decision: Dict[str, Any] = field(default_factory=dict)
    research_markdown: str = ""
    prompt: str = ""
    errors: List[Dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Generic utilities
# ---------------------------------------------------------------------------


def load_config(config: Optional[JsonLike] = None) -> Dict[str, Any]:
    if config is None:
        return deep_copy(DEFAULT_CONFIG)
    if isinstance(config, (str, Path)):
        path = Path(config)
        if not path.exists():
            raise PipelineConfigError(f"Config file not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        return deep_merge(deep_copy(DEFAULT_CONFIG), user_cfg)
    if isinstance(config, Mapping):
        return deep_merge(deep_copy(DEFAULT_CONFIG), dict(config))
    if hasattr(config, "__dict__"):
        return deep_merge(deep_copy(DEFAULT_CONFIG), dict(vars(config)))
    raise PipelineConfigError("config must be None, a JSON path, Mapping, or SimpleNamespace-like object")


def write_default_config(path: Union[str, Path]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    return p


def deep_copy(obj: Any) -> Any:
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def deep_merge(base: MutableMapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(dict(out[key]), value)
        else:
            out[key] = value
    return out


def get_in(obj: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = obj
    for part in dotted.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def set_in(obj: MutableMapping[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted-path value in a nested mutable config mapping."""
    cur: MutableMapping[str, Any] = obj
    parts = dotted.split(".")
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, MutableMapping):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def resolve_template_path(path_value: Any, *, stamp: Optional[str] = None) -> Optional[Path]:
    """Resolve CLI/config path templates such as reports_{date}.txt."""
    if not path_value:
        return None
    stamp = stamp or now_stamp()
    date = datetime.now().strftime("%Y%m%d")
    dt = datetime.now().strftime("%Y%m%d_%H%M%S")
    text = str(path_value).format(date=date, datetime=dt, timestamp=stamp, stamp=stamp)
    return Path(text)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Union[str, Path]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def add_repo_root_to_path(cfg: Mapping[str, Any]) -> Path:
    root = Path(get_in(cfg, "paths.repo_root", ".")).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def setup_logging(cfg: Mapping[str, Any]) -> None:
    level_name = str(get_in(cfg, "runtime.log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")


def clean_symbol(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(value).upper().strip())


def to_frame(obj: Any) -> pd.DataFrame:
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if isinstance(obj, list):
        return pd.DataFrame(obj)
    if isinstance(obj, dict):
        if all(isinstance(v, (list, tuple, pd.Series, np.ndarray)) for v in obj.values()):
            try:
                return pd.DataFrame(obj)
            except Exception:
                return pd.DataFrame([obj])
        return pd.DataFrame([obj])
    return pd.DataFrame([{"value": obj}])


def safe_call(name: str, fn: Callable[[], Any], fail_fast: bool = False) -> Tuple[pd.DataFrame, Optional[str]]:
    try:
        return to_frame(fn()), None
    except Exception as exc:
        msg = f"{name} failed: {type(exc).__name__}: {exc}"
        logging.warning(msg)
        if fail_fast:
            raise PipelineRuntimeError(msg) from exc
        return pd.DataFrame(), msg


def first_col(df: pd.DataFrame, candidates: Sequence[str], contains: bool = False) -> Optional[str]:
    if df is None or df.empty:
        return None
    lower_map = {str(c).lower(): c for c in df.columns}
    for cand in candidates:
        key = str(cand).lower()
        if key in lower_map:
            return str(lower_map[key])
    if contains:
        for c in df.columns:
            c_low = str(c).lower()
            if any(str(cand).lower() in c_low for cand in candidates):
                return str(c)
    return None


def as_numeric(value: Any, default: float = np.nan) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float, np.integer, np.floating)):
        try:
            return float(value)
        except Exception:
            return default
    text = str(value).replace(",", "").replace("%", "").strip()
    if not text or text.lower() in {"nan", "none", "null", "-"}:
        return default
    try:
        return float(text)
    except Exception:
        return default


DATE_FORMATS: Tuple[str, ...] = (
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


def parse_datetime_series(values: Any, dayfirst: bool = True) -> pd.Series:
    """
    Parse mixed date columns without Pandas' noisy dateutil format-inference warning.

    Vnstock/news data can return ISO timestamps, Vietnamese DD/MM/YYYY dates, or
    already-typed datetime columns. We parse known formats explicitly first, then
    use pandas format='mixed' only as a last tolerant fallback.
    """
    if isinstance(values, pd.Series):
        s = values.copy()
    else:
        s = pd.Series(values)
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    text = s.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(["", "none", "null", "nan", "nat", "-"]))

    for fmt in DATE_FORMATS:
        mask = out.isna() & text.notna()
        if not bool(mask.any()):
            break
        parsed = pd.to_datetime(text.loc[mask], format=fmt, errors="coerce")
        out.loc[mask] = parsed

    mask = out.isna() & text.notna()
    if bool(mask.any()):
        try:
            fallback = pd.to_datetime(text.loc[mask], format="mixed", errors="coerce", dayfirst=dayfirst)
        except TypeError:
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Could not infer format.*", category=UserWarning)
                fallback = pd.to_datetime(text.loc[mask], errors="coerce", dayfirst=dayfirst)
        out.loc[mask] = fallback
    return out


def latest_row(df: pd.DataFrame, time_candidates: Sequence[str] = ("time", "date", "trading_date", "reportDate", "report_date", "period")) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype="object")
    work = df.copy()
    tcol = first_col(work, time_candidates, contains=False)
    if tcol:
        try:
            work[tcol] = parse_datetime_series(work[tcol])
            work = work.sort_values(tcol)
        except Exception:
            pass
    return work.iloc[-1]


def normalize_price_to_vnd(price: Any, multiplier: float = 1000.0) -> float:
    p = as_numeric(price)
    if not np.isfinite(p):
        return np.nan
    if 0 < p < 1000:
        return p * multiplier
    return p


def choose_text_columns(df: pd.DataFrame) -> List[str]:
    candidates = ["title", "short_description", "summary", "content", "tags", "category", "source"]
    return [c for c in candidates if c in df.columns]


def write_json(path: Union[str, Path], obj: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Imports from vnstock and existing repo
# ---------------------------------------------------------------------------


def import_vnstock_data_classes() -> Dict[str, Any]:
    try:
        from vnstock_data import Analytics, Fundamental, Insights, Market, Reference  # type: ignore
    except Exception as exc:
        raise PipelineRuntimeError("vnstock_data is not importable. Activate your Vnstock virtualenv first.") from exc
    return {"Market": Market, "Reference": Reference, "Insights": Insights, "Fundamental": Fundamental, "Analytics": Analytics}


def import_existing_news_layer(cfg: Mapping[str, Any]) -> Callable[[Any], Dict[str, Any]]:
    add_repo_root_to_path(cfg)
    try:
        mod = __import__("scripts.get_news_layer", fromlist=["get_news_layer", "news_layer", "get_news"])
    except Exception as exc:
        raise PipelineRuntimeError("Cannot import scripts.get_news_layer from repo.") from exc
    for attr in ("get_news_layer", "news_layer", "get_news"):
        fn = getattr(mod, attr, None)
        if callable(fn):
            return fn
    raise PipelineRuntimeError("scripts.get_news_layer exists but has no get_news_layer/news_layer/get_news function.")


# ---------------------------------------------------------------------------
# Universe and Insights
# ---------------------------------------------------------------------------


class UniverseBuilder:
    """Build universe using only supported Insights API tree: screener + static fallback."""

    def __init__(self, cfg: Mapping[str, Any]):
        self.cfg = cfg
        self.fail_fast = bool(get_in(cfg, "runtime.fail_fast", False))
        self.classes = import_vnstock_data_classes()

    def build(self) -> pd.DataFrame:
        frames = self._from_screener_strategies()
        if bool(get_in(self.cfg, "universe.allow_static_fallback", True)):
            frames.append(self._from_static_fallback())
        frames = [f for f in frames if f is not None and not f.empty]
        if not frames:
            raise PipelineRuntimeError("No universe rows found from screener/static fallback.")
        universe = pd.concat(frames, ignore_index=True, sort=False)
        universe = self._normalize_universe(universe)
        universe = self._apply_tradeability_filter(universe)
        universe = self._enforce_sector_filter(universe)
        universe = universe.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
        max_n = int(get_in(self.cfg, "universe.max_symbols_after_universe", 120))
        return universe.head(max_n)

    def _from_screener_strategies(self) -> List[pd.DataFrame]:
        Insights = self.classes["Insights"]
        ins = Insights()
        strategies = self._load_strategy_filters()
        strategy_names = list(get_in(self.cfg, "universe.screener_strategies", []))
        exchanges = list(get_in(self.cfg, "universe.exchanges", ["hsx", "hnx", "upcom"]))
        limit = int(get_in(self.cfg, "universe.limit_per_screener_call", 500))
        frames: List[pd.DataFrame] = []

        for strategy_name in strategy_names:
            base_filters = strategies.get(strategy_name, [])
            if not isinstance(base_filters, list):
                continue
            for exchange in exchanges:
                filters = self._replace_or_add_exchange(base_filters, exchange)
                # Do not add sector filter by default. Sector values differ by vendor; filter after output.
                if bool(get_in(self.cfg, "universe.enable_sector_filter_in_screener", False)):
                    for sector in get_in(self.cfg, "universe.target_sectors", ["bank", "technology"]):
                        sector_filters = self._replace_or_add_sector(filters, sector)
                        df, err = safe_call(
                            f"Insights.screener.filter({strategy_name}/{exchange}/{sector})",
                            lambda sector_filters=sector_filters: ins.screener.filter(filters=sector_filters, limit=limit),
                            fail_fast=False,
                        )
                        if not df.empty:
                            df["source_universe"] = "screener_sector_filter"
                            df["source_strategy"] = strategy_name
                            df["sector_hint"] = sector
                            frames.append(df)
                        elif err:
                            logging.debug(err)
                else:
                    df, err = safe_call(
                        f"Insights.screener.filter({strategy_name}/{exchange})",
                        lambda filters=filters: ins.screener.filter(filters=filters, limit=limit),
                        fail_fast=self.fail_fast,
                    )
                    if not df.empty:
                        df["source_universe"] = "screener"
                        df["source_strategy"] = strategy_name
                        frames.append(df)
                    elif err:
                        logging.debug(err)

        # Broad liquid pass to catch bank/technology names missed by strict strategy filters.
        for exchange in exchanges:
            broad_filters = [
                {"name": "exchange", "conditionOptions": [{"type": "value", "value": exchange}]},
                {"name": "adtv", "extraName": "30Days", "conditionOptions": [{"from": get_in(self.cfg, "universe.min_adtv_vnd", 0), "to": 10**15}]},
                {"name": "marketPrice", "conditionOptions": [{"from": get_in(self.cfg, "universe.min_price_vnd", 0), "to": 10**9}]},
            ]
            df, err = safe_call(
                f"Insights.screener.filter(broad_liquid/{exchange})",
                lambda broad_filters=broad_filters: ins.screener.filter(filters=broad_filters, limit=limit),
                fail_fast=False,
            )
            if not df.empty:
                df["source_universe"] = "screener_broad_liquid"
                df["source_strategy"] = "broad_liquid"
                frames.append(df)
            elif err:
                logging.debug(err)
        return frames

    def _from_static_fallback(self) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []
        fallback = get_in(self.cfg, "universe.fallback_symbols_by_sector", {}) or {}
        for sector, symbols in fallback.items():
            for sym in symbols:
                rows.append({"symbol": clean_symbol(sym), "sector_hint": sector, "source_universe": "static_fallback"})
        return pd.DataFrame(rows)

    def _load_strategy_filters(self) -> Dict[str, Any]:
        path = get_in(self.cfg, "paths.insights_strategy_path")
        if not path:
            return {}
        p = Path(path)
        if not p.exists():
            logging.warning("Insights strategy file not found: %s", p)
            return {}
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logging.warning("Cannot read insights strategy file %s: %s", p, exc)
            return {}

    @staticmethod
    def _replace_or_add_exchange(filters: Sequence[Mapping[str, Any]], exchange: str) -> List[Dict[str, Any]]:
        new_filters = json.loads(json.dumps(list(filters), ensure_ascii=False, default=str))
        found = False
        for f in new_filters:
            if str(f.get("name", "")).lower() == "exchange":
                f["conditionOptions"] = [{"type": "value", "value": exchange}]
                found = True
        if not found:
            new_filters.insert(0, {"name": "exchange", "conditionOptions": [{"type": "value", "value": exchange}]})
        return new_filters

    @staticmethod
    def _replace_or_add_sector(filters: Sequence[Mapping[str, Any]], sector: str) -> List[Dict[str, Any]]:
        new_filters = json.loads(json.dumps(list(filters), ensure_ascii=False, default=str))
        found = False
        for f in new_filters:
            if str(f.get("name", "")).lower() == "sector":
                f["conditionOptions"] = [{"type": "value", "value": sector}]
                found = True
        if not found:
            new_filters.append({"name": "sector", "conditionOptions": [{"type": "value", "value": sector}]})
        return new_filters

    def _normalize_universe(self, df: pd.DataFrame) -> pd.DataFrame:
        work = df.copy()
        sym_col = first_col(work, ["symbol", "ticker", "code", "stock_code", "organ_code", "stockCode"], contains=True)
        if sym_col is None:
            raise PipelineRuntimeError("Universe frame has no symbol/ticker/code-like column.")
        work["symbol"] = work[sym_col].map(clean_symbol)
        work = work[work["symbol"].astype(bool)].copy()

        sector_col = first_col(work, ["sector", "sector_lv1", "sectorLv1", "sector_lv2", "sectorLv2", "industry", "icb"], contains=True)
        if sector_col is not None:
            work["sector_raw"] = work[sector_col].astype(str)
        else:
            work["sector_raw"] = work.get("sector_hint", "")
        work["sector"] = work.apply(lambda r: self._classify_sector(r.get("symbol"), r.get("sector_raw"), r.get("sector_hint")), axis=1)
        return work

    def _classify_sector(self, symbol: Any, raw: Any = "", hint: Any = "") -> str:
        text = f"{raw or ''} {hint or ''}".lower()
        aliases = get_in(self.cfg, "universe.sector_aliases", {}) or {}
        for canonical, words in aliases.items():
            if any(str(w).lower() in text for w in words):
                return str(canonical)
        sym = clean_symbol(symbol)
        for sector, symbols in (get_in(self.cfg, "universe.fallback_symbols_by_sector", {}) or {}).items():
            if sym in {clean_symbol(s) for s in symbols}:
                return str(sector)
        return "unknown"

    def _apply_tradeability_filter(self, universe: pd.DataFrame) -> pd.DataFrame:
        work = universe.copy()
        price_col = first_col(work, ["price", "market_price", "marketPrice", "close", "close_price"], contains=True)
        if price_col is not None:
            price = pd.to_numeric(work[price_col], errors="coerce")
            min_price = float(get_in(self.cfg, "universe.min_price_vnd", 0))
            # Screener price can be VND or thousand VND depending provider; only filter obvious VND values.
            work = work[(price.isna()) | (price >= min_price) | ((price > 0) & (price < 1000) & (price * 1000 >= min_price))].copy()
        adtv_col = first_col(work, ["adtv", "trading_value_adtv", "tradingValueAdtv"], contains=True)
        if adtv_col is not None:
            adtv = pd.to_numeric(work[adtv_col], errors="coerce")
            min_adtv = float(get_in(self.cfg, "universe.min_adtv_vnd", 0))
            work = work[(adtv.isna()) | (adtv >= min_adtv)].copy()
        return work

    def _enforce_sector_filter(self, universe: pd.DataFrame) -> pd.DataFrame:
        target = {str(s).lower() for s in get_in(self.cfg, "universe.target_sectors", ["bank", "technology"])}
        if bool(get_in(self.cfg, "universe.strict_sector_filter_after_screener", True)):
            filtered = universe[universe["sector"].astype(str).str.lower().isin(target)].copy()
            if not filtered.empty:
                return filtered
        return universe


class InsightsCollector:
    """Collect Insights data from supported tree only: flow, ranking, screener, sentiment."""

    def __init__(self, cfg: Mapping[str, Any]):
        self.cfg = cfg
        self.fail_fast = bool(get_in(cfg, "runtime.fail_fast", False))
        self.classes = import_vnstock_data_classes()
        self._insights = None

    @property
    def insights(self):
        if self._insights is None:
            self._insights = self.classes["Insights"]()
        return self._insights

    def collect_global(self) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, str]]]:
        if not bool(get_in(self.cfg, "insights.enabled", True)):
            return {}, []
        data: Dict[str, pd.DataFrame] = {}
        errors: List[Dict[str, str]] = []

        scr = self.insights.screener
        criteria_lang = str(get_in(self.cfg, "insights.screener.criteria_lang", "en"))
        df, err = safe_call("Insights.screener.criteria(lang)", lambda: scr.criteria(lang=criteria_lang), fail_fast=False)
        if df.empty:
            df, err = safe_call("Insights.screener.criteria()", lambda: scr.criteria(), fail_fast=False)
        data["screener_criteria"] = df
        if err:
            errors.append({"layer": "insights", "method": "screener.criteria", "error": err})

        rk_cfg = get_in(self.cfg, "insights.ranking", {}) or {}
        idx = rk_cfg.get("index", "VNINDEX")
        limit = int(rk_cfg.get("limit", 10))
        date = rk_cfg.get("date")
        rk = self.insights.ranking
        ranking_calls = {
            "ranking_gainer": lambda: rk.gainer(index=idx, limit=limit),
            "ranking_loser": lambda: rk.loser(index=idx, limit=limit),
            "ranking_value": lambda: rk.value(index=idx, limit=limit),
            "ranking_volume": lambda: rk.volume(index=idx, limit=limit),
            "ranking_deal": lambda: rk.deal(index=idx, limit=limit),
            "ranking_foreign_buy": lambda: rk.foreign_buy(date=date, limit=limit) if date else rk.foreign_buy(limit=limit),
            "ranking_foreign_sell": lambda: rk.foreign_sell(date=date, limit=limit) if date else rk.foreign_sell(limit=limit),
        }
        for name, fn in ranking_calls.items():
            df, err = safe_call(f"Insights.{name}", fn, fail_fast=False)
            data[name] = df
            if err:
                errors.append({"layer": "insights", "method": name, "error": err})

        if bool(get_in(self.cfg, "insights.flow.enabled", True)):
            flow = self.insights.flow
            for method in ("active", "foreign", "proprietary"):
                if hasattr(flow, method):
                    df, err = safe_call(f"Insights.flow.{method}", lambda method=method: getattr(flow, method)(), fail_fast=False)
                    data[f"flow_{method}"] = df
                    if err:
                        errors.append({"layer": "insights", "method": f"flow.{method}", "error": err})

        if bool(get_in(self.cfg, "insights.sentiment.enabled", True)):
            sentiment = self.insights.sentiment
            for method in ("breadth", "contribution", "heatmap"):
                if hasattr(sentiment, method):
                    df, err = safe_call(f"Insights.sentiment.{method}", lambda method=method: getattr(sentiment, method)(), fail_fast=False)
                    data[f"sentiment_{method}"] = df
                    if err:
                        errors.append({"layer": "insights", "method": f"sentiment.{method}", "error": err})

        return data, errors

    @staticmethod
    def subset_for_symbol(global_data: Mapping[str, pd.DataFrame], symbol: str) -> Dict[str, pd.DataFrame]:
        sym = clean_symbol(symbol)
        out: Dict[str, pd.DataFrame] = {}
        for name, df in global_data.items():
            if df is None or df.empty:
                continue
            sym_col = first_col(df, ["symbol", "ticker", "code", "stock_code", "organ_code"], contains=True)
            if sym_col is None:
                continue
            subset = df[df[sym_col].map(clean_symbol) == sym].copy()
            if not subset.empty:
                out[name] = subset
        return out


# ---------------------------------------------------------------------------
# Data collectors
# ---------------------------------------------------------------------------


class DataCollector:
    def __init__(self, cfg: Mapping[str, Any]):
        self.cfg = cfg
        self.fail_fast = bool(get_in(cfg, "runtime.fail_fast", False))
        self.classes = import_vnstock_data_classes()
        self._market = None
        self._fundamental = None
        self._analytics = None

    @property
    def market(self):
        if self._market is None:
            self._market = self.classes["Market"]()
        return self._market

    @property
    def fundamental(self):
        if self._fundamental is None:
            self._fundamental = self.classes["Fundamental"]()
        return self._fundamental

    @property
    def analytics(self):
        if self._analytics is None:
            self._analytics = self.classes["Analytics"]()
        return self._analytics

    def collect_bulk_quote(self, symbols: Sequence[str]) -> pd.DataFrame:
        symbols = [clean_symbol(s) for s in symbols if clean_symbol(s)]
        if not symbols:
            return pd.DataFrame()
        df, _ = safe_call("Market.quote(symbols)", lambda: self.market.quote(symbols), fail_fast=False)
        return df

    def collect_market_for_symbol(self, symbol: str) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, str]]]:
        symbol = clean_symbol(symbol)
        eq = self.market.equity(symbol)
        length = get_in(self.cfg, "market.length", "1Y")
        interval = get_in(self.cfg, "market.interval", "1D")
        collect_intraday = bool(get_in(self.cfg, "market.collect_intraday", False))
        intraday_limit = int(get_in(self.cfg, "market.intraday_limit", 500))
        data: Dict[str, pd.DataFrame] = {}
        errors: List[Dict[str, str]] = []

        call_specs: Dict[str, Callable[[], Any]] = {}
        for method in get_in(self.cfg, "market.historical_methods", []):
            if method == "ohlcv":
                call_specs["ohlcv"] = lambda eq=eq, length=length, interval=interval: self._call_ohlcv(eq, length, interval)
            elif method == "history":
                call_specs["history"] = lambda eq=eq, length=length: eq.history(length=length)
            elif method == "trade_history":
                call_specs["trade_history"] = lambda eq=eq: eq.trade_history()
            elif method == "foreign_flow":
                call_specs["foreign_flow"] = lambda eq=eq: eq.foreign_flow()
            elif method == "proprietary_flow":
                call_specs["proprietary_flow"] = lambda eq=eq: eq.proprietary_flow()
            elif method == "volume_profile":
                call_specs["volume_profile"] = lambda eq=eq: eq.volume_profile()
        for method in get_in(self.cfg, "market.snapshot_methods", []):
            if hasattr(eq, method):
                call_specs[str(method)] = lambda method=method, eq=eq: getattr(eq, method)()
        if collect_intraday:
            if hasattr(eq, "intraday"):
                call_specs["intraday"] = lambda eq=eq: eq.intraday()
            if hasattr(eq, "trades"):
                call_specs["trades"] = lambda eq=eq, intraday_limit=intraday_limit: eq.trades(limit=intraday_limit)

        for name, fn in call_specs.items():
            df, err = safe_call(f"Market.equity({symbol}).{name}", fn, fail_fast=self.fail_fast)
            data[name] = df
            if err:
                errors.append({"layer": "market", "method": name, "error": err})
        return data, errors

    @staticmethod
    def _call_ohlcv(eq: Any, length: Any, interval: Any) -> Any:
        try:
            return eq.ohlcv(length=length, interval=interval)
        except TypeError:
            return eq.ohlcv(length=length)

    def collect_index_market(self) -> Dict[str, pd.DataFrame]:
        index_symbol = str(get_in(self.cfg, "market.index_symbol", "VNINDEX"))
        idx = self.market.index(index_symbol)
        length = get_in(self.cfg, "market.length", "1Y")
        data: Dict[str, pd.DataFrame] = {}
        for name, fn in {
            "ohlcv": lambda: idx.ohlcv(length=length),
            "trade_history": lambda: idx.trade_history(),
            "stock_influence": lambda: idx.stock_influence(),
        }.items():
            df, _ = safe_call(f"Market.index({index_symbol}).{name}", fn, fail_fast=False)
            data[name] = df
        return data

    def collect_fundamental_for_symbol(self, symbol: str) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, str]]]:
        if not bool(get_in(self.cfg, "fundamental.enabled", True)):
            return {}, []
        symbol = clean_symbol(symbol)
        eq = self.fundamental.equity(symbol)
        periods = get_in(self.cfg, "fundamental.periods", {}) or {}
        note_lang = str(get_in(self.cfg, "fundamental.note_lang", "vi"))
        health_cfg = get_in(self.cfg, "fundamental.financial_health", {}) or {}
        calls = {
            "income_statement": lambda: eq.income_statement(period=periods.get("income_statement", "year")),
            "balance_sheet": lambda: eq.balance_sheet(period=periods.get("balance_sheet", "quarter")),
            "cash_flow": lambda: eq.cash_flow(period=periods.get("cash_flow", "year")),
            "ratio": lambda: eq.ratio(period=periods.get("ratio", "quarter")),
            "note": lambda: eq.note(period=periods.get("note", "year"), lang=note_lang),
            "filing": lambda: eq.filing(),
            "financial_health": lambda: eq.financial_health(scorecard=health_cfg.get("scorecard", "auto"), limit=int(health_cfg.get("limit", 4))),
        }
        data: Dict[str, pd.DataFrame] = {}
        errors: List[Dict[str, str]] = []
        for name, fn in calls.items():
            df, err = safe_call(f"Fundamental.equity({symbol}).{name}", fn, fail_fast=False)
            data[name] = df
            if err:
                errors.append({"layer": "fundamental", "method": name, "error": err})
        return data, errors

    def collect_analytics(self) -> Dict[str, pd.DataFrame]:
        if not bool(get_in(self.cfg, "analytics.enabled", True)):
            return {}
        index_symbol = str(get_in(self.cfg, "analytics.index_symbol", get_in(self.cfg, "market.index_symbol", "VNINDEX")))
        data: Dict[str, pd.DataFrame] = {}
        try:
            val = self.analytics.valuation(index=index_symbol)
        except TypeError:
            val = self.analytics.valuation(index_symbol)
        calls = {
            "market_pe": lambda: val.pe(duration=get_in(self.cfg, "analytics.pe_duration", "1Y")),
            "market_pb": lambda: val.pb(duration=get_in(self.cfg, "analytics.pb_duration", "3Y")),
            "market_evaluation": lambda: val.evaluation(duration=get_in(self.cfg, "analytics.evaluation_duration", "5Y")),
        }
        for name, fn in calls.items():
            df, _ = safe_call(f"Analytics.valuation({index_symbol}).{name}", fn, fail_fast=False)
            data[name] = df
        return data


# ---------------------------------------------------------------------------
# Analysis engines
# ---------------------------------------------------------------------------


class TechnicalAnalyzer:
    def __init__(self, cfg: Mapping[str, Any]):
        self.cfg = cfg

    def analyze(self, market_data: Mapping[str, pd.DataFrame], index_market: Optional[Mapping[str, pd.DataFrame]] = None) -> Dict[str, Any]:
        ohlcv = market_data.get("ohlcv")
        if ohlcv is None or ohlcv.empty:
            ohlcv = market_data.get("history", pd.DataFrame())
        df = self._normalize_ohlcv(ohlcv)
        if df.empty or len(df) < 30:
            return {"valid": False, "reason": "not enough OHLCV rows"}

        price_mult = float(get_in(self.cfg, "market.ohlcv_price_multiplier", 1000.0))
        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df[col] = df[col].map(lambda x: normalize_price_to_vnd(x, price_mult))
        df["volume"] = pd.to_numeric(df.get("volume", np.nan), errors="coerce")
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        ma_short = int(get_in(self.cfg, "technical_strategy.ma_short", 20))
        ma_mid = int(get_in(self.cfg, "technical_strategy.ma_mid", 50))
        ma_long = int(get_in(self.cfg, "technical_strategy.ma_long", 200))
        rsi_period = int(get_in(self.cfg, "technical_strategy.rsi_period", 14))
        atr_period = int(get_in(self.cfg, "technical_strategy.atr_period", 14))
        vol_window = int(get_in(self.cfg, "technical_strategy.volume_window", 20))

        df["ma20"] = close.rolling(ma_short, min_periods=max(5, ma_short // 2)).mean()
        df["ma50"] = close.rolling(ma_mid, min_periods=max(10, ma_mid // 2)).mean()
        df["ma200"] = close.rolling(ma_long, min_periods=max(30, ma_long // 2)).mean()
        df["rsi14"] = self._rsi(close, rsi_period)
        macd, signal, hist = self._macd(close)
        df["macd"] = macd
        df["macd_signal"] = signal
        df["macd_hist"] = hist
        df["atr14"] = self._atr(high, low, close, atr_period)
        df["vol_avg20"] = volume.rolling(vol_window, min_periods=max(5, vol_window // 2)).mean()
        df["volume_ratio20"] = volume / df["vol_avg20"].replace(0, np.nan)
        df["return_20d"] = close.pct_change(20)
        df["return_60d"] = close.pct_change(60)

        for window in get_in(self.cfg, "technical_strategy.breakout_windows", [20, 55]):
            w = int(window)
            df[f"high_{w}d_prev"] = high.shift(1).rolling(w, min_periods=max(5, w // 2)).max()
            df[f"breakout_{w}d"] = close > df[f"high_{w}d_prev"]

        idx_return_60d = np.nan
        if index_market and isinstance(index_market.get("ohlcv"), pd.DataFrame) and not index_market["ohlcv"].empty:
            idx_df = self._normalize_ohlcv(index_market["ohlcv"])
            if not idx_df.empty and "close" in idx_df:
                idx_close = pd.to_numeric(idx_df["close"], errors="coerce")
                idx_return_60d = float(idx_close.pct_change(60).iloc[-1]) if len(idx_close) > 60 else np.nan
        latest = latest_row(df, ["time"])
        current = float(latest.get("close", np.nan))
        trend_score = self._trend_score(latest, idx_return_60d)
        setup = self._detect_setup(latest)
        swing_low_window = int(get_in(self.cfg, "risk.swing_low_window", 20))
        recent_swing_low = float(low.tail(swing_low_window).min()) if len(low) else np.nan
        return {
            "valid": True,
            "current_price": current,
            "last_date": str(latest.get("time", "")),
            "ma20": as_numeric(latest.get("ma20")),
            "ma50": as_numeric(latest.get("ma50")),
            "ma200": as_numeric(latest.get("ma200")),
            "rsi14": as_numeric(latest.get("rsi14")),
            "macd": as_numeric(latest.get("macd")),
            "macd_signal": as_numeric(latest.get("macd_signal")),
            "macd_hist": as_numeric(latest.get("macd_hist")),
            "atr14": as_numeric(latest.get("atr14")),
            "volume": as_numeric(latest.get("volume")),
            "vol_avg20": as_numeric(latest.get("vol_avg20")),
            "volume_ratio20": as_numeric(latest.get("volume_ratio20")),
            "return_20d": as_numeric(latest.get("return_20d")),
            "return_60d": as_numeric(latest.get("return_60d")),
            "index_return_60d": idx_return_60d,
            "relative_strength_60d": as_numeric(latest.get("return_60d")) - idx_return_60d if np.isfinite(idx_return_60d) else np.nan,
            "breakout_20d": bool(latest.get("breakout_20d", False)),
            "breakout_55d": bool(latest.get("breakout_55d", False)),
            "recent_swing_low": recent_swing_low,
            "trend_score": trend_score,
            "setup_type": setup,
        }

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        work = df.copy()
        rename: Dict[str, str] = {}
        for target, candidates in {
            "time": ["time", "date", "trading_date"],
            "open": ["open", "open_price", "open_price_adjusted"],
            "high": ["high", "high_price", "highest_price_adjusted"],
            "low": ["low", "low_price", "lowest_price_adjusted"],
            "close": ["close", "close_price", "close_price_adjusted", "match_price"],
            "volume": ["volume", "matched_volume", "total_volume"],
        }.items():
            c = first_col(work, candidates, contains=False)
            if c and c != target:
                rename[c] = target
        work = work.rename(columns=rename)
        needed = {"open", "high", "low", "close"}
        if not needed.issubset(set(work.columns)):
            return pd.DataFrame()
        if "time" in work.columns:
            work["time"] = parse_datetime_series(work["time"])
            work = work.sort_values("time")
        return work.reset_index(drop=True)

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _macd(close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd, signal, macd - signal

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False).mean()

    def _trend_score(self, latest: pd.Series, idx_return_60d: float) -> float:
        score = 50.0
        close = as_numeric(latest.get("close"))
        ma20 = as_numeric(latest.get("ma20"))
        ma50 = as_numeric(latest.get("ma50"))
        ma200 = as_numeric(latest.get("ma200"))
        rsi = as_numeric(latest.get("rsi14"))
        hist = as_numeric(latest.get("macd_hist"))
        vr = as_numeric(latest.get("volume_ratio20"))
        r20 = as_numeric(latest.get("return_20d"))
        r60 = as_numeric(latest.get("return_60d"))
        if np.isfinite(close) and np.isfinite(ma20) and close > ma20:
            score += 8
        if np.isfinite(ma20) and np.isfinite(ma50) and ma20 > ma50:
            score += 8
        if np.isfinite(ma50) and np.isfinite(ma200) and ma50 > ma200:
            score += 8
        if np.isfinite(rsi) and 50 <= rsi <= 70:
            score += 8
        elif np.isfinite(rsi) and rsi > 80:
            score -= 8
        if np.isfinite(hist) and hist > 0:
            score += 5
        if np.isfinite(vr) and vr >= float(get_in(self.cfg, "technical_strategy.min_volume_ratio_breakout", 1.5)):
            score += 7
        if np.isfinite(r20) and r20 > 0:
            score += 5
        if np.isfinite(r60) and np.isfinite(idx_return_60d) and r60 > idx_return_60d:
            score += 8
        if bool(latest.get("breakout_20d", False)):
            score += 5
        if bool(latest.get("breakout_55d", False)):
            score += 7
        return float(np.clip(score, 0, 100))

    def _detect_setup(self, latest: pd.Series) -> str:
        rsi = as_numeric(latest.get("rsi14"))
        close = as_numeric(latest.get("close"))
        ma20 = as_numeric(latest.get("ma20"))
        ma50 = as_numeric(latest.get("ma50"))
        ma200 = as_numeric(latest.get("ma200"))
        vr = as_numeric(latest.get("volume_ratio20"))
        max_rsi = float(get_in(self.cfg, "technical_strategy.max_rsi_for_new_entry", 78))
        min_vr = float(get_in(self.cfg, "technical_strategy.min_volume_ratio_breakout", 1.5))
        if latest.get("breakout_55d", False) and np.isfinite(vr) and vr >= min_vr and (not np.isfinite(rsi) or rsi <= max_rsi):
            return "BREAKOUT_55D"
        if latest.get("breakout_20d", False) and np.isfinite(vr) and vr >= min_vr and (not np.isfinite(rsi) or rsi <= max_rsi):
            return "BREAKOUT_20D"
        if np.isfinite(close) and np.isfinite(ma20) and np.isfinite(ma50) and close >= ma50 and abs(close / ma20 - 1) <= 0.04:
            return "PULLBACK_TO_MA20"
        if np.isfinite(ma20) and np.isfinite(ma50) and np.isfinite(ma200) and ma20 > ma50 > ma200:
            return "UPTREND_CONTINUATION"
        return "NO_CLEAR_SETUP"


class FlowAnalyzer:
    def analyze(self, market_data: Mapping[str, pd.DataFrame]) -> Dict[str, Any]:
        foreign = self._net_flow(market_data.get("foreign_flow"))
        prop = self._net_flow(market_data.get("proprietary_flow"))
        ob = self._orderbook_imbalance(market_data.get("order_book"))
        th = self._trade_imbalance(market_data.get("trade_history"))
        score = 50.0
        if foreign.get("net_val_5d", 0) > 0:
            score += 10
        elif foreign.get("net_val_5d", 0) < 0:
            score -= 8
        if prop.get("net_val_5d", 0) > 0:
            score += 8
        elif prop.get("net_val_5d", 0) < 0:
            score -= 6
        if ob.get("imbalance", 0) > 0.15:
            score += 6
        elif ob.get("imbalance", 0) < -0.15:
            score -= 6
        if th.get("buy_sell_imbalance", 0) > 0.05:
            score += 6
        elif th.get("buy_sell_imbalance", 0) < -0.05:
            score -= 6
        return {"score": float(np.clip(score, 0, 100)), "foreign": foreign, "proprietary": prop, "order_book": ob, "trade_history": th}

    @staticmethod
    def _net_flow(df: Optional[pd.DataFrame]) -> Dict[str, float]:
        if df is None or df.empty:
            return {"net_val_5d": 0.0, "net_val_20d": 0.0, "net_vol_5d": 0.0, "net_vol_20d": 0.0}
        work = df.copy()
        tcol = first_col(work, ["time", "date", "trading_date"], contains=False)
        if tcol:
            work[tcol] = parse_datetime_series(work[tcol])
            work = work.sort_values(tcol)
        net_val_col = first_col(work, ["net_val", "net_value", "fr_net_value_total", "fr_net_value_matched"], contains=True)
        net_vol_col = first_col(work, ["net_vol", "net_volume", "fr_net_volume_total", "fr_net_volume_matched"], contains=True)
        net_val = pd.to_numeric(work[net_val_col], errors="coerce") if net_val_col else pd.Series(dtype="float")
        net_vol = pd.to_numeric(work[net_vol_col], errors="coerce") if net_vol_col else pd.Series(dtype="float")
        return {
            "net_val_5d": float(net_val.tail(5).sum()) if len(net_val) else 0.0,
            "net_val_20d": float(net_val.tail(20).sum()) if len(net_val) else 0.0,
            "net_vol_5d": float(net_vol.tail(5).sum()) if len(net_vol) else 0.0,
            "net_vol_20d": float(net_vol.tail(20).sum()) if len(net_vol) else 0.0,
        }

    @staticmethod
    def _orderbook_imbalance(df: Optional[pd.DataFrame]) -> Dict[str, float]:
        if df is None or df.empty:
            return {"imbalance": 0.0, "bid_vol": 0.0, "ask_vol": 0.0}
        row = latest_row(df)
        bid = 0.0
        ask = 0.0
        for i in range(1, 11):
            bid += as_numeric(row.get(f"bid_vol_{i}"), 0.0)
            ask += as_numeric(row.get(f"ask_vol_{i}"), 0.0)
        denom = bid + ask
        return {"imbalance": float((bid - ask) / denom) if denom > 0 else 0.0, "bid_vol": bid, "ask_vol": ask}

    @staticmethod
    def _trade_imbalance(df: Optional[pd.DataFrame]) -> Dict[str, float]:
        if df is None or df.empty:
            return {"buy_sell_imbalance": 0.0}
        row = latest_row(df)
        buy = as_numeric(row.get("total_buy_trade_volume"), 0.0)
        sell = as_numeric(row.get("total_sell_trade_volume"), 0.0)
        denom = buy + sell
        return {"buy_sell_imbalance": float((buy - sell) / denom) if denom > 0 else 0.0}


class FundamentalAnalyzer:
    def analyze(self, fundamental_data: Mapping[str, pd.DataFrame], sector: str) -> Dict[str, Any]:
        summary = latest_row(fundamental_data.get("summary", pd.DataFrame()))
        ratio = latest_row(fundamental_data.get("ratio", pd.DataFrame()))
        income = latest_row(fundamental_data.get("income_statement", pd.DataFrame()))
        balance = latest_row(fundamental_data.get("balance_sheet", pd.DataFrame()))
        cash = latest_row(fundamental_data.get("cash_flow", pd.DataFrame()))
        health = latest_row(fundamental_data.get("financial_health", pd.DataFrame()))
        note_df = fundamental_data.get("note", pd.DataFrame())

        metrics = {
            "pe": self._pick_numeric(summary, ratio, ["pe", "ttmPe", "p/e"]),
            "pb": self._pick_numeric(summary, ratio, ["pb", "ttmPb", "p/b"]),
            "eps": self._pick_numeric(summary, ratio, ["eps"]),
            "bvps": self._pick_numeric(summary, ratio, ["bvps", "book_value_per_share"]),
            "roe": self._pick_numeric(summary, ratio, ["roe", "ttmRoe"]),
            "roa": self._pick_numeric(summary, ratio, ["roa"]),
            "market_cap": self._pick_numeric(summary, balance, ["market_cap", "marketCap"]),
            "debt_to_equity": self._pick_numeric(ratio, balance, ["debt_to_equity", "debtEquity", "debt/equity"]),
            "revenue": self._pick_numeric(income, ratio, ["revenue", "net_revenue", "sale", "sales"]),
            "npat": self._pick_numeric(income, ratio, ["net_profit_after_tax", "npat", "profit_after_tax", "net_profit"]),
            "cfo": self._pick_numeric(cash, ratio, ["net_cash_flow_from_operating_activities", "cfo", "operating_cash_flow"]),
            "total_assets": self._pick_numeric(balance, ratio, ["total_assets", "asset"]),
        }
        quality_score = self._quality_score(metrics, sector)
        valuation_score = self._valuation_score(metrics, sector)
        note_signal = self._hardcoded_note_signal(note_df)
        return {**metrics, "quality_score": quality_score, "valuation_score": valuation_score, **note_signal, "health_snapshot": health.to_dict() if not health.empty else {}}

    @staticmethod
    def _pick_numeric(primary: pd.Series, secondary: pd.Series, names: Sequence[str]) -> float:
        for row in (primary, secondary):
            if row is None or row.empty:
                continue
            for n in names:
                for idx, val in row.items():
                    if str(n).lower() == str(idx).lower() or str(n).lower() in str(idx).lower():
                        x = as_numeric(val)
                        if np.isfinite(x):
                            return x
        return np.nan

    @staticmethod
    def _quality_score(m: Mapping[str, float], sector: str) -> float:
        score = 50.0
        roe = m.get("roe", np.nan)
        roa = m.get("roa", np.nan)
        cfo = m.get("cfo", np.nan)
        npat = m.get("npat", np.nan)
        dte = m.get("debt_to_equity", np.nan)
        if np.isfinite(roe):
            score += np.clip((roe - 10) * 1.5, -20, 25)
        if np.isfinite(roa) and str(sector).lower() != "bank":
            score += np.clip((roa - 5) * 1.2, -10, 15)
        if np.isfinite(cfo) and np.isfinite(npat) and abs(npat) > 0:
            score += np.clip((cfo / abs(npat) - 0.5) * 20, -15, 20)
        if np.isfinite(dte) and str(sector).lower() != "bank":
            score -= np.clip((dte - 1.5) * 10, 0, 20)
        return float(np.clip(score, 0, 100))

    @staticmethod
    def _valuation_score(m: Mapping[str, float], sector: str) -> float:
        score = 50.0
        pe = m.get("pe", np.nan)
        pb = m.get("pb", np.nan)
        roe = m.get("roe", np.nan)
        if str(sector).lower() == "bank":
            if np.isfinite(pb):
                score += np.clip((1.8 - pb) * 20, -20, 25)
            if np.isfinite(roe):
                score += np.clip((roe - 12) * 1.0, -10, 15)
        else:
            if np.isfinite(pe):
                score += np.clip((25 - pe) * 1.2, -25, 25)
            if np.isfinite(roe):
                score += np.clip((roe - 15) * 0.8, -10, 15)
        return float(np.clip(score, 0, 100))

    @staticmethod
    def _hardcoded_note_signal(note_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
        if note_df is None or note_df.empty:
            return {"note_risk_score": 5.0, "note_growth_score": 5.0, "note_markdown": "Không có dữ liệu thuyết minh để chấm điểm."}
        text = " ".join(str(x) for x in note_df.astype(str).values.ravel())[:20000].lower()
        risk_words = ["nợ quá hạn", "dự phòng", "kiện tụng", "bảo lãnh", "trái phiếu", "chậm trả", "phải thu khó đòi", "ngoại trừ"]
        growth_words = ["mở rộng", "đầu tư", "dự án", "hợp đồng", "tăng trưởng", "năng lực", "chuyển đổi số", "ai", "cloud"]
        risk_hits = [w for w in risk_words if w in text]
        growth_hits = [w for w in growth_words if w in text]
        risk_score = float(np.clip(5 + len(risk_hits), 1, 10))
        growth_score = float(np.clip(5 + len(growth_hits) - max(0, len(risk_hits) - 2) * 0.5, 1, 10))
        md = ["### Note analysis", f"- Hard-coded risk score: {risk_score}/10", f"- Hard-coded growth score: {growth_score}/10"]
        if risk_hits:
            md.append(f"- Risk keywords: {', '.join(risk_hits)}")
        if growth_hits:
            md.append(f"- Growth keywords: {', '.join(growth_hits)}")
        return {"note_risk_score": risk_score, "note_growth_score": growth_score, "note_markdown": "\n".join(md)}


class InsightSummarizer:
    def summarize(self, symbol_insights: Mapping[str, pd.DataFrame], global_insights: Mapping[str, pd.DataFrame], symbol: str) -> Dict[str, Any]:
        mentions: List[str] = []
        for name, df in symbol_insights.items():
            if not df.empty:
                mentions.append(name)
        heatmap_row = symbol_insights.get("sentiment_heatmap", pd.DataFrame())
        contribution_row = symbol_insights.get("sentiment_contribution", pd.DataFrame())
        ranking_flags = [n for n in symbol_insights if n.startswith("ranking_")]
        score = 50.0 + min(20, len(ranking_flags) * 5)
        if not heatmap_row.empty:
            score += 5
        if not contribution_row.empty:
            score += 5
        return {
            "insight_score": float(np.clip(score, 0, 100)),
            "symbol_tables": mentions,
            "ranking_flags": ranking_flags,
            "markdown": self._markdown(symbol, mentions, ranking_flags),
        }

    @staticmethod
    def _markdown(symbol: str, tables: Sequence[str], flags: Sequence[str]) -> str:
        lines = ["## Insights", f"- Symbol: {symbol}"]
        lines.append(f"- Tables containing symbol: {', '.join(tables) if tables else 'None'}")
        lines.append(f"- Ranking flags: {', '.join(flags) if flags else 'None'}")
        return "\n".join(lines)


class ScoreEngine:
    def score(self, technical: Mapping[str, Any], flow: Mapping[str, Any], fundamental: Mapping[str, Any], insights: Mapping[str, Any], news_score: float = 50.0) -> Dict[str, float]:
        technical_score = float(technical.get("trend_score", 50.0)) if technical.get("valid") else 40.0
        flow_score = float(flow.get("score", 50.0))
        fundamental_quality = float(fundamental.get("quality_score", 50.0))
        valuation = float(fundamental.get("valuation_score", 50.0))
        insight_score = float(insights.get("insight_score", 50.0))
        note_risk = float(fundamental.get("note_risk_score", 5.0))
        risk_penalty = max(0.0, (note_risk - 5.0) * 4.0)
        score_3m = 0.30 * technical_score + 0.20 * flow_score + 0.20 * fundamental_quality + 0.10 * valuation + 0.10 * insight_score + 0.10 * news_score - risk_penalty
        score_1y = 0.20 * technical_score + 0.10 * flow_score + 0.30 * fundamental_quality + 0.20 * valuation + 0.10 * insight_score + 0.10 * news_score - risk_penalty
        composite = 0.60 * score_3m + 0.40 * score_1y
        return {
            "technical_score": float(np.clip(technical_score, 0, 100)),
            "flow_score": float(np.clip(flow_score, 0, 100)),
            "fundamental_quality_score": float(np.clip(fundamental_quality, 0, 100)),
            "valuation_score": float(np.clip(valuation, 0, 100)),
            "insight_score": float(np.clip(insight_score, 0, 100)),
            "news_score": float(np.clip(news_score, 0, 100)),
            "risk_penalty": float(risk_penalty),
            "score_3m": float(np.clip(score_3m, 0, 100)),
            "score_1y": float(np.clip(score_1y, 0, 100)),
            "composite": float(np.clip(composite, 0, 100)),
        }


class ScenarioEngine:
    def __init__(self, cfg: Mapping[str, Any]):
        self.cfg = cfg

    def build(self, symbol: str, sector: str, technical: Mapping[str, Any], fundamental: Mapping[str, Any], scores: Mapping[str, float], option_markdown: str = "") -> Dict[str, Any]:
        current = float(technical.get("current_price", np.nan))
        if not np.isfinite(current) or current <= 0:
            return {"valid": False, "reason": "missing current price"}
        atr = float(technical.get("atr14", np.nan))
        if not np.isfinite(atr) or atr <= 0:
            atr = current * 0.04
        valuation_target = self._valuation_target(current, sector, fundamental)
        technical_target = current + 3.0 * atr
        base_target = valuation_target if np.isfinite(valuation_target) else technical_target
        score = float(scores.get("composite", 50.0))
        bull_target = max(base_target * (1.06 + max(0.0, score - 70.0) / 500.0), current + 4.5 * atr)
        bear_target = min(current - 2.0 * atr, base_target * 0.85)
        stop = self._stop_loss(current, atr, technical)
        entry_low = current * (1.0 - float(get_in(self.cfg, "risk.entry_buffer_pct", 0.01)))
        entry_high = current * (1.0 + float(get_in(self.cfg, "risk.entry_buffer_pct", 0.01)))
        prob = self._probabilities(scores, technical, fundamental, option_markdown)
        expected_target = prob["bear"] * bear_target + prob["base"] * base_target + prob["bull"] * bull_target
        expected_return = expected_target / current - 1.0
        rr = (base_target - current) / max(current - stop, 1e-9)
        quantity, pos_val = self._position_size(current, stop)
        return {
            "valid": True,
            "current_price": current,
            "entry_zone_low": entry_low,
            "entry_zone_high": entry_high,
            "stop_loss": stop,
            "bear_target": bear_target,
            "base_target": base_target,
            "bull_target": bull_target,
            "prob_bear": prob["bear"],
            "prob_base": prob["base"],
            "prob_bull": prob["bull"],
            "expected_target": expected_target,
            "expected_return": expected_return,
            "risk_reward": rr,
            "suggested_quantity": int(quantity),
            "suggested_position_value": pos_val,
        }

    def _valuation_target(self, current: float, sector: str, f: Mapping[str, Any]) -> float:
        sector_l = str(sector).lower()
        pe = float(f.get("pe", np.nan))
        pb = float(f.get("pb", np.nan))
        eps = float(f.get("eps", np.nan))
        bvps = float(f.get("bvps", np.nan))
        roe = float(f.get("roe", np.nan))
        if sector_l == "bank" and np.isfinite(bvps):
            justified_pb = 1.0
            if np.isfinite(roe):
                justified_pb = np.clip(roe / 12.0, get_in(self.cfg, "ms_style_scenario.bank_target_pb_floor", 0.8), get_in(self.cfg, "ms_style_scenario.bank_target_pb_cap", 2.4))
            elif np.isfinite(pb):
                justified_pb = np.clip(pb * 1.10, 0.8, 2.4)
            return float(bvps * justified_pb)
        if np.isfinite(eps) and eps > 0:
            target_pe = np.nan
            if np.isfinite(pe):
                target_pe = pe * 1.15
            if not np.isfinite(target_pe):
                target_pe = 18.0 if sector_l == "technology" else 12.0
            if sector_l == "technology":
                target_pe = float(np.clip(target_pe, get_in(self.cfg, "ms_style_scenario.tech_target_pe_floor", 10.0), get_in(self.cfg, "ms_style_scenario.tech_target_pe_cap", 35.0)))
            return float(eps * target_pe)
        return np.nan

    def _stop_loss(self, current: float, atr: float, technical: Mapping[str, Any]) -> float:
        atr_stop = current - float(get_in(self.cfg, "risk.atr_stop_multiplier", 1.8)) * atr
        swing = float(technical.get("recent_swing_low", np.nan))
        ma20 = float(technical.get("ma20", np.nan))
        candidates = [atr_stop]
        if np.isfinite(swing) and swing > 0:
            candidates.append(swing * 0.985)
        if np.isfinite(ma20) and ma20 > 0:
            candidates.append(ma20 * 0.97)
        stop = max([c for c in candidates if np.isfinite(c) and c > 0])
        return min(stop, current * 0.98)

    @staticmethod
    def _probabilities(scores: Mapping[str, float], technical: Mapping[str, Any], fundamental: Mapping[str, Any], option_markdown: str) -> Dict[str, float]:
        comp = float(scores.get("composite", 50.0))
        tech = float(scores.get("technical_score", 50.0))
        flow = float(scores.get("flow_score", 50.0))
        q = float(scores.get("fundamental_quality_score", 50.0))
        risk = float(scores.get("risk_penalty", 0.0))
        bull_raw = 1 / (1 + math.exp(-((comp - 60) / 14 + (tech - 50) / 35 + (flow - 50) / 45 + (q - 50) / 50 - risk / 30)))
        bear_raw = 1 / (1 + math.exp(-((55 - comp) / 14 + risk / 20)))
        if option_markdown and re.search(r"bull|upside|tăng|mua", option_markdown, flags=re.I):
            bull_raw += 0.05
        if option_markdown and re.search(r"bear|downside|giảm|bán|risk", option_markdown, flags=re.I):
            bear_raw += 0.05
        bull = float(np.clip(0.15 + 0.35 * bull_raw, 0.05, 0.55))
        bear = float(np.clip(0.10 + 0.30 * bear_raw, 0.05, 0.50))
        base = max(0.05, 1.0 - bull - bear)
        total = bull + bear + base
        return {"bull": bull / total, "base": base / total, "bear": bear / total}

    def _position_size(self, entry: float, stop: float) -> Tuple[int, float]:
        portfolio = float(get_in(self.cfg, "risk.portfolio_value_vnd", 0))
        risk_pct = float(get_in(self.cfg, "risk.risk_per_trade_pct", 0.0075))
        max_position_pct = float(get_in(self.cfg, "risk.max_position_pct", 0.15))
        risk_amount = portfolio * risk_pct
        risk_per_share = max(entry - stop, 1e-9)
        qty_by_risk = math.floor(risk_amount / risk_per_share)
        qty_by_max_pos = math.floor(portfolio * max_position_pct / max(entry, 1e-9))
        qty = max(0, min(qty_by_risk, qty_by_max_pos))
        return qty, float(qty * entry)


class MarkdownPackBuilder:
    def build_symbol_pack(self, analysis: SymbolAnalysis, universe_row: Optional[Mapping[str, Any]] = None) -> str:
        t = analysis.technical or {}
        f = analysis.fundamental_summary or {}
        fl = analysis.flow or {}
        sc = analysis.scenario or {}
        scores = analysis.scores or {}
        d = analysis.decision or {}
        lines = [
            f"# Research Pack - {analysis.symbol} ({analysis.sector})",
            "",
            "## Executive snapshot",
            f"- Action: {d.get('action', 'PENDING')}",
            f"- Composite score: {scores.get('composite', np.nan):.2f}",
            f"- Score 3M: {scores.get('score_3m', np.nan):.2f}",
            f"- Score 1Y: {scores.get('score_1y', np.nan):.2f}",
            f"- Current price: {sc.get('current_price', t.get('current_price', np.nan))}",
            "",
            "## Technical analysis",
            f"- Setup: {t.get('setup_type')}",
            f"- Trend score: {t.get('trend_score')}",
            f"- RSI14: {t.get('rsi14')}",
            f"- MACD histogram: {t.get('macd_hist')}",
            f"- Return 20D / 60D: {t.get('return_20d')} / {t.get('return_60d')}",
            f"- Relative strength 60D vs index: {t.get('relative_strength_60d')}",
            f"- Volume ratio 20D: {t.get('volume_ratio20')}",
            "",
            "## Flow analysis",
            f"- Flow score: {fl.get('score')}",
            f"- Foreign net value 5D/20D: {get_in(fl, 'foreign.net_val_5d')} / {get_in(fl, 'foreign.net_val_20d')}",
            f"- Proprietary net value 5D/20D: {get_in(fl, 'proprietary.net_val_5d')} / {get_in(fl, 'proprietary.net_val_20d')}",
            f"- Order-book imbalance: {get_in(fl, 'order_book.imbalance')}",
            "",
            "## Fundamental analysis",
            f"- P/E: {f.get('pe')}",
            f"- P/B: {f.get('pb')}",
            f"- EPS: {f.get('eps')}",
            f"- BVPS: {f.get('bvps')}",
            f"- ROE: {f.get('roe')}",
            f"- Quality score: {f.get('quality_score')}",
            f"- Valuation score: {f.get('valuation_score')}",
            "",
            f.get("note_markdown", ""),
            "",
            "## Insights",
            analysis.insight_summary.get("markdown", "No insight summary."),
            "",
            "## Morgan-Stanley-style risk/reward",
            f"- Entry zone: {sc.get('entry_zone_low')} - {sc.get('entry_zone_high')}",
            f"- Stop loss: {sc.get('stop_loss')}",
            f"- Bear/Base/Bull target: {sc.get('bear_target')} / {sc.get('base_target')} / {sc.get('bull_target')}",
            f"- P_bear/P_base/P_bull: {sc.get('prob_bear')} / {sc.get('prob_base')} / {sc.get('prob_bull')}",
            f"- Expected return: {sc.get('expected_return')}",
            f"- Risk/reward: {sc.get('risk_reward')}",
            f"- Suggested quantity: {sc.get('suggested_quantity')}",
            "",
            "## User-fed option / derivatives / positioning insights",
            analysis.option_markdown or "No user-fed option insights.",
            "",
            "## Latest related news",
            self._news_markdown(analysis.news_data),
            "",
            "## Agent decision",
            "```json",
            json.dumps(d, ensure_ascii=False, indent=2, default=str),
            "```",
        ]
        if analysis.errors:
            lines.extend(["", "## Data collection warnings", "```json", json.dumps(analysis.errors, ensure_ascii=False, indent=2), "```"])
        return "\n".join(lines)

    @staticmethod
    def _news_markdown(df: pd.DataFrame, max_rows: int = 10) -> str:
        if df is None or df.empty:
            return "No related news loaded."
        lines: List[str] = []
        for _, row in df.head(max_rows).iterrows():
            title = str(row.get("title", ""))[:180]
            source = str(row.get("source", ""))
            publish = str(row.get("publish_time", row.get("crawl_time_utc", "")))
            url = str(row.get("url", ""))
            lines.append(f"- [{source}] {publish}: {title} ({url})")
        return "\n".join(lines)


class AgentTradeAnalyzer:
    def __init__(self, cfg: Mapping[str, Any]):
        self.cfg = cfg

    def analyze(self, analysis: SymbolAnalysis, rag_context: str = "", mode: str = "initial") -> Dict[str, Any]:
        """Backward-compatible single decision. Uses config agent.mode/provider."""
        bundle = self.analyze_with_comparison(analysis, rag_context=rag_context, mode=mode)
        return bundle["final"]

    def analyze_with_comparison(self, analysis: SymbolAnalysis, rag_context: str = "", mode: str = "initial") -> Dict[str, Dict[str, Any]]:
        """
        Produce both heuristic and LLM decisions when configured.

        agent.mode:
            - heuristic: only deterministic rule-based decision is used
            - llm: call LLM and use LLM as final; heuristic is still saved as baseline
            - compare: compute both; use decision_source to choose final, default LLM
        """
        prompt = self._build_prompt(analysis, rag_context=rag_context, mode=mode)
        analysis.prompt = prompt

        heuristic = self._heuristic_decision(analysis, mode=mode)
        heuristic["decision_engine"] = "heuristic"

        provider = str(get_in(self.cfg, "agent.provider", "heuristic")).lower()
        agent_mode = str(get_in(self.cfg, "agent.mode", "compare")).lower()
        enabled = bool(get_in(self.cfg, "agent.enabled", True))

        llm: Dict[str, Any] = {}
        if enabled and provider != "heuristic" and agent_mode in {"llm", "compare", "both"}:
            try:
                llm = self._call_provider(prompt, heuristic_defaults=heuristic)
                llm["decision_engine"] = provider
                llm["llm_status"] = "success"
            except Exception as exc:
                logging.warning("LLM agent failed; heuristic baseline is still available: %s", exc)
                llm = dict(heuristic)
                llm["decision_engine"] = provider
                llm["llm_status"] = "failed"
                llm["llm_error"] = str(exc)
                llm["reason"] = f"LLM failed, fallback to heuristic. Original heuristic reason: {heuristic.get('reason', '')}"
                if not bool(get_in(self.cfg, "agent.fallback_to_heuristic_on_error", True)):
                    raise
        else:
            llm = dict(heuristic)
            llm["decision_engine"] = "disabled"
            llm["llm_status"] = "not_called"

        decision_source = str(get_in(self.cfg, "agent.decision_source", "llm")).lower()
        if agent_mode == "heuristic" or not enabled or provider == "heuristic":
            final = dict(heuristic)
            final_source = "heuristic"
        elif decision_source == "heuristic":
            final = dict(heuristic)
            final_source = "heuristic"
        else:
            final = dict(llm)
            final_source = "llm"

        final["decision_source"] = final_source
        final["heuristic_action"] = heuristic.get("action")
        final["llm_action"] = llm.get("action")
        final["decision_agreement"] = bool(str(heuristic.get("action")) == str(llm.get("action")))

        return {"final": final, "heuristic": heuristic, "llm": llm}

    def _build_prompt(self, analysis: SymbolAnalysis, rag_context: str, mode: str) -> str:
        return f"""
You are a senior Vietnam equity trade analyzer. Use the research pack below to produce a strict JSON decision.
Do not guarantee profit. Focus on probability, risk/reward, liquidity, and invalidation rules.
Do not recompute indicators; use the deterministic values already provided by the pipeline.

Mode: {mode}

RAG context / playbook:
{rag_context or '(none)'}

Research pack:
{analysis.research_markdown}

Return JSON with these keys:
action, confidence, horizon, entry_price_low, entry_price_high, stop_loss, base_target, bull_target,
bear_target, suggested_quantity, suggested_position_value, buy_strategy, sell_or_reduce_rules,
reason, key_risks, monitoring_triggers.
""".strip()

    def _call_provider(self, prompt: str, heuristic_defaults: Mapping[str, Any]) -> Dict[str, Any]:
        provider = str(get_in(self.cfg, "agent.provider", "heuristic")).lower()
        if provider in {"project_gemini", "gemini", "gemini_scripts"}:
            return self._call_project_gemini(prompt, heuristic_defaults=heuristic_defaults)
        if provider == "openai_compatible":
            return self._call_openai_compatible(prompt)
        raise PipelineConfigError(f"Unsupported agent provider={provider}")

    def _call_project_gemini(self, prompt: str, heuristic_defaults: Mapping[str, Any]) -> Dict[str, Any]:
        """Call the user's project LLM wrapper in scripts/get_llm_layer.py and get normalized JSON."""
        try:
            from scripts.get_llm_layer import ask_llm
        except Exception:
            from get_llm_layer import ask_llm  # type: ignore

        llm_cfg = get_in(self.cfg, "llm_config", {}) or {}
        if not isinstance(llm_cfg, Mapping) or not llm_cfg:
            llm_cfg = {
                "api_key_env": get_in(self.cfg, "agent.api_key_env", "GEMINI_API_KEY"),
                "api_key": get_in(self.cfg, "agent.api_key"),
                "llm_model": get_in(self.cfg, "agent.model", "gemini-2.5-flash"),
                "temperature": get_in(self.cfg, "agent.temperature", 0.2),
                "max_output_tokens": get_in(self.cfg, "agent.max_output_tokens", 4096),
                "require_json": True,
                "timeout": get_in(self.cfg, "agent.timeout", 60),
            }

        result = ask_llm(
            prompt,
            {"llm_config": dict(llm_cfg)},
            output_schema="trade_decision",
            return_json=True,
            print_response=False,
            schema_defaults=dict(heuristic_defaults),
            raise_on_error=True,
        )
        if not isinstance(result, dict):
            raise PipelineRuntimeError("Project Gemini returned non-dict JSON result")
        return result

    def _call_openai_compatible(self, prompt: str) -> Dict[str, Any]:
        import requests
        endpoint = get_in(self.cfg, "agent.endpoint_url")
        if not endpoint:
            raise PipelineConfigError("agent.endpoint_url is required for openai_compatible provider")
        api_key = get_in(self.cfg, "agent.api_key") or os.getenv(str(get_in(self.cfg, "agent.api_key_env", "TRADING_LLM_API_KEY")))
        if not api_key:
            raise PipelineConfigError("No agent API key found")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": get_in(self.cfg, "agent.model", "trading-analyzer"),
            "temperature": float(get_in(self.cfg, "agent.temperature", 0.2)),
            "max_tokens": int(get_in(self.cfg, "agent.max_output_tokens", 4096)),
            "messages": [
                {"role": "system", "content": "Return only valid JSON matching the requested schema."},
                {"role": "user", "content": prompt},
            ],
        }
        resp = requests.post(str(endpoint), headers=headers, json=payload, timeout=int(get_in(self.cfg, "agent.timeout", 60)))
        resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return self._parse_json_from_text(text)

    @staticmethod
    def _parse_json_from_text(text: str) -> Dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text).strip()
            text = re.sub(r"```$", "", text).strip()
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, flags=re.S)
            if match:
                return json.loads(match.group(0))
            raise

    @staticmethod
    def _heuristic_decision(analysis: SymbolAnalysis, mode: str = "initial") -> Dict[str, Any]:
        scores = analysis.scores or {}
        sc = analysis.scenario or {}
        comp = float(scores.get("composite", 0))
        rr = float(sc.get("risk_reward", 0) or 0)
        er = float(sc.get("expected_return", 0) or 0)
        pbear = float(sc.get("prob_bear", 1) or 1)
        setup = str((analysis.technical or {}).get("setup_type", ""))
        if mode == "daily_news":
            action = "HOLD_MONITOR"
            if analysis.news_data is not None and not analysis.news_data.empty and comp < 55:
                action = "REDUCE_OR_EXIT"
        elif comp >= 78 and rr >= 2.0 and er >= 0.10 and pbear <= 0.40 and setup != "NO_CLEAR_SETUP":
            action = "BUY_CANDIDATE"
        elif comp >= 68:
            action = "WATCHLIST"
        elif comp >= 58:
            action = "HOLD_MONITOR"
        else:
            action = "IGNORE"
        return {
            "action": action,
            "confidence": float(np.clip(comp / 100, 0.1, 0.95)),
            "horizon": "3M" if mode != "daily_news" else "monitoring",
            "entry_price_low": sc.get("entry_zone_low"),
            "entry_price_high": sc.get("entry_zone_high"),
            "stop_loss": sc.get("stop_loss"),
            "base_target": sc.get("base_target"),
            "bull_target": sc.get("bull_target"),
            "bear_target": sc.get("bear_target"),
            "suggested_quantity": sc.get("suggested_quantity"),
            "suggested_position_value": sc.get("suggested_position_value"),
            "buy_strategy": setup if action in {"BUY_CANDIDATE", "WATCHLIST"} else "wait",
            "sell_or_reduce_rules": ["Close below stop_loss", "Composite score drops below 55", "Severe negative news or BCTC red flag"],
            "reason": f"Heuristic decision from composite={comp:.1f}, R/R={rr:.2f}, expected_return={er:.2%}, setup={setup}.",
            "key_risks": ["Market regime reversal", "Liquidity and gap risk", "Fundamental/news risk"],
            "monitoring_triggers": ["Breakout confirmation", "Foreign/proprietary flow reversal", "New BCTC or severe news"],
        }


# ---------------------------------------------------------------------------
# News monitoring
# ---------------------------------------------------------------------------


class NewsMonitor:
    def __init__(self, cfg: Mapping[str, Any]):
        self.cfg = cfg

    def fetch_news(self) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        news_cfg_path = get_in(self.cfg, "paths.news_config_path")
        fn = import_existing_news_layer(self.cfg)
        result = fn(news_cfg_path)
        df = to_frame(result.get("data") if isinstance(result, Mapping) else result)
        if bool(get_in(self.cfg, "runtime.deduplicate_news_by_url", True)) and "url" in df.columns:
            df = df.drop_duplicates(subset=["url"], keep="first")
        return df, dict(result) if isinstance(result, Mapping) else {"data": df}

    def filter_for_symbol(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        sym = clean_symbol(symbol)
        aliases = [sym] + list((get_in(self.cfg, "daily_news.company_aliases", {}) or {}).get(sym, []))
        pattern = re.compile("|".join(re.escape(a) for a in aliases if a), flags=re.I)
        cols = choose_text_columns(df)
        if not cols:
            return pd.DataFrame()
        text = df[cols].astype(str).agg(" ".join, axis=1)
        out = df[text.str.contains(pattern, na=False)].copy()
        if "publish_time" in out.columns:
            out["publish_time"] = parse_datetime_series(out["publish_time"])
            out = out.sort_values("publish_time", ascending=False)
        return out.head(int(get_in(self.cfg, "daily_news.max_articles_per_symbol", 20)))

    def score_news_for_symbol(self, df: pd.DataFrame) -> Dict[str, Any]:
        if df is None or df.empty:
            return {"news_score": 50.0, "severe_count": 0, "positive_count": 0}
        cols = choose_text_columns(df)
        text = " ".join(df[cols].astype(str).agg(" ".join, axis=1).tolist()).lower()
        severe_words = list(get_in(self.cfg, "daily_news.severe_risk_keywords", []))
        positive_words = list(get_in(self.cfg, "daily_news.positive_keywords", []))
        severe_count = sum(1 for w in severe_words if str(w).lower() in text)
        positive_count = sum(1 for w in positive_words if str(w).lower() in text)
        score = 50 + positive_count * 5 - severe_count * 8
        return {"news_score": float(np.clip(score, 0, 100)), "severe_count": severe_count, "positive_count": positive_count}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class FullTradePipeline:
    def __init__(
        self,
        config: Optional[JsonLike] = None,
        *,
        output_dir: Optional[Union[str, Path]] = None,
        results_path: Optional[Union[str, Path]] = None,
        agent_mode: Optional[str] = None,
    ):
        self.cfg = load_config(config)
        if output_dir:
            set_in(self.cfg, "paths.output_dir", str(output_dir))
            set_in(self.cfg, "daily_news.watchlist_path", str(Path(output_dir) / "watchlist_latest.csv"))
        if results_path:
            set_in(self.cfg, "reports.file_path", str(results_path))
            set_in(self.cfg, "reports.enabled", True)
        if agent_mode:
            mode_raw = str(agent_mode).lower()
            mode_map = {"off": "heuristic", "heuristic": "heuristic", "on": "llm", "llm": "llm", "both": "compare", "compare": "compare"}
            mode_norm = mode_map.get(mode_raw, mode_raw)
            set_in(self.cfg, "agent.mode", mode_norm)
            set_in(self.cfg, "agent.llm_mode", mode_norm)
            if mode_norm == "heuristic":
                set_in(self.cfg, "agent.provider", "heuristic")
            elif str(get_in(self.cfg, "agent.provider", "heuristic")).lower() == "heuristic":
                set_in(self.cfg, "agent.provider", "project_gemini")
        setup_logging(self.cfg)
        self.repo_root = add_repo_root_to_path(self.cfg)
        self.paths = self._init_paths()
        self.collector = DataCollector(self.cfg)
        self.insights = InsightsCollector(self.cfg)
        self.technical = TechnicalAnalyzer(self.cfg)
        self.flow = FlowAnalyzer()
        self.fundamental = FundamentalAnalyzer()
        self.insight_summarizer = InsightSummarizer()
        self.score_engine = ScoreEngine()
        self.scenario = ScenarioEngine(self.cfg)
        self.markdown = MarkdownPackBuilder()
        self.agent = AgentTradeAnalyzer(self.cfg)
        self.news = NewsMonitor(self.cfg)
        self.rag_context = self._load_optional_text(get_in(self.cfg, "paths.rag_markdown_path"))
        self.option_feed = self._load_option_feed(get_in(self.cfg, "paths.user_option_insights_path"))

    def _init_paths(self) -> Dict[str, Path]:
        root = ensure_dir(get_in(self.cfg, "paths.output_dir", "./outputs/trade_pipeline_integrate_llm"))
        out = {
            "root": root,
            "markdown": ensure_dir(root / "markdown"),
            "decisions": ensure_dir(root / "decisions"),
            "prompts": ensure_dir(root / "prompts"),
            "raw": ensure_dir(root / "raw"),
            "daily_news": ensure_dir(root / "daily_news"),
            "reports": ensure_dir(get_in(self.cfg, "reports.dir", "./reports")),
        }
        return out

    @staticmethod
    def _load_optional_text(path: Any) -> str:
        if not path:
            return ""
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return ""

    @staticmethod
    def _load_option_feed(path: Any) -> Dict[str, str]:
        if not path:
            return {}
        p = Path(path)
        if not p.exists():
            return {}
        text = p.read_text(encoding="utf-8")
        blocks: Dict[str, str] = {}
        current = "GLOBAL"
        buf: List[str] = []
        for line in text.splitlines():
            m = re.match(r"^##+\s*([A-Z0-9]{2,10})\b", line.strip())
            if m:
                if buf:
                    blocks[current] = "\n".join(buf).strip()
                current = clean_symbol(m.group(1))
                buf = [line]
            else:
                buf.append(line)
        if buf:
            blocks[current] = "\n".join(buf).strip()
        return blocks

    def run_initial(self) -> Dict[str, Any]:
        logging.info("Building bank + technology universe...")
        universe = UniverseBuilder(self.cfg).build()
        universe_path = self.paths["root"] / f"universe_{now_stamp()}.csv"
        universe.to_csv(universe_path, index=False, encoding=get_in(self.cfg, "runtime.csv_encoding", "utf-8-sig"))

        logging.info("Collecting global market/insights/analytics data...")
        index_market = self.collector.collect_index_market()
        analytics_data = self.collector.collect_analytics()
        global_insights, insight_errors = self.insights.collect_global()

        max_symbols = int(get_in(self.cfg, "universe.max_symbols_to_analyze", 30))
        rows: List[Dict[str, Any]] = []
        analyses: List[SymbolAnalysis] = []
        for i, row in universe.head(max_symbols).iterrows():
            symbol = clean_symbol(row.get("symbol"))
            sector = str(row.get("sector", row.get("sector_hint", "unknown"))).lower()
            if not symbol:
                continue
            logging.info("Analyzing %s/%s: %s (%s)", i + 1, min(max_symbols, len(universe)), symbol, sector)
            try:
                analysis = self._analyze_one_symbol(symbol, sector, dict(row), index_market, analytics_data, global_insights, insight_errors)
                analyses.append(analysis)
                rows.append(self._decision_row(analysis))
                self._save_symbol_outputs(analysis)
            except Exception as exc:
                logging.exception("Analysis failed for %s: %s", symbol, exc)
                if bool(get_in(self.cfg, "runtime.fail_fast", False)):
                    raise
            time.sleep(float(get_in(self.cfg, "runtime.sleep_between_symbols", 0.2)))

        ranked = pd.DataFrame(rows)
        if not ranked.empty:
            ranked = ranked.sort_values(["action_rank", "composite"], ascending=[True, False]).reset_index(drop=True)
        ranked_path = self.paths["root"] / "candidates_ranked_latest.csv"
        watchlist_path = self.paths["root"] / "watchlist_latest.csv"
        ranked.to_csv(ranked_path, index=False, encoding=get_in(self.cfg, "runtime.csv_encoding", "utf-8-sig"))
        watchlist = ranked[ranked["action"].isin(["BUY_CANDIDATE", "WATCHLIST", "HOLD_MONITOR"])] if not ranked.empty else ranked
        watchlist.to_csv(watchlist_path, index=False, encoding=get_in(self.cfg, "runtime.csv_encoding", "utf-8-sig"))
        manifest = {
            "generated_at": utc_now_iso(),
            "mode": "initial",
            "universe_path": str(universe_path),
            "ranked_path": str(ranked_path),
            "watchlist_path": str(watchlist_path),
            "symbol_count": len(analyses),
            "markdown_dir": str(self.paths["markdown"]),
            "decision_dir": str(self.paths["decisions"]),
        }
        report_text = ""
        report_path: Optional[Path] = None
        if bool(get_in(self.cfg, "reports.enabled", True)):
            report_text = self._build_initial_report(ranked, watchlist, universe, manifest)
            configured_report = resolve_template_path(get_in(self.cfg, "reports.file_path"), stamp=now_stamp())
            report_path = configured_report if configured_report else self.paths["reports"] / f"reports_{now_stamp()}.txt"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_text, encoding="utf-8")
            manifest["report_path"] = str(report_path)
            if bool(get_in(self.cfg, "reports.print_to_console", True)):
                print("\n" + report_text)

        manifest_path = self.paths["root"] / f"initial_manifest_{now_stamp()}.json"
        write_json(manifest_path, manifest)
        return {
            "universe": universe,
            "ranked": ranked,
            "watchlist": watchlist,
            "manifest": manifest,
            "manifest_path": str(manifest_path),
            "report_text": report_text,
            "report_path": str(report_path) if report_path else None,
        }

    def _analyze_one_symbol(
        self,
        symbol: str,
        sector: str,
        universe_row: Mapping[str, Any],
        index_market: Mapping[str, pd.DataFrame],
        analytics_data: Mapping[str, pd.DataFrame],
        global_insights: Mapping[str, pd.DataFrame],
        insight_errors: Sequence[Mapping[str, str]],
        news_df: Optional[pd.DataFrame] = None,
    ) -> SymbolAnalysis:
        a = SymbolAnalysis(symbol=symbol, sector=sector)
        market_data, errors = self.collector.collect_market_for_symbol(symbol)
        a.market_data = market_data
        a.errors.extend(errors)
        a.errors.extend([dict(e) for e in insight_errors])
        sym_insights = self.insights.subset_for_symbol(global_insights, symbol)
        a.insights_data = sym_insights
        fundamental_data, errors = self.collector.collect_fundamental_for_symbol(symbol)
        if "summary" in market_data and not market_data["summary"].empty:
            fundamental_data = dict(fundamental_data)
            fundamental_data["summary"] = market_data["summary"]
        a.fundamental_data = fundamental_data
        a.errors.extend(errors)
        a.analytics_data = dict(analytics_data)
        a.option_markdown = self.option_feed.get(symbol, self.option_feed.get("GLOBAL", ""))
        if news_df is not None:
            a.news_data = news_df
        a.technical = self.technical.analyze(market_data, index_market=index_market)
        a.flow = self.flow.analyze(market_data)
        a.fundamental_summary = self.fundamental.analyze(fundamental_data, sector=sector)
        a.insight_summary = self.insight_summarizer.summarize(sym_insights, global_insights, symbol)
        news_score = 50.0
        if news_df is not None:
            news_score = float(self.news.score_news_for_symbol(news_df).get("news_score", 50.0))
        a.scores = self.score_engine.score(a.technical, a.flow, a.fundamental_summary, a.insight_summary, news_score=news_score)
        a.scenario = self.scenario.build(symbol, sector, a.technical, a.fundamental_summary, a.scores, a.option_markdown)
        a.research_markdown = self.markdown.build_symbol_pack(a, universe_row)
        decision_bundle = self.agent.analyze_with_comparison(a, rag_context=self.rag_context, mode="initial")
        a.heuristic_decision = decision_bundle.get("heuristic", {})
        a.llm_decision = decision_bundle.get("llm", {})
        a.decision = decision_bundle.get("final", {})
        a.research_markdown = self.markdown.build_symbol_pack(a, universe_row)
        return a

    def run_daily_news(self, watchlist_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        path = Path(watchlist_path or get_in(self.cfg, "daily_news.watchlist_path", ""))
        if not path.exists():
            raise PipelineConfigError(f"Watchlist not found: {path}. Run --mode initial first or pass --watchlist.")
        watch = pd.read_csv(path)
        if watch.empty or "symbol" not in watch.columns:
            raise PipelineRuntimeError("Watchlist is empty or has no symbol column.")
        news_df, news_result = self.news.fetch_news()
        events: List[Dict[str, Any]] = []
        for _, row in watch.iterrows():
            symbol = clean_symbol(row.get("symbol"))
            if not symbol:
                continue
            sector = str(row.get("sector", "unknown")).lower()
            related = self.news.filter_for_symbol(news_df, symbol)
            pseudo = SymbolAnalysis(symbol=symbol, sector=sector, news_data=related)
            # Preserve previous decision metrics from watchlist for context.
            pseudo.scores = {"composite": as_numeric(row.get("composite")), "score_3m": as_numeric(row.get("score_3m")), "score_1y": as_numeric(row.get("score_1y"))}
            pseudo.scenario = {
                "current_price": as_numeric(row.get("current_price")),
                "entry_zone_low": as_numeric(row.get("entry_price_low")),
                "entry_zone_high": as_numeric(row.get("entry_price_high")),
                "stop_loss": as_numeric(row.get("stop_loss")),
                "base_target": as_numeric(row.get("base_target")),
                "bull_target": as_numeric(row.get("bull_target")),
                "bear_target": as_numeric(row.get("bear_target")),
                "risk_reward": as_numeric(row.get("risk_reward")),
                "expected_return": as_numeric(row.get("expected_return")),
            }
            news_signal = self.news.score_news_for_symbol(related)
            pseudo.insight_summary = {"markdown": "Daily news monitoring", "insight_score": 50}
            pseudo.research_markdown = self.markdown.build_symbol_pack(pseudo, dict(row))
            decision_bundle = self.agent.analyze_with_comparison(pseudo, rag_context=self.rag_context, mode="daily_news")
            pseudo.heuristic_decision = decision_bundle.get("heuristic", {})
            pseudo.llm_decision = decision_bundle.get("llm", {})
            pseudo.decision = decision_bundle.get("final", {})
            md = self.markdown.build_symbol_pack(pseudo, dict(row))
            md_path = self.paths["daily_news"] / f"{symbol}_daily_news_{now_stamp()}.md"
            md_path.write_text(md, encoding="utf-8")
            events.append({
                "symbol": symbol,
                "sector": sector,
                "related_articles": len(related),
                "news_signal": news_signal,
                "decision": pseudo.decision,
                "markdown_path": str(md_path),
                "telegram_ready": True,
            })
        events_path = self.paths["daily_news"] / f"daily_news_decisions_{now_stamp()}.json"
        write_json(events_path, {"generated_at": utc_now_iso(), "events": events, "news_files": news_result.get("files", [])})
        return {"events": events, "events_path": str(events_path), "news": news_result}

    def _build_initial_report(
        self,
        ranked: pd.DataFrame,
        watchlist: pd.DataFrame,
        universe: pd.DataFrame,
        manifest: Mapping[str, Any],
    ) -> str:
        top_n = int(get_in(self.cfg, "reports.top_n", 20))
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines: List[str] = [
            "=" * 92,
            "VNSTOCK TRADE PIPELINE - INITIAL RUN REPORT",
            "=" * 92,
            f"Generated at       : {generated_at}",
            f"Universe symbols   : {len(universe)}",
            f"Analyzed symbols   : {len(ranked)}",
            f"Ranked output      : {manifest.get('ranked_path')}",
            f"Watchlist output   : {manifest.get('watchlist_path')}",
            f"Agent mode         : {get_in(self.cfg, 'agent.mode', 'compare')}",
            f"Decision source    : {get_in(self.cfg, 'agent.decision_source', 'llm')}",
            "",
        ]

        if ranked is None or ranked.empty:
            lines.extend([
                "KẾT QUẢ HÀNH ĐỘNG",
                "- Không có symbol nào được phân tích thành công.",
                "- Không có symbol nào đáng để WATCH.",
                "- Không có symbol nào đáng để BUY.",
            ])
            return "\n".join(lines)

        action_counts = ranked.get("action", pd.Series(dtype="object")).value_counts(dropna=False).to_dict()
        lines.append("ACTION SUMMARY")
        for action in ["BUY_CANDIDATE", "WATCHLIST", "HOLD_MONITOR", "REDUCE_OR_EXIT", "IGNORE", "UNKNOWN"]:
            count = int(action_counts.get(action, 0))
            lines.append(f"- {action:16s}: {count}")
        lines.append("")
        if "heuristic_action" in ranked.columns and "llm_action" in ranked.columns:
            agree = ranked["heuristic_action"].astype(str).eq(ranked["llm_action"].astype(str))
            lines.append("LLM VS HEURISTIC COMPARISON")
            lines.append(f"- Agreement count : {int(agree.sum())}/{len(ranked)}")
            lines.append(f"- Agreement rate  : {float(agree.mean() if len(agree) else 0):.2%}")
            lines.append("")

        def table_for(action: str, title: str, empty_message: str, limit: int = top_n) -> None:
            subset = ranked[ranked["action"].astype(str).eq(action)].copy() if "action" in ranked.columns else pd.DataFrame()
            lines.append(title)
            if subset.empty:
                lines.append(f"- {empty_message}")
                lines.append("")
                return
            subset = subset.sort_values("composite", ascending=False, na_position="last").head(limit)
            lines.append("symbol | sector | composite | score_3m | score_1y | entry | stop | base | bull | R/R | qty")
            lines.append("-" * 118)
            for _, r in subset.iterrows():
                lines.append(
                    f"{str(r.get('symbol', '')):6s} | "
                    f"{str(r.get('sector', '')):10s} | "
                    f"{as_numeric(r.get('composite')):8.2f} | "
                    f"{as_numeric(r.get('score_3m')):8.2f} | "
                    f"{as_numeric(r.get('score_1y')):8.2f} | "
                    f"{as_numeric(r.get('entry_price_low')):.0f}-{as_numeric(r.get('entry_price_high')):.0f} | "
                    f"{as_numeric(r.get('stop_loss')):.0f} | "
                    f"{as_numeric(r.get('base_target')):.0f} | "
                    f"{as_numeric(r.get('bull_target')):.0f} | "
                    f"{as_numeric(r.get('risk_reward')):.2f} | "
                    f"{int(as_numeric(r.get('suggested_quantity'), 0))}"
                )
            lines.append("")

        table_for("BUY_CANDIDATE", "BUY CANDIDATES", "Không có symbol nào đáng để BUY.")
        table_for("WATCHLIST", "WATCHLIST", "Không có symbol nào đáng để WATCH.")
        table_for("HOLD_MONITOR", "HOLD / MONITOR", "Không có symbol nào cần HOLD/MONITOR.", limit=min(top_n, 10))

        lines.append(f"TOP {top_n} BY COMPOSITE SCORE")
        top = ranked.sort_values("composite", ascending=False, na_position="last").head(top_n)
        if top.empty:
            lines.append("- Không có dữ liệu xếp hạng.")
        else:
            lines.append("symbol | final_action | h_action | llm_action | sector | composite | expected_return | R/R | reason")
            lines.append("-" * 132)
            for _, r in top.iterrows():
                reason = str(r.get("reason", "")).replace("\n", " ")[:78]
                lines.append(
                    f"{str(r.get('symbol', '')):6s} | "
                    f"{str(r.get('action', '')):12s} | "
                    f"{str(r.get('heuristic_action', '')):8s} | "
                    f"{str(r.get('llm_action', '')):10s} | "
                    f"{str(r.get('sector', '')):10s} | "
                    f"{as_numeric(r.get('composite')):8.2f} | "
                    f"{as_numeric(r.get('expected_return')):14.2%} | "
                    f"{as_numeric(r.get('risk_reward')):5.2f} | "
                    f"{reason}"
                )

        if "errors_count" in ranked.columns:
            total_errors = int(pd.to_numeric(ranked["errors_count"], errors="coerce").fillna(0).sum())
            lines.extend(["", f"Data collection warnings/errors_count total: {total_errors}"])
        lines.extend(["", "Ghi chú: BUY_CANDIDATE/WATCHLIST là output sàng lọc xác suất, không phải khuyến nghị đảm bảo lợi nhuận."])
        return "\n".join(lines)


    def _save_symbol_outputs(self, analysis: SymbolAnalysis) -> None:
        stamp = now_stamp()
        md_path = self.paths["markdown"] / f"{analysis.symbol}_research_{stamp}.md"
        md_path.write_text(analysis.research_markdown, encoding="utf-8")
        decision_path = self.paths["decisions"] / f"{analysis.symbol}_decision_{stamp}.json"
        write_json(decision_path, analysis.decision)
        if bool(get_in(self.cfg, "agent.save_prompt", True)):
            prompt_path = self.paths["prompts"] / f"{analysis.symbol}_prompt_{stamp}.md"
            prompt_path.write_text(analysis.prompt or "", encoding="utf-8")
        if bool(get_in(self.cfg, "runtime.save_raw_data", False)):
            raw = {
                "market_data": {k: v.to_dict(orient="records") for k, v in analysis.market_data.items()},
                "fundamental_data": {k: v.to_dict(orient="records") for k, v in analysis.fundamental_data.items()},
                "insights_data": {k: v.to_dict(orient="records") for k, v in analysis.insights_data.items()},
                "analytics_data": {k: v.to_dict(orient="records") for k, v in analysis.analytics_data.items()},
                "errors": analysis.errors,
            }
            write_json(self.paths["raw"] / f"{analysis.symbol}_raw_{stamp}.json", raw)

    @staticmethod
    def _action_rank(action: str) -> int:
        return {"BUY_CANDIDATE": 0, "WATCHLIST": 1, "HOLD_MONITOR": 2, "REDUCE_OR_EXIT": 3, "IGNORE": 4}.get(str(action), 9)

    def _decision_row(self, a: SymbolAnalysis) -> Dict[str, Any]:
        d = a.decision or {}
        s = a.scenario or {}
        scores = a.scores or {}
        return {
            "symbol": a.symbol,
            "sector": a.sector,
            "action": d.get("action", "UNKNOWN"),
            "action_rank": self._action_rank(d.get("action", "UNKNOWN")),
            "decision_source": d.get("decision_source"),
            "decision_engine": d.get("decision_engine"),
            "heuristic_action": (a.heuristic_decision or {}).get("action"),
            "llm_action": (a.llm_decision or {}).get("action"),
            "llm_status": (a.llm_decision or {}).get("llm_status"),
            "decision_agreement": d.get("decision_agreement"),
            "confidence": d.get("confidence"),
            "score_3m": scores.get("score_3m"),
            "score_1y": scores.get("score_1y"),
            "composite": scores.get("composite"),
            "technical_score": scores.get("technical_score"),
            "flow_score": scores.get("flow_score"),
            "fundamental_quality_score": scores.get("fundamental_quality_score"),
            "valuation_score": scores.get("valuation_score"),
            "insight_score": scores.get("insight_score"),
            "risk_penalty": scores.get("risk_penalty"),
            "current_price": s.get("current_price"),
            "entry_price_low": d.get("entry_price_low", s.get("entry_zone_low")),
            "entry_price_high": d.get("entry_price_high", s.get("entry_zone_high")),
            "stop_loss": d.get("stop_loss", s.get("stop_loss")),
            "base_target": d.get("base_target", s.get("base_target")),
            "bull_target": d.get("bull_target", s.get("bull_target")),
            "bear_target": d.get("bear_target", s.get("bear_target")),
            "expected_return": s.get("expected_return"),
            "risk_reward": s.get("risk_reward"),
            "prob_bear": s.get("prob_bear"),
            "prob_base": s.get("prob_base"),
            "prob_bull": s.get("prob_bull"),
            "suggested_quantity": d.get("suggested_quantity", s.get("suggested_quantity")),
            "suggested_position_value": d.get("suggested_position_value", s.get("suggested_position_value")),
            "buy_strategy": d.get("buy_strategy"),
            "reason": d.get("reason"),
            "heuristic_reason": (a.heuristic_decision or {}).get("reason"),
            "llm_reason": (a.llm_decision or {}).get("reason"),
            "llm_error": (a.llm_decision or {}).get("llm_error"),
            "errors_count": len(a.errors),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Full Vnstock trade pipeline with LLM/heuristic comparison")
    parser.add_argument("--mode", choices=["initial", "daily_news"], default="initial")
    parser.add_argument("--config", default="./configs/trade_pipeline_integrate_llm.json")
    parser.add_argument("--watchlist", default=None)
    parser.add_argument("--outputs", default=None, help="Override paths.output_dir, e.g. ./outputs/trade_pipeline_integrate_llm")
    parser.add_argument("--results", default=None, help="Report file path template, e.g. ./results/reports_trade_pipeline_integrate_llm_{date}.txt")
    parser.add_argument("--agent-mode", "--llm-mode", dest="agent_mode", choices=["heuristic", "llm", "compare", "off", "on", "both"], default=None, help="heuristic/off=no API; llm/on=LLM final; compare/both=save heuristic+LLM comparison")
    parser.add_argument("--write-default-config", default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if args.write_default_config:
        p = write_default_config(args.write_default_config)
        print(f"Wrote default config: {p}")
        return
    pipe = FullTradePipeline(
        args.config,
        output_dir=args.outputs,
        results_path=args.results,
        agent_mode=args.agent_mode,
    )
    if args.mode == "initial":
        result = pipe.run_initial()
        print(json.dumps(result["manifest"], ensure_ascii=False, indent=2, default=str))
        if result.get("report_path"):
            print(f"Report saved: {result['report_path']}")
    else:
        result = pipe.run_daily_news(watchlist_path=args.watchlist)
        print(json.dumps({"events_path": result["events_path"], "events": len(result["events"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
