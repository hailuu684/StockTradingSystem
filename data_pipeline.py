from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

try:  # pragma: no cover - import depends on the user's licensed environment
    from vnstock_data import Market, Fundamental, Analytics  # type: ignore
except Exception:  # pragma: no cover
    Market = None  # type: ignore
    Fundamental = None  # type: ignore
    Analytics = None  # type: ignore

try:  # pragma: no cover
    from vnstock_data import Insights, Macro  # type: ignore
except Exception:  # pragma: no cover
    try:
        from vnstock_data.ui import Insights, Macro  # type: ignore
    except Exception:
        Insights = None  # type: ignore
        Macro = None  # type: ignore


ALLOWED_PREFIXES: Tuple[str, ...] = (
    "MKT_",
    "FLOW_",
    "INS_",
    "VAL_",
    "FUN_",
    "MAC_",
    "CMD_",
)

SYSTEM_COLUMNS: Tuple[str, ...] = (
    "time",
    "date",
    "trading_date",
    "report_date",
    "reportdate",
    "report_time",
    "period",
    "period_end",
    "released_at",
    "event_date",
    "symbol",
    "ticker",
    "code",
    "stock_code",
    "organ_code",
    "exchange",
    "floor",
    "source",
)

DATE_CANDIDATES: Tuple[str, ...] = (
    "released_at",
    "time",
    "date",
    "trading_date",
    "report_date",
    "reportDate",
    "report_time",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class FeatureRoute:
    prefix: str
    keywords: Tuple[str, ...]
    fill_policy: str
    impact: str


# Dynamic router taxonomy. Each route carries the mandatory price-impact comment
# used to audit every generated feature in feature_catalog_. The router is not a
# whitelist: unmatched columns are still routed by their source_type fallback.
FEATURE_ROUTING_MAP: Tuple[FeatureRoute, ...] = (
    FeatureRoute(
        # FLOW_*: Net buying, active buying and order pressure change short-term demand/supply balance.
        prefix="FLOW_",
        keywords=(
            "foreign",
            "proprietary",
            "self_trade",
            "tu_doanh",
            "net_val",
            "net_value",
            "net_vol",
            "net_volume",
            "buy_volume",
            "sell_volume",
            "buy_value",
            "sell_value",
            "active_buy",
            "active_sell",
            "unmatched",
            "put_through",
            "deal_volume",
            "deal_value",
            "bid_volume",
            "ask_volume",
        ),
        fill_policy="zero",
        impact="FLOW: Dòng tiền mua/bán ròng tác động trực tiếp đến mất cân bằng cung-cầu và áp lực khớp lệnh.",
    ),
    FeatureRoute(
        # MKT_*: Price, liquidity and order-book variables express the traded equilibrium price and market depth.
        prefix="MKT_",
        keywords=(
            "open",
            "high",
            "low",
            "close",
            "price",
            "match_price",
            "average_price",
            "reference_price",
            "ceiling_price",
            "floor_price",
            "volume",
            "total_volume",
            "trading_volume",
            "value",
            "trading_value",
            "turnover",
            "bid_price",
            "ask_price",
            "bid_vol",
            "ask_vol",
            "order_book",
            "spread",
            "depth",
            "liquidity",
            "room",
        ),
        fill_policy="median",
        impact="MKT: Giá, thanh khoản và độ sâu sổ lệnh phản ánh điểm cân bằng cung-cầu hiện tại của cổ phiếu.",
    ),
    FeatureRoute(
        # INS_*: Momentum, trend, rank and relative-strength variables approximate crowding and trend-following demand.
        prefix="INS_",
        keywords=(
            "rsi",
            "macd",
            "histogram",
            "signal",
            "stoch",
            "adx",
            "ema",
            "sma",
            "ma_",
            "momentum",
            "strength",
            "rs_",
            "relative_strength",
            "trend",
            "rank",
            "score",
            "rating",
            "technical",
            "volatility",
            "beta",
            "alpha",
            "drawdown",
            "zscore",
            "screener",
            "gainer",
            "loser",
        ),
        fill_policy="neutral",
        impact="INS: Xung lượng, xu hướng và sức mạnh tương đối cho biết dòng tiền đang ưu tiên hay rút khỏi mã cổ phiếu.",
    ),
    FeatureRoute(
        # VAL_*: Valuation multiples translate expected earnings/book value into intrinsic-value pressure.
        prefix="VAL_",
        keywords=(
            "pe",
            "p_e",
            "ttm_pe",
            "pb",
            "p_b",
            "ttm_pb",
            "eps",
            "eps_growth",
            "book_value",
            "bvps",
            "dividend",
            "dividend_yield",
            "market_cap",
            "enterprise_value",
            "ev_",
            "valuation",
            "multiple",
            "fair_value",
            "target_price",
        ),
        fill_policy="median",
        impact="VAL: Định giá và tăng trưởng EPS quyết định biên an toàn, kỳ vọng tái định giá và giá trị nội tại.",
    ),
    FeatureRoute(
        # FUN_*: Balance-sheet, profitability and solvency variables govern sustainable intrinsic value.
        prefix="FUN_",
        keywords=(
            "roe",
            "roa",
            "roic",
            "asset",
            "liabilit",
            "equity",
            "debt",
            "loan",
            "deposit",
            "npl",
            "provision",
            "capital",
            "revenue",
            "income",
            "profit",
            "margin",
            "cash_flow",
            "operating_cash",
            "free_cash",
            "current_ratio",
            "quick_ratio",
            "gross_margin",
            "net_margin",
            "health",
            "llm_risk_score",
            "llm_growth_score",
        ),
        fill_policy="median",
        impact="FUN: Chất lượng tài sản, lợi nhuận, đòn bẩy và dòng tiền chi phối giá trị nội tại dài hạn.",
    ),
    FeatureRoute(
        # MAC_*: Macro variables affect discount rates, credit growth, inflation expectations and risk appetite.
        prefix="MAC_",
        keywords=(
            "exchange",
            "usd",
            "vnd",
            "fx",
            "rate",
            "interest",
            "interbank",
            "overnight",
            "cpi",
            "inflation",
            "gdp",
            "fdi",
            "money_supply",
            "m2",
            "import",
            "export",
            "retail",
            "industry_prod",
            "population",
            "labor",
            "macro",
        ),
        fill_policy="median",
        impact="MAC: Vĩ mô tác động tới lãi suất chiết khấu, tăng trưởng tín dụng, lạm phát và khẩu vị rủi ro thị trường.",
    ),
    FeatureRoute(
        # CMD_*: Commodity prices transmit input-cost, inflation and risk-rotation signals into equity valuation.
        prefix="CMD_",
        keywords=(
            "gold",
            "oil",
            "wti",
            "brent",
            "steel",
            "iron",
            "ore",
            "gas",
            "coke",
            "coal",
            "fertilizer",
            "ure",
            "soybean",
            "corn",
            "sugar",
            "pork",
            "commodity",
        ),
        fill_policy="median",
        impact="CMD: Giá hàng hóa ảnh hưởng chi phí đầu vào, kỳ vọng lạm phát và sự dịch chuyển dòng tiền giữa tài sản rủi ro/trú ẩn.",
    ),
)

SOURCE_DEFAULT_PREFIX: Mapping[str, str] = {
    "market": "MKT_",
    "ohlcv": "MKT_",
    "order_book": "MKT_",
    "price_depth": "MKT_",
    "quote": "MKT_",
    "flow": "FLOW_",
    "foreign_flow": "FLOW_",
    "proprietary_flow": "FLOW_",
    "trade_history": "FLOW_",
    "insights": "INS_",
    "technical": "INS_",
    "analytics": "VAL_",
    "valuation": "VAL_",
    "fundamental": "FUN_",
    "ratio": "FUN_",
    "financial": "FUN_",
    "macro": "MAC_",
    "economy": "MAC_",
    "currency": "MAC_",
    "commodity": "CMD_",
}

PREFIX_DEFAULT_IMPACT: Mapping[str, str] = {
    "MKT_": "MKT: Biến thị trường phản ánh giá cân bằng, thanh khoản và độ sâu cung-cầu.",
    "FLOW_": "FLOW: Biến dòng tiền phản ánh lực mua/bán ròng và áp lực hấp thụ hàng.",
    "INS_": "INS: Biến insight/kỹ thuật phản ánh xung lượng, xu hướng và sức mạnh tương đối.",
    "VAL_": "VAL: Biến định giá phản ánh mức thị trường đang trả cho lợi nhuận, sổ sách hoặc tăng trưởng.",
    "FUN_": "FUN: Biến cơ bản phản ánh sức khỏe tài chính và khả năng tạo giá trị nội tại.",
    "MAC_": "MAC: Biến vĩ mô ảnh hưởng lãi suất chiết khấu, lạm phát và nhu cầu tín dụng.",
    "CMD_": "CMD: Biến hàng hóa truyền dẫn chi phí đầu vào, lạm phát và dòng tiền trú ẩn.",
}

PREFIX_DEFAULT_FILL: Mapping[str, str] = {
    "MKT_": "median",
    "FLOW_": "zero",
    "INS_": "neutral",
    "VAL_": "median",
    "FUN_": "median",
    "MAC_": "median",
    "CMD_": "median",
}

# Canonical aliases kept stable for downstream model contracts.
CANONICAL_ALIASES: Mapping[Tuple[str, str, str], str] = {
    ("market", "ohlcv", "open"): "MKT_open",
    ("market", "ohlcv", "high"): "MKT_high",
    ("market", "ohlcv", "low"): "MKT_low",
    ("market", "ohlcv", "close"): "MKT_close",
    ("market", "ohlcv", "volume"): "MKT_volume",
    ("analytics", "valuation_pe", "pe"): "VAL_market_pe",
    ("analytics", "valuation_pb", "pb"): "VAL_market_pb",
    ("fundamental", "ratio", "pe"): "VAL_stock_pe",
    ("fundamental", "ratio", "pb"): "VAL_stock_pb",
    ("fundamental", "ratio", "eps"): "VAL_stock_eps",
    ("fundamental", "note_llm", "llm_risk_score"): "FUN_LLM_risk_score",
    ("fundamental", "note_llm", "llm_growth_score"): "FUN_LLM_growth_score",
}


@dataclass(frozen=True)
class PipelineConfig:
    symbol: str = "TCB"
    index_symbol: str = "VNINDEX"
    length: str = "5Y"
    start: Optional[str] = None
    end: Optional[str] = None
    financial_lag_days: int = 20
    macro_monthly_lag_days: int = 7
    macro_quarterly_lag_days: int = 20
    macro_yearly_lag_days: int = 30
    analytics_duration: str = "5Y"
    seq_length: int = 20
    train_ratio: float = 0.80
    insights_limit: int = 5000
    include_current_snapshots: bool = True
    include_categorical_hash: bool = True
    min_numeric_non_null: int = 1
    log_level: int = logging.INFO


@dataclass
class TensorBundle:
    X_train: np.ndarray
    y_train: np.ndarray
    X_valid: np.ndarray
    y_valid: np.ndarray
    feature_columns: List[str]
    target_column: str
    sample_dates_train: pd.DatetimeIndex
    sample_dates_valid: pd.DatetimeIndex
    x_scaler: MinMaxScaler
    y_scaler: MinMaxScaler
    imputation_values: Dict[str, float]


@dataclass
class FeatureAuditRecord:
    feature: str
    prefix: str
    source_type: str
    dataset: str
    original_column: str
    temporal_mode: str
    fill_policy: str
    impact_comment: str
    route_reason: str
    encoded_as_hash: bool = False


class VnstockMasterMatrixPipeline:
    """
    Schema-agnostic, leak-safe daily master-matrix builder for vnstock_data.

    Core properties:
    - Base calendar is the real trading calendar from Market().equity(symbol).ohlcv().
    - Fundamental and periodic macro data are shifted to released_at before merge_asof.
    - Dynamic Feature Router scans every non-system column of every returned DataFrame.
    - Current-only snapshots are attached only to the most recent base date; never backfilled.
    - Tensor preparation fits imputers and scalers only on the chronological training split.
    """

    def __init__(
        self,
        config: PipelineConfig,
        market_client: Any = None,
        fundamental_client: Any = None,
        insights_client: Any = None,
        macro_client: Any = None,
        analytics_client: Any = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(config.log_level)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            self.logger.addHandler(handler)

        if market_client is None and Market is None:
            raise ImportError("vnstock_data.Market is required. Activate the vnstock_data environment first.")
        if fundamental_client is None and Fundamental is None:
            raise ImportError("vnstock_data.Fundamental is required. Activate the vnstock_data environment first.")

        self.market = market_client if market_client is not None else Market()
        self.fundamental = fundamental_client if fundamental_client is not None else Fundamental()
        self.insights = insights_client if insights_client is not None else (Insights() if Insights is not None else None)
        self.macro = macro_client if macro_client is not None else (Macro() if Macro is not None else None)
        self.analytics = analytics_client if analytics_client is not None else (Analytics() if Analytics is not None else None)

        self._cache: Dict[str, Any] = {}
        self.feature_catalog_: Dict[str, FeatureAuditRecord] = {}
        self.excluded_columns_: List[Tuple[str, str, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_master_matrix(self) -> pd.DataFrame:
        market_df = self._build_market_features()
        if market_df.empty or "MKT_close" not in market_df.columns:
            raise ValueError("Market OHLCV is empty or missing MKT_close; cannot build base trading calendar.")

        base_index = pd.DatetimeIndex(market_df.index).sort_values()
        frames = [
            market_df,
            self._build_flow_features(base_index),
            self._build_technical_features(market_df),
            self._build_insights_features(base_index),
            self._build_analytics_features(base_index),
            self._build_fundamental_features(base_index),
            self._build_macro_features(base_index),
            self._build_commodity_features(base_index),
        ]
        master = self._concat_feature_frames(base_index, frames)
        master = self._finalize_master(master)
        return master

    def get_feature_catalog(self) -> pd.DataFrame:
        """Return one audit row per generated feature, including the price-impact comment."""
        if not self.feature_catalog_:
            return pd.DataFrame(
                columns=[
                    "feature",
                    "prefix",
                    "source_type",
                    "dataset",
                    "original_column",
                    "temporal_mode",
                    "fill_policy",
                    "impact_comment",
                    "route_reason",
                    "encoded_as_hash",
                ]
            )
        return pd.DataFrame([record.__dict__ for record in self.feature_catalog_.values()]).sort_values(
            ["prefix", "source_type", "dataset", "feature"]
        )

    def assert_feature_contract(self, master: pd.DataFrame) -> None:
        orphan_cols = [c for c in master.columns if not c.startswith(ALLOWED_PREFIXES)]
        if orphan_cols:
            raise ValueError(f"Found orphan feature columns without allowed prefix: {orphan_cols}")
        missing_catalog = [c for c in master.columns if c not in self.feature_catalog_]
        if missing_catalog:
            raise ValueError(f"Features missing audit records: {missing_catalog}")
        bad_prefix = [c for c in master.columns if c.split("_", 1)[0] + "_" not in ALLOWED_PREFIXES]
        if bad_prefix:
            raise ValueError(f"Unexpected feature prefix: {bad_prefix}")

    def build_tensor_bundle(
        self,
        master: pd.DataFrame,
        seq_length: Optional[int] = None,
        train_ratio: Optional[float] = None,
    ) -> TensorBundle:
        seq = seq_length or self.config.seq_length
        ratio = self.config.train_ratio if train_ratio is None else train_ratio
        if seq < 2:
            raise ValueError("seq_length must be >= 2.")
        if not 0.5 <= ratio < 1.0:
            raise ValueError("train_ratio must be in [0.5, 1.0).")

        df = master.copy().sort_index().replace([np.inf, -np.inf], np.nan)
        target_col = "TARGET_return_t+1"

        # Trong Quant, chúng ta luôn dự báo Lợi suất (Return) thay vì Giá. Hãy đổi Target thành % thay đổi của ngày mai. Khi cần tính giá thật, bạn chỉ lấy giá hôm nay nhân với (1 + Return)
        df[target_col] = df["MKT_close"].shift(-1) / df["MKT_close"].replace(0, np.nan) - 1.0

        feature_cols = [c for c in df.columns if c.startswith(ALLOWED_PREFIXES)]
        if not feature_cols:
            raise ValueError("No routed feature columns found.")

        work = df[feature_cols + [target_col]].dropna(subset=[target_col])
        if len(work) < seq + 5:
            raise ValueError(f"Not enough observations before cleaning. Need at least {seq + 5}, got {len(work)}.")

        split_row = int(math.floor(len(work) * ratio))
        split_row = max(seq, min(split_row, len(work) - 1))

        X_raw = work[feature_cols].copy()
        X_raw = self._forward_fill_sticky_features(X_raw)

        train_raw = X_raw.iloc[:split_row]
        impute_values = self._fit_imputation_values(train_raw, feature_cols)
        X_imputed = self._apply_imputation_values(X_raw, impute_values)
        y_raw = work[[target_col]].astype(float)

        if X_imputed.isna().any().any():
            missing = X_imputed.columns[X_imputed.isna().any()].tolist()
            raise ValueError(f"NaN remains after imputation: {missing[:20]}")

        x_scaler = MinMaxScaler()
        y_scaler = MinMaxScaler()
        x_scaler.fit(X_imputed.iloc[:split_row][feature_cols])
        y_scaler.fit(y_raw.iloc[:split_row])

        X_scaled = x_scaler.transform(X_imputed[feature_cols]).astype(np.float32)
        y_scaled = y_scaler.transform(y_raw).astype(np.float32).reshape(-1)

        X_seq: List[np.ndarray] = []
        y_seq: List[float] = []
        sample_dates: List[pd.Timestamp] = []
        sample_target_rows: List[int] = []
        for i in range(seq - 1, len(work)):
            X_seq.append(X_scaled[i - seq + 1 : i + 1])
            y_seq.append(float(y_scaled[i]))
            sample_dates.append(pd.Timestamp(work.index[i]))
            sample_target_rows.append(i)

        X_all = np.stack(X_seq).astype(np.float32)
        y_all = np.asarray(y_seq, dtype=np.float32)
        sample_dates_idx = pd.DatetimeIndex(sample_dates)
        sample_rows = np.asarray(sample_target_rows)
        train_mask = sample_rows < split_row

        return TensorBundle(
            X_train=X_all[train_mask],
            y_train=y_all[train_mask],
            X_valid=X_all[~train_mask],
            y_valid=y_all[~train_mask],
            feature_columns=feature_cols,
            target_column=target_col,
            sample_dates_train=sample_dates_idx[train_mask],
            sample_dates_valid=sample_dates_idx[~train_mask],
            x_scaler=x_scaler,
            y_scaler=y_scaler,
            imputation_values=impute_values,
        )

    # ------------------------------------------------------------------
    # Dynamic Feature Router
    # ------------------------------------------------------------------
    def auto_prefix_dataframe(
        self,
        df: pd.DataFrame,
        source_type: str,
        dataset_name: str,
        temporal_mode: str,
    ) -> pd.DataFrame:
        """
        Route 100% non-system columns to the 7 allowed feature groups.

        Unmatched columns are not dropped and are not named OTHER_/UNKNOWN_. They
        receive the default prefix of source_type, e.g. source_type="fundamental"
        -> FUN_raw_<column>. This preserves full schema coverage while enforcing
        the 7-prefix contract.
        """
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame(index=getattr(df, "index", None))

        data = self._flatten_columns(df.copy())
        out = pd.DataFrame(index=data.index)
        source_key = self._snake_case(source_type)
        dataset_key = self._snake_case(dataset_name)

        for i, original_col in enumerate(data.columns):
            col_key = self._snake_case(str(original_col))
            if self._is_system_column(col_key):
                self.excluded_columns_.append((source_key, dataset_key, col_key))
                continue

            route = self._route_column(col_key, source_key, dataset_key)
            feature_name = self._make_feature_name(source_key, dataset_key, col_key, route.prefix)
            
            # SỬA Ở ĐÂY: Thay data[original_col] bằng data.iloc[:, i]
            numeric_series, encoded_as_hash = self._coerce_feature_series(data.iloc[:, i])
            
            if numeric_series is None:
                self.excluded_columns_.append((source_key, dataset_key, col_key))
                continue

            unique_name = self._deduplicate_feature_name(feature_name, out.columns)
            out[unique_name] = numeric_series.to_numpy(dtype=float)
            self._register_feature(
                feature=unique_name,
                prefix=route.prefix,
                source_type=source_key,
                dataset=dataset_key,
                original_column=col_key,
                temporal_mode=temporal_mode,
                fill_policy=self._infer_fill_policy(unique_name, route.fill_policy),
                impact_comment=route.impact,
                route_reason="keyword" if any(kw in col_key for kw in route.keywords) else "source_type_fallback",
                encoded_as_hash=encoded_as_hash,
            )
        return out

    def _route_column(self, col_key: str, source_type: str, dataset_name: str) -> FeatureRoute:
        default_prefix = SOURCE_DEFAULT_PREFIX.get(dataset_name) or SOURCE_DEFAULT_PREFIX.get(source_type) or "INS_"
        allowed_prefixes_by_source: Mapping[str, Tuple[str, ...]] = {
            "market": ("FLOW_", "MKT_"),
            "ohlcv": ("MKT_",),
            "order_book": ("MKT_",),
            "price_depth": ("MKT_",),
            "quote": ("MKT_",),
            "flow": ("FLOW_", "MKT_"),
            "foreign_flow": ("FLOW_",),
            "proprietary_flow": ("FLOW_",),
            "trade_history": ("FLOW_", "MKT_"),
            "technical": ("INS_",),
            "analytics": ("VAL_",),
            "valuation": ("VAL_",),
            "fundamental": ("VAL_", "FUN_"),
            "ratio": ("VAL_", "FUN_"),
            "financial": ("VAL_", "FUN_"),
            "macro": ("MAC_",),
            "economy": ("MAC_",),
            "currency": ("MAC_",),
            "commodity": ("CMD_",),
        }
        allowed = allowed_prefixes_by_source.get(source_type) or allowed_prefixes_by_source.get(dataset_name)
        if allowed is None and source_type == "insights":
            allowed = ALLOWED_PREFIXES
        if allowed is None:
            allowed = (default_prefix,)

        for route in FEATURE_ROUTING_MAP:
            if route.prefix not in allowed:
                continue
            if any(keyword in col_key for keyword in route.keywords):
                return route
        prefix = default_prefix if default_prefix in allowed else allowed[0]
        return FeatureRoute(
            prefix=prefix,
            keywords=(),
            fill_policy=PREFIX_DEFAULT_FILL[prefix],
            impact=PREFIX_DEFAULT_IMPACT[prefix],
        )

    def _make_feature_name(self, source_type: str, dataset_name: str, col_key: str, prefix: str) -> str:
        # BỎ QUA CANONICAL_ALIASES vì nó có thể đang lưu rác (như MKT_ohlcv_close)
        clean_key = col_key
        prefix_lower = prefix.lower()
        
        # Xóa tiền tố gốc nếu bị trùng (Ví dụ: tránh MKT_mkt_close)
        if clean_key.startswith(prefix_lower):
            clean_key = clean_key[len(prefix_lower):]
            
        # Trả về chuẩn xác (Ví dụ: MKT_close)
        return f"{prefix}{clean_key}"
            
        # Xóa tiền tố gốc nếu bị trùng (Ví dụ: tránh MKT_mkt_close)
        clean_key = col_key
        prefix_lower = prefix.lower()
        if clean_key.startswith(prefix_lower):
            clean_key = clean_key[len(prefix_lower):]
            
        # BỎ dataset_name: Tên cột sẽ là MKT_close thay vì MKT_ohlcv_close
        return f"{prefix}{clean_key}"

    def _deduplicate_feature_name(self, feature_name: str, existing_columns: Iterable[str]) -> str:
        if feature_name not in existing_columns and feature_name not in self.feature_catalog_:
            return feature_name
        i = 2
        while f"{feature_name}__{i}" in existing_columns or f"{feature_name}__{i}" in self.feature_catalog_:
            i += 1
        return f"{feature_name}__{i}"

    def _register_feature(
        self,
        feature: str,
        prefix: str,
        source_type: str,
        dataset: str,
        original_column: str,
        temporal_mode: str,
        fill_policy: str,
        impact_comment: str,
        route_reason: str,
        encoded_as_hash: bool = False,
    ) -> None:
        self.feature_catalog_[feature] = FeatureAuditRecord(
            feature=feature,
            prefix=prefix,
            source_type=source_type,
            dataset=dataset,
            original_column=original_column,
            temporal_mode=temporal_mode,
            fill_policy=fill_policy,
            impact_comment=impact_comment,
            route_reason=route_reason,
            encoded_as_hash=encoded_as_hash,
        )

    # ------------------------------------------------------------------
    # Layer builders
    # ------------------------------------------------------------------
    def _build_market_features(self) -> pd.DataFrame:
        print(f"[*] Đang tải Market Data (OHLCV) cho {self.config.symbol}...")
        
        # 1. Gọi API an toàn (Hỗ trợ cả ohlcv mới và history cũ của vnstock)
        try:
            ohlcv_raw = self.market.equity(self.config.symbol).ohlcv(length=self.config.length)
        except AttributeError:
            ohlcv_raw = self.market.equity(self.config.symbol).history(length=self.config.length)
            
        # Kiểm tra dữ liệu rỗng trước khi xử lý
        if ohlcv_raw is None or ohlcv_raw.empty:
            raise ValueError(f"❌ API vnstock trả về dữ liệu rỗng cho mã {self.config.symbol}.")
            
        # Lấy cột ngày tháng
        date_series = self._extract_date_series(ohlcv_raw)
        
        # 2. Đưa qua Router tự động gán Prefix
        df = self.auto_prefix_dataframe(ohlcv_raw, "market", "ohlcv", "daily")
        
        if date_series is not None:
            df = df.set_index(date_series)
            
        # =========================================================
        # 3. CHỐT CHẶN AN TOÀN (FAILSAFE) CHO CỘT TARGET MKT_close
        # =========================================================
        if "MKT_close" not in df.columns:
            # Nếu Router lỡ bỏ sót hoặc đặt tên sai, ta ép kiểu và bốc thẳng từ raw data sang
            if "close" in ohlcv_raw.columns:
                # Dùng .values để đảm bảo không bị lệch Index
                df["MKT_close"] = pd.to_numeric(ohlcv_raw["close"].values, errors="coerce")
            else:
                # Nếu raw data thực sự mất cột close, in ra danh sách cột để debug
                raise ValueError(f"❌ OHLCV Raw Data không có cột 'close'. Cột hiện có: {list(ohlcv_raw.columns)}")
                
        return df

    def _derive_market_microstructure_features(self, market_df: pd.DataFrame) -> pd.DataFrame:
        close = market_df["MKT_close"].astype(float)
        high = market_df.get("MKT_high", close).astype(float)
        low = market_df.get("MKT_low", close).astype(float)
        volume = market_df.get("MKT_volume", pd.Series(np.nan, index=market_df.index)).astype(float)

        raw = pd.DataFrame(index=market_df.index)
        # MKT_return_1d: Lợi suất ngày đo xung lực cung-cầu vừa hình thành, dùng để dự báo phản ứng ngày kế tiếp.
        raw["return_1d"] = close.pct_change()
        # MKT_range_pct: Biên độ trong ngày càng lớn càng cho thấy tranh chấp cung-cầu và rủi ro biến động cao.
        raw["range_pct"] = (high - low) / close.replace(0, np.nan)
        vol_mean = volume.rolling(20, min_periods=5).mean()
        vol_std = volume.rolling(20, min_periods=5).std().replace(0, np.nan)
        # MKT_volume_z20: Volume bất thường so với 20 phiên thường đi trước thay đổi kỳ vọng giá.
        raw["volume_z20"] = (volume - vol_mean) / vol_std
        # MKT_dollar_value_proxy: Giá trị giao dịch proxy đo sức mua bằng tiền, không chỉ bằng số cổ phiếu.
        raw["dollar_value_proxy"] = close * volume
        return self.auto_prefix_dataframe(raw, "market", "derived", "derived")

    def _build_flow_features(self, base_index: pd.DatetimeIndex) -> pd.DataFrame:
        eq = self._equity_client(self.market, self.config.symbol)
        frames: List[pd.DataFrame] = []
        for method_name in ("foreign_flow", "proprietary_flow", "trade_history"):
            raw = self._safe_call(
                f"market.equity.{method_name}",
                lambda name=method_name: self._call_noarg_method(eq, name),
                required=False,
            )
            frames.append(self._daily_exact_features(raw, "flow", method_name, base_index))
        return self._concat_feature_frames(base_index, frames)

    def _build_technical_features(self, market_df: pd.DataFrame) -> pd.DataFrame:
        close = market_df["MKT_close"].astype(float)
        ret = close.pct_change()
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        ma20 = close.rolling(20, min_periods=5).mean()
        ma50 = close.rolling(50, min_periods=10).mean()

        index_close = self._fetch_index_close(market_df.index)
        stock_norm = close / close.dropna().iloc[0]
        index_norm = index_close / index_close.dropna().iloc[0] if index_close.notna().any() else pd.Series(1.0, index=close.index)

        ret_20d_stock = close / close.shift(20) - 1.0
        ret_20d_index = index_close / index_close.shift(20) - 1.0

        raw = pd.DataFrame(index=market_df.index)
        # INS_rsi14: RSI cao thể hiện cầu áp đảo, RSI quá cao cũng cảnh báo vùng mua đuổi dễ đảo chiều.
        raw["rsi14"] = 100 - (100 / (1 + rs))

        # INS_macd: MACD dương cho thấy xu hướng giá đang được lực cầu kéo lên so với trung bình dài hơn.
        raw["macd"] = macd

        # INS_macd_signal: Signal làm mượt MACD để nhận biết lực mua đang tăng tốc hay suy yếu.
        raw["macd_signal"] = macd_signal

        # INS_macd_hist: Histogram mở rộng thường báo hiệu xung lượng cầu đang gia tăng.
        raw["macd_hist"] = macd - macd_signal

        # INS_rs_vs_index: Sức mạnh tương đối vượt chỉ số cho thấy dòng tiền đang ưu tiên mã này hơn thị trường.
        raw["rs_vs_index"] = stock_norm / index_norm.replace(0, np.nan)

        # INS_rs_vs_index_20d: Hiệu suất vượt trội (Alpha) của cổ phiếu so với TT chung trong 1 tháng
        raw["rs_vs_index_20d"] = ret_20d_stock - ret_20d_index

        # INS_trend_ma20_50: MA20 cao hơn MA50 xác nhận xu hướng tăng và tâm lý nắm giữ tốt hơn.
        raw["trend_ma20_50"] = (ma20 / ma50.replace(0, np.nan)) - 1.0

        # INS_volatility20: Biến động cao làm tăng risk premium và có thể ép giảm bội số định giá hợp lý.
        raw["volatility20"] = ret.rolling(20, min_periods=5).std() * math.sqrt(252)

        return self.auto_prefix_dataframe(raw, "technical", "derived", "derived")

    def _build_insights_features(self, base_index: pd.DatetimeIndex) -> pd.DataFrame:
        if self.insights is None:
            return pd.DataFrame(index=base_index)

        frames: List[pd.DataFrame] = []
        screener = self._resolve_domain(self.insights, "screener")
        if screener is not None:
            raw = self._safe_call("insights.screener.filter", lambda: self._call_screener_filter(screener), required=False)
            filtered = self._filter_symbol_rows(raw, self.config.symbol)
            frames.append(self._snapshot_latest_features(filtered, "insights", "screener", base_index))

        ranking = self._resolve_domain(self.insights, "ranking")
        if ranking is not None:
            for method_name in ("gainer", "loser", "value", "volume", "foreign_buy", "foreign_sell", "deal"):
                raw = self._safe_call(
                    f"insights.ranking.{method_name}",
                    lambda name=method_name: self._call_optional_kwargs(getattr(ranking, name), index=self.config.index_symbol, limit=500),
                    required=False,
                )
                filtered = self._filter_symbol_rows(raw, self.config.symbol)
                if isinstance(filtered, pd.DataFrame) and not filtered.empty:
                    filtered = filtered.copy()
                    # INS_rank_position: Vị trí trong ranking thể hiện mức độ được thị trường chú ý, có thể kéo dòng tiền ngắn hạn.
                    filtered["rank_position"] = np.arange(1, len(filtered) + 1)
                frames.append(self._snapshot_latest_features(filtered, "insights", f"ranking_{method_name}", base_index))

        return self._concat_feature_frames(base_index, frames)

    def _build_analytics_features(self, base_index: pd.DatetimeIndex) -> pd.DataFrame:
        if self.analytics is None:
            return pd.DataFrame(index=base_index)
        valuation = self._valuation_client(self.analytics, self.config.index_symbol)
        if valuation is None:
            return pd.DataFrame(index=base_index)

        frames: List[pd.DataFrame] = []
        methods = {
            "valuation_pe": lambda: valuation.pe(duration=self.config.analytics_duration),
            "valuation_pb": lambda: valuation.pb(duration=self.config.analytics_duration),
            "valuation_evaluation": lambda: valuation.evaluation(duration=self.config.analytics_duration),
        }
        for dataset_name, fn in methods.items():
            raw = self._safe_call(f"analytics.{dataset_name}", fn, required=False)
            frames.append(self._event_asof_features(raw, "analytics", dataset_name, base_index, lag_days=0))
        return self._concat_feature_frames(base_index, frames)

    def _build_fundamental_features(self, base_index: pd.DatetimeIndex) -> pd.DataFrame:
        eq = self._equity_client(self.fundamental, self.config.symbol)
        frames: List[pd.DataFrame] = []

        method_specs: Tuple[Tuple[str, Callable[[], Any]], ...] = (
            ("income_statement", lambda: self._call_period_method(eq, "income_statement", period="quarter")),
            ("balance_sheet", lambda: self._call_period_method(eq, "balance_sheet", period="quarter")),
            ("cash_flow", lambda: self._call_period_method(eq, "cash_flow", period="quarter")),
            ("ratio", lambda: self._call_period_method(eq, "ratio", period="quarter")),
            ("financial_health", lambda: self._call_optional_kwargs(getattr(eq, "financial_health"), scorecard="auto", limit=40)),
        )
        for dataset_name, fn in method_specs:
            raw = self._safe_call(f"fundamental.{dataset_name}", fn, required=False)
            frames.append(
                self._event_asof_features(
                    raw,
                    "fundamental" if dataset_name != "ratio" else "ratio",
                    dataset_name,
                    base_index,
                    lag_days=self.config.financial_lag_days,
                )
            )

        notes = self._build_llm_note_scores(eq)
        frames.append(self._event_asof_features(notes, "fundamental", "note_llm", base_index, lag_days=0))
        return self._concat_feature_frames(base_index, frames)

    def _build_llm_note_scores(self, equity_obj: Any) -> pd.DataFrame:
        note_raw = self._safe_call(
            "fundamental.note.quarter",
            lambda: self._call_period_method(equity_obj, "note", period="quarter", lang="vi"),
            required=False,
        )
        if note_raw is None or not isinstance(note_raw, pd.DataFrame) or note_raw.empty:
            note_raw = self._safe_call(
                "fundamental.note.year",
                lambda: self._call_period_method(equity_obj, "note", period="year", lang="vi"),
                required=False,
            )
        events = self._infer_event_frame(note_raw, lag_days=self.config.financial_lag_days)
        if events.empty:
            return pd.DataFrame()

        rows: List[Dict[str, Any]] = []
        for _, row in events.iterrows():
            payload = row.drop(labels=["released_at", "period_end", "event_date"], errors="ignore").to_dict()
            raw_scores = self._mock_local_llm_read_notes(payload)
            rows.append(
                {
                    "released_at": row["released_at"],
                    # FUN_LLM_risk_score: Rủi ro tín dụng cao làm tăng discount rate và gây áp lực lên giá trị nội tại.
                    "LLM_risk_score": raw_scores["LLM_risk_score"],
                    # FUN_LLM_growth_score: Tiềm năng tăng trưởng cao hỗ trợ kỳ vọng lợi nhuận và mở rộng định giá.
                    "LLM_growth_score": raw_scores["LLM_growth_score"],
                }
            )
        return pd.DataFrame(rows).sort_values("released_at")

    def _mock_local_llm_read_notes(self, note_payload: Mapping[str, Any]) -> Dict[str, float]:
        """
        Mock Local LLM contract for financial-statement notes JSON.

        Replace this method with an internal Ollama/vLLM/llama.cpp endpoint in
        production. Do not expand raw notes into hundreds of sparse columns.
        """
        text = json.dumps(note_payload, ensure_ascii=False).lower()
        risk = 5.0
        growth = 5.0
        risk_terms = (
            "bad debt",
            "nợ xấu",
            "substandard",
            "doubtful",
            "loss",
            "provision",
            "overdue",
            "vamc",
            "litigation",
            "tranh chấp",
            "dự phòng",
        )
        growth_terms = (
            "digital",
            "retail",
            "fee income",
            "growth",
            "increase",
            "mở rộng",
            "tăng trưởng",
            "dịch vụ",
            "khách hàng mới",
        )
        negative_growth_terms = ("decline", "decrease", "loss", "giảm", "suy giảm", "lỗ")
        risk += min(4.0, sum(0.4 for term in risk_terms if term in text))
        growth += min(3.5, sum(0.35 for term in growth_terms if term in text))
        growth -= min(2.5, sum(0.3 for term in negative_growth_terms if term in text))
        return {
            "LLM_risk_score": float(np.clip(risk, 1.0, 10.0)),
            "LLM_growth_score": float(np.clip(growth, 1.0, 10.0)),
        }

    def _build_macro_features(self, base_index: pd.DatetimeIndex) -> pd.DataFrame:
        print("[*] Đang tải Macro Data...")
        eco = self.macro.economy()
        
        # Định nghĩa các phương thức đã xác nhận hoạt động
        eco_methods = {
            'MAC_gdp': lambda: eco.gdp(period="quarter", length=4),
            'MAC_cpi': lambda: eco.cpi(period="month", length=12),
            'MAC_industry': lambda: eco.industry_prod(period="month", length=3),
            'MAC_import_export': lambda: eco.import_export(period="month", length=3),
            'MAC_retail': lambda: eco.retail(period="month", length=3),
            'MAC_fdi': lambda: eco.fdi(period="month", length=3),
            'MAC_money': lambda: eco.money_supply(period="month", length=3),
            'MAC_labor': lambda: eco.population_labor(period="year", length=3)
        }
        
        all_dfs = []
        for name, func in eco_methods.items():
            try:
                df = func()
                if df is not None and not df.empty:
                    # Rename cột value thành tên prefix
                    if 'value' in df.columns:
                        df = df.rename(columns={'value': name})
                    all_dfs.append(df)
            except Exception as e:
                print(f"⚠️ Bỏ qua {name} do lỗi: {e}")
                continue
                
        # Merge tất cả lại
        if not all_dfs:
            return pd.DataFrame(index=base_index)
            
        final_macro = pd.concat(all_dfs, axis=1)
        return self._align_daily(base_index, final_macro, final_macro.columns)

    def _build_commodity_features(self, base_index: pd.DatetimeIndex) -> pd.DataFrame:
        if self.macro is None:
            return pd.DataFrame(index=base_index)
        commodity = self._resolve_domain(self.macro, "commodity")
        if commodity is None:
            return pd.DataFrame(index=base_index)

        specs: Tuple[Tuple[str, Callable[[], Any]], ...] = (
            ("gold_vn", lambda: self._call_optional_kwargs(getattr(commodity, "gold"), market="VN")),
            ("gold_global", lambda: self._call_optional_kwargs(getattr(commodity, "gold"), market="GLOBAL")),
            ("gas_vn", lambda: self._call_optional_kwargs(getattr(commodity, "gas"), market="VN")),
            ("oil_crude", lambda: self._call_noarg_method(commodity, "oil_crude")),
            ("coke", lambda: self._call_noarg_method(commodity, "coke")),
            ("steel_vn", lambda: self._call_optional_kwargs(getattr(commodity, "steel"), market="VN")),
            ("iron_ore", lambda: self._call_noarg_method(commodity, "iron_ore")),
            ("fertilizer_ure", lambda: self._call_noarg_method(commodity, "fertilizer_ure")),
            ("soybean", lambda: self._call_noarg_method(commodity, "soybean")),
            ("corn", lambda: self._call_noarg_method(commodity, "corn")),
            ("sugar", lambda: self._call_noarg_method(commodity, "sugar")),
            ("pork_vn", lambda: self._call_optional_kwargs(getattr(commodity, "pork"), market="VN")),
        )
        frames: List[pd.DataFrame] = []
        for dataset_name, fn in specs:
            raw = self._safe_call(f"macro.commodity.{dataset_name}", fn, required=False)
            frames.append(self._event_asof_features(raw, "commodity", dataset_name, base_index, lag_days=0))
        return self._concat_feature_frames(base_index, frames)

    # ------------------------------------------------------------------
    # Time alignment helpers
    # ------------------------------------------------------------------
    def _daily_exact_features(
        self,
        raw: Any,
        source_type: str,
        dataset_name: str,
        base_index: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
            return pd.DataFrame(index=base_index)
        data = self._normalize_date_index(raw)
        if data.empty:
            return pd.DataFrame(index=base_index)
        routed = self.auto_prefix_dataframe(data, source_type, dataset_name, "daily_exact")
        return routed.reindex(base_index)

    def get_latest_inference_tensor(self, master: pd.DataFrame, bundle: TensorBundle) -> np.ndarray:
        """Trích xuất mảng 2D (seq_length, features) của ngày giao dịch cuối cùng để dự báo"""
        seq = self.config.seq_length
        if len(master) < seq:
            raise ValueError("Không đủ data để tạo sequence dự báo.")

        # Lấy seq_length dòng cuối cùng
        latest_window = master[bundle.feature_columns].tail(seq).copy()

        # Fill NaN bằng imputer của tập Train
        latest_imputed = self._apply_imputation_values(latest_window, bundle.imputation_values)

        # Scale bằng X_scaler đã fit
        X_scaled = bundle.x_scaler.transform(latest_imputed).astype(np.float32)

        # Reshape thành (1, seq_length, features) sẵn sàng feed vào model.predict()
        return np.expand_dims(X_scaled, axis=0)

    def _event_asof_features(
        self,
        raw: Any,
        source_type: str,
        dataset_name: str,
        base_index: pd.DatetimeIndex,
        lag_days: int,
    ) -> pd.DataFrame:
        if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
            return pd.DataFrame(index=base_index)
        events = self._infer_event_frame(raw, lag_days=lag_days)
        if events.empty:
            return pd.DataFrame(index=base_index)
        routed = self.auto_prefix_dataframe(events, source_type, dataset_name, "event_asof")
        if routed.empty:
            return pd.DataFrame(index=base_index)
        routed["released_at"] = events["released_at"].values
        return self._merge_asof_features(base_index, routed)

    def _snapshot_latest_features(
        self,
        raw: Any,
        source_type: str,
        dataset_name: str,
        base_index: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty or not self.config.include_current_snapshots:
            return pd.DataFrame(index=base_index)
        data = raw.copy()
        data = self._filter_symbol_rows(data, self.config.symbol)
        if data.empty:
            return pd.DataFrame(index=base_index)
        row_df = data.tail(1).reset_index(drop=True)
        routed = self.auto_prefix_dataframe(row_df, source_type, dataset_name, "snapshot_latest_only")
        out = pd.DataFrame(index=base_index, columns=routed.columns, dtype=float)
        if not routed.empty:
            # Snapshot features are assigned only to the most recent available trading date to avoid historical leakage.
            out.loc[base_index[-1], routed.columns] = routed.iloc[-1].astype(float).values
        return out

    def _infer_event_frame(self, raw: Any, lag_days: int) -> pd.DataFrame:
        if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
            return pd.DataFrame()
        data = self._flatten_columns(raw.copy())
        data.columns = [self._snake_case(str(c)) for c in data.columns]

        if "period" in data.columns:
            event_date = data["period"].apply(self._period_to_end_date)
        elif "period_end" in data.columns:
            event_date = pd.to_datetime(data["period_end"], errors="coerce")
        else:
            event_date = self._extract_date_series(data)

        if event_date is None:
            return pd.DataFrame()

        data["event_date"] = pd.to_datetime(event_date, errors="coerce").dt.normalize()
        data = data.dropna(subset=["event_date"])
        if data.empty:
            return pd.DataFrame()
        if "released_at" in data.columns and pd.to_datetime(data["released_at"], errors="coerce").notna().any():
            released = pd.to_datetime(data["released_at"], errors="coerce").dt.normalize()
        else:
            released = data["event_date"] + pd.to_timedelta(lag_days, unit="D")
        data["released_at"] = pd.to_datetime(released, errors="coerce").dt.normalize()
        data = data.dropna(subset=["released_at"]).sort_values("released_at")
        data = data.drop_duplicates("released_at", keep="last")
        return data

    def _merge_asof_features(self, base_index: pd.DatetimeIndex, event_features: pd.DataFrame) -> pd.DataFrame:
        feature_cols = [c for c in event_features.columns if c.startswith(ALLOWED_PREFIXES)]
        if not feature_cols:
            return pd.DataFrame(index=base_index)
        left = pd.DataFrame({"date": pd.DatetimeIndex(base_index).sort_values()})
        right = event_features[["released_at"] + feature_cols].copy()
        right["released_at"] = pd.to_datetime(right["released_at"], errors="coerce").dt.normalize()
        right = right.dropna(subset=["released_at"]).sort_values("released_at")
        for c in feature_cols:
            right[c] = self._to_numeric(right[c])
        merged = pd.merge_asof(left, right, left_on="date", right_on="released_at", direction="backward")
        merged = merged.set_index("date")
        return merged[feature_cols].reindex(base_index)

    # ------------------------------------------------------------------
    # API compatibility helpers
    # ------------------------------------------------------------------
    def _equity_client(self, root: Any, symbol: str) -> Any:
        equity_attr = getattr(root, "equity", None)
        if equity_attr is None:
            raise AttributeError(f"{root!r} has no equity attribute")
        if callable(equity_attr):
            try:
                return equity_attr(symbol)
            except TypeError:
                return equity_attr
        return equity_attr

    def _valuation_client(self, analytics_root: Any, index_symbol: str) -> Any:
        valuation_attr = getattr(analytics_root, "valuation", None)
        if valuation_attr is None:
            return None
        if callable(valuation_attr):
            for kwargs in ({"index": index_symbol}, {}):
                try:
                    return valuation_attr(index_symbol, **kwargs) if not kwargs else valuation_attr(**kwargs)
                except TypeError:
                    continue
                except Exception:
                    continue
        return valuation_attr

    def _resolve_domain(self, root: Any, name: str) -> Any:
        attr = getattr(root, name, None)
        if attr is None:
            return None
        if callable(attr):
            try:
                return attr()
            except TypeError:
                return attr
            except Exception:
                return attr
        return attr

    def _call_ohlcv(self, asset_obj: Any) -> pd.DataFrame:
        if self.config.start and self.config.end:
            call_patterns = (
                lambda: asset_obj.ohlcv(start=self.config.start, end=self.config.end, interval="1D"),
                lambda: asset_obj.ohlcv(start=self.config.start, end=self.config.end),
            )
            for fn in call_patterns:
                try:
                    return fn()
                except TypeError:
                    continue
                except Exception as exc:
                    self.logger.warning("ohlcv(start/end) failed: %s", exc)
                    break
        return asset_obj.ohlcv(length=self.config.length)

    def _call_period_method(self, obj: Any, method_name: str, **kwargs: Any) -> Any:
        method = getattr(obj, method_name)
        period = kwargs.pop("period", None)
        patterns: List[Dict[str, Any]] = []
        if period is not None:
            if str(period).lower().startswith("q"):
                patterns.extend([{**kwargs, "period": "quarter"}, {**kwargs, "period": "Q"}])
            elif str(period).lower().startswith("y"):
                patterns.extend([{**kwargs, "period": "year"}, {**kwargs, "period": "Y"}])
            else:
                patterns.append({**kwargs, "period": period})
        patterns.append(kwargs)
        return self._call_with_patterns(method, patterns)

    def _call_noarg_method(self, obj: Any, method_name: str) -> Any:
        method = getattr(obj, method_name, None)
        if method is None:
            return pd.DataFrame()
        if callable(method):
            return method()
        return method

    def _call_optional_kwargs(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        patterns = [kwargs]
        for key in list(kwargs):
            reduced = {k: v for k, v in kwargs.items() if k != key}
            if reduced not in patterns:
                patterns.append(reduced)
        patterns.append({})
        return self._call_with_patterns(method, patterns)

    def _call_with_patterns(self, method: Callable[..., Any], patterns: Sequence[Dict[str, Any]]) -> Any:
        last_exc: Optional[Exception] = None
        for kwargs in patterns:
            try:
                return method(**kwargs)
            except TypeError as exc:
                last_exc = exc
                continue
        if last_exc is not None:
            raise last_exc
        return method()

    def _call_screener_filter(self, screener: Any) -> Any:
        method = getattr(screener, "filter", None)
        if method is None:
            return pd.DataFrame()
        patterns = ({"limit": self.config.insights_limit}, {}, {"filters": [], "limit": self.config.insights_limit})
        return self._call_with_patterns(method, patterns)

    def _call_interest_rate(self, currency: Any, base_len: int) -> Any:
        method = getattr(currency, "interest_rate")
        patterns = (
            {"period": "day", "length": max(base_len + 60, 365), "format": "long"},
            {"period": "day", "length": max(base_len + 60, 365)},
            {"length": max(base_len + 60, 365), "format": "long"},
            {"length": max(base_len + 60, 365)},
        )
        return self._call_with_patterns(method, patterns)

    def _safe_call(self, key: str, fn: Callable[[], Any], required: bool = False) -> Any:
        if key in self._cache:
            val = self._cache[key]
            return val.copy() if isinstance(val, pd.DataFrame) else val
        try:
            val = fn()
            self._cache[key] = val.copy() if isinstance(val, pd.DataFrame) else val
            return val
        except Exception as exc:
            if required:
                raise
            self.logger.warning("Optional fetch failed: %s: %s", key, exc)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Data normalization helpers
    # ------------------------------------------------------------------
    def _normalize_date_index(self, raw: Any) -> pd.DataFrame:
        if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
            return pd.DataFrame()
        data = self._flatten_columns(raw.copy())
        data.columns = [self._snake_case(str(c)) for c in data.columns]
        date_series = self._extract_date_series(data)
        if date_series is None:
            return pd.DataFrame()
        data["__date"] = pd.to_datetime(date_series, errors="coerce").dt.normalize()
        data = data.dropna(subset=["__date"]).sort_values("__date")
        data = data.drop_duplicates("__date", keep="last").set_index("__date")
        data.index.name = "date"
        return data

    def _extract_date_series(self, data: pd.DataFrame) -> Optional[pd.Series]:
        # Lưu index (i) thay vì giữ tên cột để tránh trùng lặp
        lower_map = {self._snake_case(str(c)): i for i, c in enumerate(data.columns)}
        for candidate in DATE_CANDIDATES:
            key = self._snake_case(candidate)
            if key in lower_map:
                col_idx = lower_map[key]
                # Gọi bằng iloc để lấy đúng 1 Series
                return pd.to_datetime(data.iloc[:, col_idx].apply(self._maybe_period_end), errors="coerce")
        if isinstance(data.index, pd.DatetimeIndex):
            return pd.Series(data.index, index=data.index)
        return None

    def _filter_symbol_rows(self, raw: Any, symbol: str) -> pd.DataFrame:
        if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
            return pd.DataFrame()
        data = self._flatten_columns(raw.copy())
        data.columns = [self._snake_case(str(c)) for c in data.columns]
        symbol_upper = symbol.upper()
        symbol_cols = [c for c in ("symbol", "ticker", "code", "stock_code") if c in data.columns]
        if not symbol_cols:
            return data
        mask = pd.Series(False, index=data.index)
        for col in symbol_cols:
            series = data[col]
            # SỬA Ở ĐÂY: Nếu trùng tên tạo ra DataFrame, chỉ lấy cột đầu tiên
            if isinstance(series, pd.DataFrame):
                series = series.iloc[:, 0]
            mask = mask | series.astype(str).str.upper().eq(symbol_upper)
        return data.loc[mask].copy()

    @staticmethod
    def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = ["_".join(str(part) for part in tup if str(part) != "") for tup in df.columns]
        return df

    @staticmethod
    def _snake_case(value: str) -> str:
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value))
        text = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
        text = re.sub(r"_+", "_", text)
        return text

    @staticmethod
    def _is_system_column(col_key: str) -> bool:
        return col_key in {VnstockMasterMatrixPipeline._snake_case(c) for c in SYSTEM_COLUMNS} or col_key.startswith("unnamed")

    def _coerce_feature_series(self, series: pd.Series) -> Tuple[Optional[pd.Series], bool]:
        if pd.api.types.is_bool_dtype(series):
            return series.astype(float), False
        if pd.api.types.is_numeric_dtype(series):
            return pd.to_numeric(series, errors="coerce"), False

        cleaned = (
            series.astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("%", "", regex=False)
            .str.strip()
            .replace({"": np.nan, "None": np.nan, "nan": np.nan, "NaN": np.nan})
        )
        numeric = pd.to_numeric(cleaned, errors="coerce")
        if numeric.notna().sum() >= self.config.min_numeric_non_null:
            return numeric, False
        if self.config.include_categorical_hash:
            return series.map(self._stable_hash_to_float).astype(float), True
        
        trend_mapping = {
        "strong_uptrend": 1.0, "uptrend": 0.5, "sideway": 0.0,
        "downtrend": -0.5, "strong_downtrend": -1.0,
        "above_zero": 1.0, "below_zero": -1.0
        }

        lower_series = series.astype(str).str.lower().str.strip()
        if lower_series.isin(trend_mapping.keys()).any():
            return lower_series.map(trend_mapping).astype(float), False
    
        return None, False

    @staticmethod
    def _stable_hash_to_float(value: Any) -> float:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return np.nan
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return np.nan
        digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest()
        integer = int.from_bytes(digest, byteorder="big", signed=False)
        return integer / float(2**64 - 1)

    @staticmethod
    def _to_numeric(series_or_value: Any) -> pd.Series:
        if isinstance(series_or_value, pd.Series):
            s = series_or_value
        else:
            s = pd.Series(series_or_value)
        if pd.api.types.is_numeric_dtype(s):
            return pd.to_numeric(s, errors="coerce")
        return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce")

    def _concat_feature_frames(self, base_index: pd.DatetimeIndex, frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
        out = pd.DataFrame(index=base_index)
        for frame in frames:
            if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
                continue
            frame = frame.reindex(base_index)
            rename_map: Dict[str, str] = {}
            for col in frame.columns:
                if col in out.columns:
                    new_col = self._deduplicate_feature_name(col, list(out.columns) + list(rename_map.values()))
                    rename_map[col] = new_col
                    if col in self.feature_catalog_:
                        record = self.feature_catalog_[col]
                        self.feature_catalog_[new_col] = FeatureAuditRecord(**{**record.__dict__, "feature": new_col})
            if rename_map:
                frame = frame.rename(columns=rename_map)
            out = out.join(frame, how="left")
        return out

    def _finalize_master(self, df: pd.DataFrame) -> pd.DataFrame:
        master = df.copy().sort_index()
        master = master[~master.index.duplicated(keep="last")]
        master = master.replace([np.inf, -np.inf], np.nan)
        feature_cols = [c for c in master.columns if c.startswith(ALLOWED_PREFIXES)]
        master = master[feature_cols]
        for col in master.columns:
            master[col] = self._to_numeric(master[col]).values
        self.assert_feature_contract(master)
        ordered_cols = sorted(master.columns, key=lambda c: (ALLOWED_PREFIXES.index(c[: c.find("_") + 1]), c))
        return master[ordered_cols].astype(float)

    # ------------------------------------------------------------------
    # Imputation and tensor helpers
    # ------------------------------------------------------------------
    def _forward_fill_sticky_features(self, X: pd.DataFrame) -> pd.DataFrame:
        out = X.copy()
        sticky_cols = [
            col
            for col in out.columns
            if self.feature_catalog_.get(col) is not None
            and self.feature_catalog_[col].temporal_mode in {"event_asof"}
        ]
        if sticky_cols:
            out[sticky_cols] = out[sticky_cols].ffill()
        return out

    def _fit_imputation_values(self, train_raw: pd.DataFrame, feature_cols: Sequence[str]) -> Dict[str, float]:
        values: Dict[str, float] = {}
        for col in feature_cols:
            policy = self._infer_fill_policy(col, self.feature_catalog_.get(col).fill_policy if col in self.feature_catalog_ else "median")
            train_series = pd.to_numeric(train_raw[col], errors="coerce")
            if policy == "zero":
                values[col] = 0.0
            elif policy == "neutral_rsi":
                values[col] = 50.0
            elif policy == "neutral_score":
                values[col] = 5.0
            elif policy == "unit":
                values[col] = 1.0
            elif policy == "neutral":
                values[col] = self._safe_median(train_series, fallback=0.0)
            else:
                values[col] = self._safe_median(train_series, fallback=self._fallback_by_prefix(col))
        return values

    @staticmethod
    def _apply_imputation_values(X: pd.DataFrame, impute_values: Mapping[str, float]) -> pd.DataFrame:
        out = X.copy()
        for col, value in impute_values.items():
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(value)
        return out.astype(float)

    def _infer_fill_policy(self, feature_name: str, suggested_policy: str) -> str:
        key = feature_name.lower()
        if feature_name.startswith("FLOW_") and any(
            token in key for token in ("volume", "vol_", "value", "net_val", "net_vol", "buy_", "sell_", "flow", "unmatched", "imbalance")
        ):
            return "zero"
        if feature_name.startswith("MKT_") and any(
            token in key for token in ("volume", "turnover", "trading_value", "dollar_value", "deal_value", "order_imbalance")
        ):
            return "zero"
        if "rsi" in key:
            return "neutral_rsi"
        if "llm_risk_score" in key or "llm_growth_score" in key or key.endswith("_score"):
            return "neutral_score"
        if any(token in key for token in ("rs_vs_index", "ratio_to", "loan_to_deposit")):
            return "unit"
        if any(token in key for token in ("return", "growth", "change", "pct", "hist", "macd", "trend", "z20", "zscore")):
            return "zero"
        if suggested_policy in {"zero", "neutral", "median"}:
            return suggested_policy
        return "median"

    @staticmethod
    def _safe_median(series: pd.Series, fallback: float) -> float:
        clean = pd.to_numeric(series, errors="coerce")
        if clean.notna().sum() == 0:
            return float(fallback)
        val = clean.median(skipna=True)
        if pd.isna(val) or not np.isfinite(val):
            return float(fallback)
        return float(val)

    @staticmethod
    def _fallback_by_prefix(feature_name: str) -> float:
        if feature_name.startswith("INS_"):
            return 0.0
        if feature_name.startswith("FLOW_"):
            return 0.0
        if feature_name.startswith("VAL_"):
            return 1.0
        if feature_name.startswith("FUN_"):
            return 0.0
        if feature_name.startswith("MAC_"):
            return 0.0
        if feature_name.startswith("CMD_"):
            return 0.0
        return 0.0

    # ------------------------------------------------------------------
    # Date parsing
    # ------------------------------------------------------------------
    @classmethod
    def _period_to_end_date(cls, value: Any) -> pd.Timestamp:
        if value is None or pd.isna(value):
            return pd.NaT
        text = str(value).strip().upper()
        q1 = re.match(r"^(\d{4})[-_/ ]?Q([1-4])$", text)
        q2 = re.match(r"^Q([1-4])[-_/ ]?(\d{4})$", text)
        if q1:
            return pd.Period(f"{q1.group(1)}Q{q1.group(2)}", freq="Q").end_time.normalize()
        if q2:
            return pd.Period(f"{q2.group(2)}Q{q2.group(1)}", freq="Q").end_time.normalize()
        ym = re.match(r"^(\d{4})[-_/](\d{1,2})$", text)
        if ym:
            year, month = int(ym.group(1)), int(ym.group(2))
            return pd.Period(f"{year}-{month:02d}", freq="M").end_time.normalize()
        year_only = re.match(r"^(\d{4})$", text)
        if year_only:
            return pd.Timestamp(year=int(year_only.group(1)), month=12, day=31)
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            return pd.NaT
        return pd.Timestamp(parsed).normalize()

    @classmethod
    def _maybe_period_end(cls, value: Any) -> Any:
        if value is None or pd.isna(value):
            return pd.NaT
        text = str(value).strip()
        if re.match(r"^\d{4}[-_/]?Q[1-4]$", text, re.I) or re.match(r"^Q[1-4][-_/]?\d{4}$", text, re.I):
            return cls._period_to_end_date(text)
        if re.match(r"^\d{4}[-_/]\d{1,2}$", text):
            return cls._period_to_end_date(text)
        return value

    def _fetch_index_close(self, base_index: pd.DatetimeIndex) -> pd.Series:
        idx_raw = self._safe_call(
            "market.index.ohlcv",
            lambda: self._call_ohlcv(self.market.index(self.config.index_symbol)),
            required=False,
        )
        idx = self._normalize_date_index(idx_raw)
        if idx.empty or "close" not in idx.columns:
            return pd.Series(np.nan, index=base_index, name="index_close")
        close = self._to_numeric(idx["close"])
        close.index = idx.index
        return close.reindex(base_index).ffill()


if __name__ == "__main__":
    cfg = PipelineConfig(symbol="TCB", index_symbol="VNINDEX", length="1Y", seq_length=5)
    pipeline = VnstockMasterMatrixPipeline(cfg)
    master_df = pipeline.build_master_matrix()
    catalog = pipeline.get_feature_catalog()
    bundle = pipeline.build_tensor_bundle(master_df)
    print(master_df.tail(3))
    print(catalog.tail(10))
    print("X_train", bundle.X_train.shape, "y_train", bundle.y_train.shape)
    print("X_valid", bundle.X_valid.shape, "y_valid", bundle.y_valid.shape)
