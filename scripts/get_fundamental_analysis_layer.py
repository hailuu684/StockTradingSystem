#!/usr/bin/env python3
"""
Structured Fundamental / BCTC analysis layer for vnstock_data.

This module intentionally DOES NOT OCR or download financial-statement PDFs for
LLM input. It uses structured Fundamental APIs and converts the latest available
quarter into an analyst-grade Markdown report.

Public API:
    get_fundamental_analysis_layer(symbol, output_root, ...)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

JsonDict = Dict[str, Any]

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

SYSTEM_COLUMNS = {
    "ticker", "symbol", "code", "organ_code", "organCode", "industry", "exchange",
    "source", "url", "doc_url", "docUrl", "doc_title", "doc_name", "file_url",
    "fileUrl", "download_url", "downloadUrl", "href", "link", "attachment",
    "file", "report_url", "reportUrl", "company", "company_name", "organ_name",
}

PERIOD_COLUMNS = {
    "period", "report_period", "reportPeriod", "reportperiod", "fiscal_period",
    "fiscalPeriod", "quarter", "quy", "q", "year", "fiscal_year", "fiscalYear",
    "nam", "report_year", "reportYear", "date", "time", "trading_date",
    "publish_date", "published_at", "published_date", "filing_date", "created_at", "updated_at",
}

METRIC_NAME_CANDIDATES = (
    "item", "metric", "indicator", "criteria", "name", "field", "title", "description",
    "account", "account_name", "accountName", "financial_item", "financialItem",
    "label", "chi_tieu", "chitieu", "thuyet_minh", "note", "category",
)

IMPACT_KEYWORDS: List[Tuple[Sequence[str], str, str]] = [
    (("revenue", "doanh thu", "sales"), "growth", "Doanh thu phản ánh quy mô tiêu thụ; tăng bền vững thường hỗ trợ kỳ vọng lợi nhuận và định giá."),
    (("gross profit", "lợi nhuận gộp", "gross_margin", "gross margin"), "growth", "Biên/lợi nhuận gộp cải thiện cho thấy sức mạnh giá bán hoặc chi phí đầu vào thuận lợi."),
    (("operating profit", "ebit", "lợi nhuận hoạt động"), "growth", "Lợi nhuận hoạt động cải thiện cho thấy chất lượng tăng trưởng từ hoạt động cốt lõi."),
    (("net profit", "npat", "lợi nhuận sau thuế", "lnst", "profit after tax"), "growth", "Lợi nhuận sau thuế tăng là động lực trực tiếp cho EPS, P/E forward và giá trị nội tại."),
    (("eps",), "growth", "EPS tăng làm giảm P/E forward và thường hỗ trợ rerating nếu chất lượng lợi nhuận tốt."),
    (("roe",), "quality", "ROE cao và ổn định phản ánh hiệu quả sử dụng vốn chủ; với ngân hàng còn tác động mạnh tới P/B hợp lý."),
    (("roa",), "quality", "ROA cho biết hiệu quả sinh lời trên tổng tài sản; đặc biệt quan trọng với ngân hàng và doanh nghiệp tài sản lớn."),
    (("cfo", "operating cash", "cash flow from operating", "lưu chuyển tiền thuần từ hoạt động kinh doanh"), "cashflow", "Dòng tiền hoạt động xác nhận chất lượng lợi nhuận; CFO yếu hơn lợi nhuận kéo dài là red flag."),
    (("cash", "tiền và tương đương", "cash and cash equivalents"), "liquidity", "Tiền mặt cao tăng khả năng chịu đựng chu kỳ xấu và giảm rủi ro thanh khoản."),
    (("receivable", "phải thu"), "risk", "Phải thu tăng nhanh hơn doanh thu có thể báo hiệu chất lượng doanh thu thấp hoặc rủi ro thu hồi."),
    (("inventory", "hàng tồn kho"), "risk", "Tồn kho tăng nhanh có thể tạo áp lực giảm giá, trích lập hoặc suy giảm vòng quay vốn."),
    (("debt", "borrow", "loan", "nợ vay", "liabilities", "nợ phải trả"), "risk", "Đòn bẩy/nợ tăng làm tăng rủi ro tài chính và chi phí lãi vay, nhất là khi lãi suất bất lợi."),
    (("equity", "vốn chủ", "book value", "bvps"), "valuation", "Vốn chủ/BVPS là nền tảng định giá P/B, đặc biệt quan trọng với ngân hàng."),
    (("asset", "tài sản"), "scale", "Tổng tài sản cho biết quy mô bảng cân đối; tăng trưởng tài sản cần đi kèm hiệu quả sinh lời và kiểm soát rủi ro."),
    (("npl", "bad debt", "nợ xấu"), "risk", "Nợ xấu tăng làm tăng chi phí dự phòng và giảm chất lượng lợi nhuận ngân hàng."),
    (("provision", "dự phòng"), "risk", "Dự phòng tăng có thể bảo thủ nhưng cũng phản ánh rủi ro tài sản hoặc nợ xấu tăng."),
    (("pe", "p/e"), "valuation", "P/E đo mức giá trả cho lợi nhuận; thấp chỉ hấp dẫn nếu tăng trưởng và chất lượng lợi nhuận không xấu."),
    (("pb", "p/b"), "valuation", "P/B đo giá so với vốn chủ; với ngân hàng cần so cùng ROE, NIM và chất lượng tài sản."),
    (("margin", "biên"), "quality", "Biên lợi nhuận cải thiện cho thấy khả năng giữ giá hoặc tối ưu chi phí."),
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Union[str, Path]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _missing_scalar(value: Any) -> bool:
    """Safe missing check for scalar only; never evaluates Series/DataFrame truthiness."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null", "nat", "-", "<na>"}
    if isinstance(value, (pd.Series, pd.DataFrame, list, tuple, set, dict)):
        return False
    try:
        out = pd.isna(value)
        if isinstance(out, (bool, type(True))):
            return bool(out)
    except Exception:
        pass
    try:
        return isinstance(value, float) and math.isnan(value)
    except Exception:
        return False


def scalarize(value: Any, default: Any = None) -> Any:
    """Reduce pandas/list-like accidental containers to one deterministic scalar.

    This specifically fixes pandas duplicate-column behaviour where row.get(col)
    returns a Series, which later crashes with: `truth value of a Series is ambiguous`.
    """
    if value is None:
        return default
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return default
        vals = value.to_numpy().ravel().tolist()
        for item in vals:
            v = scalarize(item, default=None)
            if not _missing_scalar(v):
                return v
        return default
    if isinstance(value, pd.Series):
        if value.empty:
            return default
        for item in value.tolist():
            v = scalarize(item, default=None)
            if not _missing_scalar(v):
                return v
        return default
    if not isinstance(value, (str, bytes, bytearray)) and hasattr(value, "tolist"):
        try:
            return scalarize(value.tolist(), default=default)
        except Exception:
            pass
    if isinstance(value, (list, tuple, set)):
        for item in list(value):
            v = scalarize(item, default=None)
            if not _missing_scalar(v):
                return v
        return default
    if isinstance(value, Mapping):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
    return value


def safe_get(row: Any, key: Any, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        if isinstance(row, pd.Series):
            if key in row.index:
                return scalarize(row.loc[key], default=default)
            key_s = str(key)
            for idx in row.index:
                if str(idx) == key_s:
                    return scalarize(row.loc[idx], default=default)
            return default
        if isinstance(row, Mapping):
            return scalarize(row.get(key, default), default=default)
        if hasattr(row, "__getitem__"):
            return scalarize(row[key], default=default)
    except Exception:
        return default
    return default


def make_unique_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    seen: Dict[str, int] = {}
    cols: List[str] = []
    for col in out.columns:
        base = str(col)
        count = seen.get(base, 0) + 1
        seen[base] = count
        cols.append(base if count == 1 else f"{base}__dup{count}")
    out.columns = cols
    return out


def clean_symbol(value: Any) -> str:
    value = scalarize(value, default="")
    if _missing_scalar(value):
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(value).upper().strip())


def safe_filename(text: Any, max_len: int = 120) -> str:
    value = scalarize(text, default="")
    raw = "" if _missing_scalar(value) else str(value).strip()
    raw = re.sub(r"[\\/:*?\"<>|]+", "_", raw)
    raw = re.sub(r"\s+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("._")
    return raw[:max_len] or "unknown"


def safe_str(value: Any, max_len: Optional[int] = None) -> str:
    value = scalarize(value, default="")
    if _missing_scalar(value):
        return ""
    out = str(value).strip()
    return out if max_len is None else out[:max_len]


def to_frame(obj: Any) -> pd.DataFrame:
    if obj is None:
        return pd.DataFrame()
    if isinstance(obj, pd.DataFrame):
        return make_unique_columns(obj)
    if isinstance(obj, list):
        return make_unique_columns(pd.DataFrame(obj))
    if isinstance(obj, dict):
        try:
            return make_unique_columns(pd.DataFrame(obj))
        except Exception:
            return make_unique_columns(pd.DataFrame([obj]))
    return make_unique_columns(pd.DataFrame([{"value": scalarize(obj)}]))


def parse_datetime_series(values: Any, dayfirst: bool = True) -> pd.Series:
    """
    Strict datetime parser for Fundamental data.

    No Pandas format inference. Any unmatched value is kept as NaT.
    """
    if isinstance(values, pd.Series):
        s = values.copy()
    else:
        s = pd.Series(values)

    if pd.api.types.is_datetime64_any_dtype(s):
        return s

    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    text = s.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(["", "none", "null", "nan", "nat", "-", "--", "n/a"]))

    text = text.str.replace(r"\s*(Z|[+-]\d{2}:?\d{2})$", "", regex=True)
    text = text.str.replace(r"\s+(UTC|utc|GMT|gmt)$", "", regex=True)

    for fmt in DATE_FORMATS:
        mask = out.isna() & text.notna()
        if not bool(mask.any()):
            break

        parsed = pd.to_datetime(text.loc[mask], format=fmt, errors="coerce")
        out.loc[mask] = parsed

    return out


def first_existing_col(df: pd.DataFrame, candidates: Sequence[str], contains: bool = False) -> Optional[str]:
    if df is None or df.empty:
        return None
    lower = {str(c).lower(): c for c in df.columns}
    for c in candidates:
        if str(c).lower() in lower:
            return str(lower[str(c).lower()])
    if contains:
        cands = [str(c).lower() for c in candidates]
        for col in df.columns:
            cl = str(col).lower()
            if any(c in cl for c in cands):
                return str(col)
    return None


def infer_quarter_year_from_text(text: Any) -> Tuple[Optional[int], Optional[int]]:
    s = safe_str(text)
    low = s.lower()
    quarter: Optional[int] = None
    year: Optional[int] = None
    patterns = [
        r"(?:qu[yý]|quy|q|quarter)\s*([1-4])(?:\D{0,30}(20\d{2}))?",
        r"(20\d{2})\s*[-_/]?\s*q\s*([1-4])",
        r"q\s*([1-4])\s*[-_/]?\s*(20\d{2})",
        r"([1-4])\s*/\s*(20\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, low, flags=re.I)
        if not m:
            continue
        groups = m.groups()
        try:
            if pat.startswith(r"(20"):
                year = int(groups[0]); quarter = int(groups[1])
            else:
                quarter = int(groups[0])
                if len(groups) >= 2 and groups[1] and re.match(r"20\d{2}", str(groups[1])):
                    year = int(groups[1])
            break
        except Exception:
            pass
    ym = re.search(r"(20\d{2})", low)
    if ym and year is None:
        year = int(ym.group(1))
    return quarter, year


def previous_quarter(q: int, y: int) -> Tuple[int, int]:
    return (4, y - 1) if q <= 1 else (q - 1, y)


def previous_completed_quarter(dt: Optional[datetime] = None) -> Tuple[int, int]:
    dt = dt or datetime.now()
    if dt.month <= 3:
        return 4, dt.year - 1
    if dt.month <= 6:
        return 1, dt.year
    if dt.month <= 9:
        return 2, dt.year
    return 3, dt.year


def as_number(value: Any) -> Optional[float]:
    value = scalarize(value, default=None)
    if _missing_scalar(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            n = float(value)
            return n if math.isfinite(n) else None
        except Exception:
            return None
    text = str(value).strip()
    neg = False
    if text.startswith("(") and text.endswith(")"):
        neg = True
        text = text[1:-1]
    text = text.replace("%", "").replace(",", "").replace(" ", "").replace("−", "-")
    text = re.sub(r"(?i)(vnđ|vnd|đồng|dong)", "", text)
    try:
        n = float(text)
        return -n if neg else n
    except Exception:
        return None


def fmt_value(value: Any) -> str:
    value = scalarize(value, default=None)
    n = as_number(value)
    if n is None:
        return safe_str(value, max_len=120)
    absn = abs(n)
    if absn >= 1e12:
        return f"{n/1e12:,.2f} nghìn tỷ"
    if absn >= 1e9:
        return f"{n/1e9:,.2f} tỷ"
    if absn >= 1e6:
        return f"{n/1e6:,.2f} triệu"
    if absn >= 1000:
        return f"{n:,.0f}"
    if absn >= 1:
        return f"{n:,.2f}"
    return f"{n:.4f}"


def pct_change(current: Any, previous: Any) -> Optional[float]:
    c = as_number(current)
    p = as_number(previous)
    if c is None or p is None or abs(p) < 1e-12:
        return None
    return (c - p) / abs(p) * 100.0


def is_empty_value(value: Any) -> bool:
    return _missing_scalar(scalarize(value, default=None))


def data_frame_to_markdown(df: pd.DataFrame, max_rows: int = 120, max_cols: int = 120) -> str:
    df = to_frame(df)
    if df.empty:
        return "_Không có dữ liệu._"
    work = df.copy()
    if len(work) > max_rows:
        work = work.head(max_rows)
    if len(work.columns) > max_cols:
        work = work.iloc[:, :max_cols]
    try:
        return work.to_markdown(index=False)
    except Exception:
        return "```text\n" + work.to_string(index=False) + "\n```"


def impact_comment(metric: Any, current: Any = None, previous: Any = None) -> Tuple[str, str]:
    m = safe_str(metric).lower().replace("_", " ")
    category = "general"
    base = "Chỉ tiêu này cần được đọc cùng xu hướng lợi nhuận, dòng tiền và định giá để đánh giá tác động lên giá cổ phiếu."
    for keywords, cat, comment in IMPACT_KEYWORDS:
        if any(k.lower() in m for k in keywords):
            category = cat
            base = comment
            break
    chg = pct_change(current, previous)
    if chg is None:
        return category, base
    direction = "tăng" if chg > 0 else "giảm" if chg < 0 else "không đổi"
    return category, base + f" Kỳ này {direction} {abs(chg):.1f}% so với kỳ so sánh."


@dataclass
class MetricReadthrough:
    metric: str
    source_column: str
    current: Any
    previous: Any = None
    change_pct: Optional[float] = None
    category: str = "general"
    interpretation: str = ""


@dataclass
class TableReadthrough:
    name: str
    raw_shape: Tuple[int, int]
    selected_shape: Tuple[int, int]
    latest_period: str
    previous_period: str
    metrics: List[MetricReadthrough] = field(default_factory=list)
    skipped_null_quarter_rows: int = 0
    skipped_empty_columns: List[str] = field(default_factory=list)
    data_quality_notes: List[str] = field(default_factory=list)
    latest_slice: pd.DataFrame = field(default_factory=pd.DataFrame)
    all_null_columns: List[str] = field(default_factory=list)


class FundamentalTableAnalyzer:
    def __init__(self, quarter: int, year: int):
        self.quarter = int(quarter)
        self.year = int(year)
        self.prev_quarter, self.prev_year = previous_quarter(self.quarter, self.year)

    def analyze(self, table_name: str, df: pd.DataFrame) -> TableReadthrough:
        df = to_frame(df)
        result = TableReadthrough(
            name=table_name,
            raw_shape=(len(df), len(df.columns) if df is not None else 0),
            selected_shape=(0, 0),
            latest_period=f"{self.year}-Q{self.quarter}",
            previous_period=f"{self.prev_year}-Q{self.prev_quarter}",
        )
        if df is None or df.empty:
            result.data_quality_notes.append("API trả về DataFrame rỗng.")
            return result
        result.all_null_columns = [str(c) for c in df.columns if df[c].isna().all()]
        clean_df = df.dropna(axis=1, how="all").copy()
        if clean_df.empty:
            result.data_quality_notes.append("Tất cả cột đều rỗng sau khi drop cột all-null.")
            result.skipped_empty_columns.extend(result.all_null_columns)
            return result
        row_result = self._analyze_row_wise(clean_df, result)
        if row_result.metrics:
            return row_result
        wide_result = self._analyze_wide(clean_df, result)
        if wide_result.metrics:
            return wide_result
        return self._analyze_single_snapshot(clean_df, result)

    def _add_period_cols(self, df: pd.DataFrame) -> pd.DataFrame:
        work = to_frame(df)
        q_col = first_existing_col(work, ["quarter", "quy", "q", "fiscal_quarter", "fiscalQuarter"])
        y_col = first_existing_col(work, ["year", "fiscal_year", "fiscalYear", "report_year", "reportYear", "nam"])
        period_col = first_existing_col(work, ["period", "report_period", "reportPeriod", "fiscal_period", "fiscalPeriod"])
        text_cols = [c for c in [q_col, y_col, period_col] if c]
        if text_cols:
            row_text = work[text_cols].fillna("").astype(str).agg(" ".join, axis=1)
        else:
            obj_cols = [c for c in work.columns if work[c].dtype == object][:8]
            row_text = work[obj_cols].fillna("").astype(str).agg(" ".join, axis=1) if obj_cols else pd.Series([""] * len(work), index=work.index)
        if q_col:
            q_series = pd.to_numeric(work[q_col], errors="coerce")
            q_from_text = row_text.map(lambda x: infer_quarter_year_from_text(x)[0])
            work["__quarter"] = q_series.combine_first(pd.to_numeric(q_from_text, errors="coerce"))
        else:
            work["__quarter"] = row_text.map(lambda x: infer_quarter_year_from_text(x)[0])
        if y_col:
            y_series = pd.to_numeric(work[y_col], errors="coerce")
            y_from_text = row_text.map(lambda x: infer_quarter_year_from_text(x)[1])
            work["__year"] = y_series.combine_first(pd.to_numeric(y_from_text, errors="coerce"))
        else:
            work["__year"] = row_text.map(lambda x: infer_quarter_year_from_text(x)[1])
        return work

    def _analyze_row_wise(self, df: pd.DataFrame, result: TableReadthrough) -> TableReadthrough:
        work = self._add_period_cols(df)
        has_any_period = bool(work["__quarter"].notna().any() and work["__year"].notna().any())
        has_explicit_q = first_existing_col(df, ["quarter", "quy", "q", "fiscal_quarter", "fiscalQuarter", "period"], contains=False) is not None
        if not has_any_period:
            result.data_quality_notes.append("Không nhận diện được latest quarter theo hàng; thử phân tích dạng bảng wide.")
            return result
        if has_explicit_q:
            result.skipped_null_quarter_rows = int(work["__quarter"].isna().sum())
            work = work[work["__quarter"].notna()].copy()
        latest = work[(pd.to_numeric(work["__quarter"], errors="coerce") == self.quarter) & (pd.to_numeric(work["__year"], errors="coerce") == self.year)].copy()
        previous = work[(pd.to_numeric(work["__quarter"], errors="coerce") == self.prev_quarter) & (pd.to_numeric(work["__year"], errors="coerce") == self.prev_year)].copy()
        if latest.empty:
            sortable = work.copy()
            sortable["__ys"] = pd.to_numeric(sortable["__year"], errors="coerce").fillna(0)
            sortable["__qs"] = pd.to_numeric(sortable["__quarter"], errors="coerce").fillna(0)
            sortable = sortable.sort_values(["__ys", "__qs"], ascending=[False, False])
            if not sortable.empty and as_number(safe_get(sortable.iloc[0], "__qs", 0)):
                y = int(as_number(safe_get(sortable.iloc[0], "__ys", 0)) or self.year)
                q = int(as_number(safe_get(sortable.iloc[0], "__qs", 0)) or self.quarter)
                latest = work[(pd.to_numeric(work["__quarter"], errors="coerce") == q) & (pd.to_numeric(work["__year"], errors="coerce") == y)].copy()
                pq, py = previous_quarter(q, y)
                previous = work[(pd.to_numeric(work["__quarter"], errors="coerce") == pq) & (pd.to_numeric(work["__year"], errors="coerce") == py)].copy()
                result.latest_period = f"{y}-Q{q}"
                result.previous_period = f"{py}-Q{pq}"
                result.data_quality_notes.append(f"Requested {self.year}-Q{self.quarter} not found; used latest available {y}-Q{q}.")
        if latest.empty:
            return result
        result.latest_slice = latest.drop(columns=["__quarter", "__year"], errors="ignore")
        result.selected_shape = result.latest_slice.shape
        latest_row = latest.iloc[0]
        prev_row = previous.iloc[0] if not previous.empty else None
        self._collect_metrics_from_rows(result, latest_row, prev_row, df.columns)
        return result

    def _analyze_wide(self, df: pd.DataFrame, result: TableReadthrough) -> TableReadthrough:
        period_cols: List[Tuple[str, int, int]] = []
        for col in df.columns:
            q, y = infer_quarter_year_from_text(col)
            if q and y:
                period_cols.append((str(col), int(q), int(y)))
        if not period_cols:
            result.data_quality_notes.append("Không tìm thấy cột dạng period như 2026-Q2/Q2-2026.")
            return result
        period_cols = sorted(period_cols, key=lambda x: (x[2], x[1]), reverse=True)
        latest_col = None
        prev_col = None
        latest_q, latest_y = None, None
        for col, q, y in period_cols:
            if q == self.quarter and y == self.year:
                latest_col, latest_q, latest_y = col, q, y
                break
        if latest_col is None:
            latest_col, latest_q, latest_y = period_cols[0]
            result.latest_period = f"{latest_y}-Q{latest_q}"
            result.data_quality_notes.append(f"Requested {self.year}-Q{self.quarter} not found; used latest period column {latest_col}.")
        if latest_q and latest_y:
            pq, py = previous_quarter(latest_q, latest_y)
            for col, q, y in period_cols:
                if q == pq and y == py:
                    prev_col = col
                    result.previous_period = f"{py}-Q{pq}"
                    break
        metric_col = first_existing_col(df, METRIC_NAME_CANDIDATES, contains=True)
        if not metric_col:
            non_period = [c for c in df.columns if str(c) not in {x[0] for x in period_cols}]
            metric_col = non_period[0] if non_period else df.columns[0]
        latest_slice = df[[metric_col, latest_col] + ([prev_col] if prev_col else [])].copy()
        latest_slice = latest_slice[latest_slice[latest_col].map(lambda x: not is_empty_value(x))]
        result.latest_slice = latest_slice
        result.selected_shape = latest_slice.shape
        for _, row in latest_slice.iterrows():
            metric = safe_str(safe_get(row, metric_col), max_len=180) or str(metric_col)
            current = safe_get(row, latest_col)
            previous = safe_get(row, prev_col) if prev_col else None
            change = pct_change(current, previous)
            cat, interp = impact_comment(metric, current, previous)
            result.metrics.append(MetricReadthrough(metric, latest_col, current, previous, change, cat, interp))
        return result

    def _analyze_single_snapshot(self, df: pd.DataFrame, result: TableReadthrough) -> TableReadthrough:
        if df.empty:
            return result
        latest_row = df.iloc[0]
        result.latest_slice = df.head(1).copy()
        result.selected_shape = result.latest_slice.shape
        self._collect_metrics_from_rows(result, latest_row, None, df.columns)
        result.data_quality_notes.append("Không có thông tin period rõ ràng; phân tích snapshot dòng đầu tiên.")
        return result

    def _collect_metrics_from_rows(self, result: TableReadthrough, latest_row: pd.Series, prev_row: Optional[pd.Series], original_cols: Iterable[Any]) -> None:
        lower_system = {x.lower() for x in SYSTEM_COLUMNS | PERIOD_COLUMNS}
        for col in original_cols:
            col_s = str(col)
            if col_s.startswith("__") or col_s.lower() in lower_system:
                continue
            current = safe_get(latest_row, col)
            if is_empty_value(current):
                result.skipped_empty_columns.append(col_s)
                continue
            previous = safe_get(prev_row, col) if prev_row is not None else None
            change = pct_change(current, previous)
            cat, interp = impact_comment(col_s, current, previous)
            result.metrics.append(MetricReadthrough(col_s, col_s, current, previous, change, cat, interp))


def select_latest_quarter_from_filing(filing_df: pd.DataFrame) -> Tuple[Optional[Dict[str, Any]], Optional[int], Optional[int]]:
    filing_df = to_frame(filing_df)
    if filing_df.empty:
        return None, None, None
    work = filing_df.copy()
    priority_cols = [c for c in ["doc_title", "doc_name", "title", "name", "report_title", "description"] if c in work.columns]
    if priority_cols:
        title_text = work[priority_cols].fillna("").astype(str).agg(" ".join, axis=1)
    else:
        title_text = pd.Series([""] * len(work), index=work.index)
    row_text = work.fillna("").astype(str).agg(" ".join, axis=1)

    def parse_row(title: str, full: str) -> Tuple[Optional[int], Optional[int]]:
        q, y = infer_quarter_year_from_text(title)
        if q and y:
            return q, y
        # Fallback to full row only if quarter is explicitly present. This avoids
        # picking a year from doc_url like /2026/NGHI... without a real Q label.
        q2, y2 = infer_quarter_year_from_text(full)
        if q2:
            return q2, y2
        return q, y

    parsed = [parse_row(t, r) for t, r in zip(title_text.tolist(), row_text.tolist())]
    work["__quarter"] = [x[0] for x in parsed]
    work["__year"] = [x[1] for x in parsed]
    work["__row_text"] = row_text
    date_col = first_existing_col(work, ["publish_date", "published_at", "published_date", "date", "time", "report_date", "filing_date", "created_at", "updated_at"], contains=True)
    work["__date"] = parse_datetime_series(work[date_col]) if date_col else pd.NaT
    text_l = work["__row_text"].str.lower()
    fs_mask = text_l.str.contains(r"bctc|báo cáo tài chính|bao cao tai chinh|financial report|financial statement", regex=True, na=False)
    q_mask = work["__quarter"].notna()
    candidates = work[fs_mask & q_mask].copy()
    if candidates.empty:
        candidates = work[q_mask].copy()
    if candidates.empty:
        candidates = work[fs_mask].copy()
    if candidates.empty:
        candidates = work.copy()
    candidates["__ys"] = pd.to_numeric(candidates["__year"], errors="coerce").fillna(0)
    candidates["__qs"] = pd.to_numeric(candidates["__quarter"], errors="coerce").fillna(0)
    candidates = candidates.sort_values(["__ys", "__qs", "__date"], ascending=[False, False, False], na_position="last")
    row = candidates.iloc[0]
    q_num = as_number(safe_get(row, "__qs", 0))
    y_num = as_number(safe_get(row, "__ys", 0))
    q = int(q_num) if q_num and q_num > 0 else None
    y = int(y_num) if y_num and y_num > 0 else None
    clean: Dict[str, Any] = {}
    for col in candidates.columns:
        if str(col).startswith("__"):
            continue
        v = safe_get(row, col)
        clean[str(col)] = None if is_empty_value(v) else v
    return clean, q, y


def extract_url(row: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(row, Mapping) or len(row) == 0:
        return None
    url_cols = ["doc_url", "docUrl", "url", "file_url", "fileUrl", "download_url", "downloadUrl", "link", "href", "attachment", "file", "report_url", "reportUrl"]
    for col in url_cols:
        if col in row:
            raw = safe_get(row, col)
            if not is_empty_value(raw):
                text = safe_str(raw).strip('"\'')
                if text.startswith("//"):
                    text = "https:" + text
                if text.startswith("http://") or text.startswith("https://"):
                    return text
    all_text = " ".join(safe_str(v) for v in row.values() if not is_empty_value(v))
    m = re.search(r"https?://[^\s'\"<>]+", all_text)
    return m.group(0) if m else None


def safe_call(fn, label: str, errors: List[str]) -> pd.DataFrame:
    try:
        return to_frame(fn())
    except Exception as exc:
        errors.append(f"{label} failed: {type(exc).__name__}: {exc}")
        logging.warning("%s failed: %s", label, exc)
        return pd.DataFrame()


def get_company_name(symbol: str) -> str:
    try:
        from vnstock_data import Reference  # type: ignore
        ref = Reference()
        df = to_frame(ref.company(symbol).info())
        if not df.empty:
            row = df.iloc[0]
            for col in ["company_name", "organ_name", "short_name", "name", "companyName", "organName", "ticker"]:
                val = safe_get(row, col)
                if not is_empty_value(val):
                    return safe_str(val)
            for col in df.columns:
                val = safe_get(row, col)
                if isinstance(val, str) and len(val.strip()) > 2:
                    return val.strip()
    except Exception as exc:
        logging.info("Reference.company(%s).info failed: %s", symbol, exc)
    return symbol


def call_fundamental_methods(symbol: str, *, note_lang: str = "vi", scorecard: Any = "auto", financial_health_limit: int = 4, filing_doc_type: Optional[str] = "financial_report") -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    from vnstock_data import Fundamental  # type: ignore
    errors: List[str] = []
    fun = Fundamental()
    eq = fun.equity(symbol)
    if filing_doc_type:
        filing = safe_call(lambda: eq.filing(doc_type=filing_doc_type), "filing(doc_type=financial_report)", errors)
        if filing.empty:
            filing = safe_call(lambda: eq.filing(), "filing() fallback", errors)
    else:
        filing = safe_call(lambda: eq.filing(), "filing()", errors)
    tables: Dict[str, pd.DataFrame] = {
        "filing": filing,
        "income_statement_quarter": safe_call(lambda: eq.income_statement(period="quarter"), "income_statement(period=quarter)", errors),
        "balance_sheet_quarter": safe_call(lambda: eq.balance_sheet(period="quarter"), "balance_sheet(period=quarter)", errors),
        "cash_flow_quarter": safe_call(lambda: eq.cash_flow(period="quarter"), "cash_flow(period=quarter)", errors),
        "ratio_quarter": safe_call(lambda: eq.ratio(period="quarter"), "ratio(period=quarter)", errors),
    }
    note = safe_call(lambda: eq.note(period="quarter", lang=note_lang), "note(period=quarter)", errors)
    if note.empty:
        note = safe_call(lambda: eq.note(period="year", lang=note_lang), "note(period=year) fallback", errors)
    tables["note"] = note
    health = safe_call(lambda: eq.financial_health(scorecard=scorecard, limit=financial_health_limit), "financial_health(scorecard, limit)", errors)
    if health.empty:
        health = safe_call(lambda: eq.financial_health(), "financial_health() fallback", errors)
    tables["financial_health"] = health
    return tables, errors


def build_flags(readthroughs: Sequence[TableReadthrough]) -> Tuple[List[str], List[str], List[str]]:
    positive: List[str] = []
    negative: List[str] = []
    watch: List[str] = []
    for table in readthroughs:
        for m in table.metrics:
            metric_l = safe_str(m.metric).lower()
            chg = m.change_pct
            value_n = as_number(m.current)
            if chg is not None:
                if any(k in metric_l for k in ["revenue", "doanh thu", "profit", "lợi nhuận", "lnst", "eps", "roe", "roa", "cfo", "cash flow"]):
                    if chg >= 10:
                        positive.append(f"{table.name}: {m.metric} tăng {chg:.1f}% so với kỳ trước.")
                    elif chg <= -10:
                        negative.append(f"{table.name}: {m.metric} giảm {abs(chg):.1f}% so với kỳ trước.")
                if any(k in metric_l for k in ["debt", "borrow", "nợ vay", "liabilities", "phải thu", "receivable", "inventory", "hàng tồn kho", "npl", "nợ xấu"]):
                    if chg >= 15:
                        watch.append(f"{table.name}: {m.metric} tăng {chg:.1f}%, cần kiểm tra rủi ro chất lượng tài sản/vốn lưu động.")
            if value_n is not None:
                if any(k in metric_l for k in ["cfo", "operating cash", "lưu chuyển tiền thuần từ hoạt động kinh doanh"]) and value_n < 0:
                    negative.append(f"{table.name}: {m.metric} âm, cần kiểm tra chất lượng lợi nhuận.")
                if "roe" in metric_l and value_n >= 15:
                    positive.append(f"{table.name}: ROE ở mức cao ({fmt_value(value_n)}).")
                if "roe" in metric_l and value_n < 8:
                    watch.append(f"{table.name}: ROE thấp ({fmt_value(value_n)}), có thể hạn chế định giá P/B.")
    def uniq(xs: List[str], limit: int = 12) -> List[str]:
        return list(dict.fromkeys(xs))[:limit]
    return uniq(positive), uniq(negative), uniq(watch)


def metric_table_to_markdown(metrics: Sequence[MetricReadthrough]) -> str:
    if not metrics:
        return "_Không có chỉ tiêu non-null để phân tích._"
    rows = []
    for m in metrics:
        rows.append({
            "metric": safe_str(m.metric, max_len=140),
            "current": fmt_value(m.current),
            "previous": fmt_value(m.previous) if not is_empty_value(m.previous) else "",
            "chg_%": "" if m.change_pct is None else f"{m.change_pct:.1f}%",
            "category": m.category,
            "interpretation": m.interpretation,
        })
    return data_frame_to_markdown(pd.DataFrame(rows), max_rows=1000, max_cols=12)


def write_json(path: Union[str, Path], obj: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    return p


def write_text(path: Union[str, Path], text: str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if isinstance(text, str) else ("" if is_empty_value(text) else str(scalarize(text, default=""))), encoding="utf-8")
    return p


def save_csv(df: pd.DataFrame, path: Union[str, Path]) -> Optional[Path]:
    df = to_frame(df)
    if df.empty:
        return None
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8-sig")
    return p


def build_fundamental_markdown(
    *,
    symbol: str,
    company_name: str,
    quarter: int,
    year: int,
    filing_row: Optional[Mapping[str, Any]],
    source_url: Optional[str],
    readthroughs: Sequence[TableReadthrough],
    raw_paths: Mapping[str, str],
    errors: Sequence[str],
) -> str:
    positive, negative, watch = build_flags(readthroughs)

    def bullets(items: Sequence[str]) -> str:
        return "\n".join(f"- {x}" for x in items) if items else "- Không có điểm nổi bật tự động phát hiện."

    filing_md = "_Không tìm thấy filing row phù hợp._"
    if isinstance(filing_row, Mapping) and len(filing_row) > 0:
        filing_items = []
        for k, v in filing_row.items():
            if not is_empty_value(v):
                filing_items.append({"field": k, "value": safe_str(v, max_len=500)})
        filing_md = data_frame_to_markdown(pd.DataFrame(filing_items), max_rows=80, max_cols=4)

    lines = [
        f"# Báo cáo phân tích BCTC cấu trúc - {symbol} ({company_name})",
        "",
        f"- Kỳ phân tích: **{year}-Q{quarter}**",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Nguồn dữ liệu: `vnstock_data.Fundamental().equity('{symbol}')`",
        f"- Filing doc_url metadata: {source_url or 'N/A'}",
        "- PDF/OCR: disabled. LLM input is generated from structured Fundamental tables only.",
        "",
        "## Executive readthrough cho LLM",
        "",
        "### Điểm tích cực tự động phát hiện",
        bullets(positive),
        "",
        "### Điểm tiêu cực / suy yếu tự động phát hiện",
        bullets(negative),
        "",
        "### Điểm cần theo dõi kỹ",
        bullets(watch),
        "",
        "## Filing metadata",
        filing_md,
        "",
        "## Raw data files",
    ]
    for name, path in raw_paths.items():
        lines.append(f"- {name}: `{path}`")
    lines.extend(["", "## API / data quality notes"])
    lines.extend(f"- {e}" for e in errors) if errors else lines.append("- Không có lỗi API ghi nhận.")

    for table in readthroughs:
        lines.extend([
            "",
            f"# Section: {table.name}",
            "",
            f"- Raw shape: {table.raw_shape[0]} rows x {table.raw_shape[1]} cols",
            f"- Selected latest slice: {table.selected_shape[0]} rows x {table.selected_shape[1]} cols",
            f"- Latest period used: {table.latest_period}",
            f"- Previous period used: {table.previous_period}",
            f"- Rows skipped because quarter was null: {table.skipped_null_quarter_rows}",
            f"- All-null columns skipped: {len(table.all_null_columns)}",
            f"- Empty/latest-null columns skipped: {len(table.skipped_empty_columns)}",
        ])
        if table.data_quality_notes:
            lines.append("- Notes: " + "; ".join(table.data_quality_notes[:8]))
        if table.all_null_columns:
            lines.append("- All-null columns: " + ", ".join(table.all_null_columns[:80]))
        if table.skipped_empty_columns:
            lines.append("- Skipped empty/latest-null columns: " + ", ".join(table.skipped_empty_columns[:80]))
        lines.extend([
            "",
            "## Column-by-column / line-item readthrough",
            metric_table_to_markdown(table.metrics),
            "",
            "## Latest period raw slice",
            data_frame_to_markdown(table.latest_slice, max_rows=80, max_cols=120),
        ])
    return "\n".join(lines).strip() + "\n"


def get_fundamental_analysis_layer(
    symbol: str,
    output_root: Union[str, Path],
    *,
    note_lang: str = "vi",
    scorecard: Any = "auto",
    financial_health_limit: int = 4,
    filing_doc_type: Optional[str] = "financial_report",
    force_refresh: bool = False,
    **_ignored_options: Any,
) -> JsonDict:
    """Fetch structured Fundamental data and generate a full Markdown BCTC report.

    Extra keyword options are accepted for backwards compatibility and ignored.
    """
    symbol = clean_symbol(symbol)
    if not symbol:
        raise ValueError("symbol is required")
    company_name = get_company_name(symbol)
    output_root = ensure_dir(output_root)

    tables, errors = call_fundamental_methods(
        symbol,
        note_lang=note_lang,
        scorecard=scorecard,
        financial_health_limit=financial_health_limit,
        filing_doc_type=filing_doc_type,
    )
    filing_row, quarter, year = select_latest_quarter_from_filing(tables.get("filing", pd.DataFrame()))
    if quarter is None or year is None:
        quarter, year = previous_completed_quarter()
        errors.append(f"Could not infer latest quarter from filing; fallback to previous completed quarter {year}-Q{quarter}.")

    quarter_dir = ensure_dir(output_root / f"quarter_{quarter}")
    base_name = safe_filename(f"{symbol}_{company_name}_{year}_Q{quarter}")
    md_path = quarter_dir / f"{base_name}_structured_financial_report.md"
    audit_path = quarter_dir / f"{base_name}_structured_financial_audit.json"

    if md_path.exists() and audit_path.exists() and not force_refresh:
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            audit["used_cache"] = True
            return audit
        except Exception:
            pass

    raw_paths: Dict[str, str] = {}
    for name, df in tables.items():
        df = to_frame(df)
        if not df.empty:
            path = quarter_dir / f"{base_name}_{name}.csv"
            save_csv(df, path)
            raw_paths[name] = str(path)

    source_url = extract_url(filing_row)
    analyzer = FundamentalTableAnalyzer(quarter, year)
    readthroughs = [analyzer.analyze(name, df) for name, df in tables.items()]
    markdown = build_fundamental_markdown(
        symbol=symbol,
        company_name=company_name,
        quarter=quarter,
        year=year,
        filing_row=filing_row,
        source_url=source_url,
        readthroughs=readthroughs,
        raw_paths=raw_paths,
        errors=errors,
    )
    write_text(md_path, markdown)

    audit = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "used_cache": False,
        "symbol": symbol,
        "company_name": company_name,
        "quarter": quarter,
        "year": year,
        "period_label": f"{year}-Q{quarter}",
        "quarter_dir": str(quarter_dir),
        "markdown_path": str(md_path),
        "audit_json_path": str(audit_path),
        "raw_csv_paths": raw_paths,
        "filing_row": filing_row,
        "source_url": source_url,
        "pdf_path": None,
        "errors": list(errors),
        "table_summaries": [
            {
                "name": t.name,
                "raw_shape": t.raw_shape,
                "selected_shape": t.selected_shape,
                "latest_period": t.latest_period,
                "previous_period": t.previous_period,
                "metrics_count": len(t.metrics),
                "skipped_null_quarter_rows": t.skipped_null_quarter_rows,
                "all_null_columns_count": len(t.all_null_columns),
                "skipped_empty_columns_count": len(t.skipped_empty_columns),
                "data_quality_notes": t.data_quality_notes,
            }
            for t in readthroughs
        ],
    }
    write_json(audit_path, audit)
    return audit


# Backward-compatible alias used by older deep analyzers.
def get_fundamental_report(*args: Any, **kwargs: Any) -> JsonDict:
    return get_fundamental_analysis_layer(*args, **kwargs)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate structured Fundamental/BCTC markdown from vnstock_data.")
    parser.add_argument("--symbol", required=True, help="Ticker, e.g. TCB or MBS")
    parser.add_argument("--output_root", default="./data/financial_statements", help="Root folder for financial statement markdown/cache")
    parser.add_argument("--note_lang", default="vi")
    parser.add_argument("--scorecard", default="auto")
    parser.add_argument("--financial_health_limit", type=int, default=4)
    parser.add_argument("--filing_doc_type", default="financial_report")
    parser.add_argument("--force_refresh", action="store_true")
    parser.add_argument("--log_level", default="INFO")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s | %(levelname)s | %(message)s")
    result = get_fundamental_analysis_layer(
        args.symbol,
        args.output_root,
        note_lang=args.note_lang,
        scorecard=args.scorecard,
        financial_health_limit=args.financial_health_limit,
        filing_doc_type=args.filing_doc_type,
        force_refresh=args.force_refresh,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(f"\nMarkdown saved: {result.get('markdown_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
