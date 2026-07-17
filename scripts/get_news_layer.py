"""
Config-driven vnstock_news layer.

Expected project layout:

    Stocks/
    ├── configs/
    │   └── news.json
    └── scripts/
        └── get_news_layer.py

Primary public function:

    from Stocks.scripts.get_news_layer import get_news_layer
    result = get_news_layer("./Stocks/configs/news.json")

The function returns a dictionary with:
    - data: combined pandas DataFrame
    - files: output files written to output.my_path
    - metadata: run metadata and per-site counts
    - errors: non-fatal crawler errors when fail_fast=false

This module intentionally lazy-imports vnstock_news so the project remains importable
in development/test environments where the paid vnstock_news package is not active.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union

import pandas as pd

JsonLike = Union[str, Path, Mapping[str, Any], SimpleNamespace]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "news.json"
SYSTEM_COLUMNS = {"crawl_time_utc", "source"}

DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%Y%m%d",
)

_EMPTY_DATE_STRINGS = {"", "none", "null", "nan", "nat", "-", "--", "n/a"}

class NewsLayerConfigError(ValueError):
    """Raised when news.json is missing required configuration."""


class NewsLayerRuntimeError(RuntimeError):
    """Raised for fail-fast crawler/runtime errors."""


def load_news_config(config: Optional[JsonLike] = None) -> Dict[str, Any]:
    """
    Load news config from a JSON path, dict, SimpleNamespace, or default path.

    Parameters
    ----------
    config:
        None -> Stocks/configs/news.json; str/Path -> JSON file; Mapping -> copied dict;
        SimpleNamespace/object -> vars(config).
    """
    if config is None:
        config_path = DEFAULT_CONFIG_PATH
        if not config_path.exists():
            raise NewsLayerConfigError(f"Default config not found: {config_path}")
        return _load_json(config_path)

    if isinstance(config, (str, Path)):
        return _load_json(Path(config))

    if isinstance(config, Mapping):
        return dict(config)

    if hasattr(config, "__dict__"):
        return dict(vars(config))

    raise NewsLayerConfigError(
        "config must be None, a JSON path, a Mapping, or an object with __dict__."
    )


def get_news_layer(config: Optional[JsonLike] = None) -> Dict[str, Any]:
    """
    Run vnstock_news collection according to news.json.

    Supported profile values:
        - quick: fast RSS/sitemap monitoring for latest news
        - ml: stable historical corpus for classical ML/NLP
        - dl: larger corpus for Transformer/embedding/deep-learning workflows

    Returns
    -------
    dict
        {"data": DataFrame, "files": list[str], "metadata": dict, "errors": list[dict]}
    """
    cfg = load_news_config(config)
    _validate_config(cfg)
    _setup_logging(cfg)

    profile_name = _get_profile_name(cfg)
    run_mode = _get_run_mode(cfg, profile_name)

    logging.info("Starting news layer: profile=%s, run_mode=%s", profile_name, run_mode)

    if profile_name == "quick":
        result = _run_quick_profile(cfg, profile_name, run_mode)
    elif profile_name == "ml":
        result = _run_ml_profile(cfg, profile_name, run_mode)
    elif profile_name == "dl":
        result = _run_dl_profile(cfg, profile_name, run_mode)
    else:
        raise NewsLayerConfigError(
            f"Unsupported run_profile={profile_name!r}. Expected one of: quick, ml, dl."
        )

    df = result["data"]
    files = _save_outputs(df, cfg, profile_name, run_mode, result["metadata"])
    result["files"] = files
    logging.info("News layer finished: rows=%s, files=%s", len(df), len(files))
    return result


# Backward-friendly aliases for different import styles.
get_news = get_news_layer
news_layer = get_news_layer


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise NewsLayerConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _validate_config(cfg: Mapping[str, Any]) -> None:
    required = ["target_sites", "profiles", "crawlers", "network_settings", "output"]
    missing = [key for key in required if key not in cfg]
    if missing:
        raise NewsLayerConfigError(f"Missing required config keys: {missing}")

    profile_name = _get_profile_name(cfg)
    if profile_name not in cfg.get("profiles", {}):
        raise NewsLayerConfigError(
            f"run_profile={profile_name!r} not found in profiles."
        )

    if not isinstance(cfg.get("target_sites"), list) or not cfg["target_sites"]:
        raise NewsLayerConfigError("target_sites must be a non-empty list.")


def _setup_logging(cfg: Mapping[str, Any]) -> None:
    level_name = str(_deep_get(cfg, "runtime.log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def _get_profile_name(cfg: Mapping[str, Any]) -> str:
    return str(cfg.get("run_profile") or _deep_get(cfg, "execution.profile", "quick")).lower()


def _get_run_mode(cfg: Mapping[str, Any], profile_name: str) -> str:
    explicit = cfg.get("run_mode") or _deep_get(cfg, "execution.run_mode", None)
    if explicit:
        return str(explicit).lower()
    return str(_deep_get(cfg, f"profiles.{profile_name}.run_mode", profile_name)).lower()


def _import_vnstock_news() -> Dict[str, Any]:
    """Lazy import vnstock_news classes; keep this module importable without vnstock_news."""
    try:
        import vnstock_news  # type: ignore
    except ImportError as exc:
        raise NewsLayerRuntimeError(
            "vnstock_news is not installed/activated in this Python environment. "
            "Activate your Vnstock virtualenv before calling get_news_layer()."
        ) from exc

    classes: Dict[str, Any] = {}
    for class_name in ["Crawler", "BatchCrawler", "AsyncBatchCrawler", "EnhancedNewsCrawler"]:
        try:
            classes[class_name] = getattr(vnstock_news, class_name)
            continue
        except AttributeError:
            pass
        # Version-compatible fallbacks for package layouts documented by vnstock_news.
        try:
            if class_name == "Crawler":
                from vnstock_news.core.crawler import Crawler  # type: ignore

                classes[class_name] = Crawler
            elif class_name == "BatchCrawler":
                from vnstock_news.core.batch import BatchCrawler  # type: ignore

                classes[class_name] = BatchCrawler
            elif class_name == "EnhancedNewsCrawler":
                from vnstock_news.api.enhanced import EnhancedNewsCrawler  # type: ignore

                classes[class_name] = EnhancedNewsCrawler
        except Exception:
            classes[class_name] = None

    # Async crawler has appeared under multiple paths; try the documented one.
    if classes.get("AsyncBatchCrawler") is None:
        try:
            from vnstock_news.async_crawlers.async_batch import AsyncBatchCrawler  # type: ignore

            classes["AsyncBatchCrawler"] = AsyncBatchCrawler
        except Exception:
            classes["AsyncBatchCrawler"] = None

    return classes


def _run_quick_profile(cfg: Mapping[str, Any], profile: str, run_mode: str) -> Dict[str, Any]:
    classes = _import_vnstock_news()
    sites = _enabled_target_sites(cfg)
    errors: List[Dict[str, Any]] = []
    frames: List[pd.DataFrame] = []
    counts: Dict[str, int] = {}

    for site in sites:
        try:
            if run_mode == "sitemap":
                df = _fetch_with_crawler_get_articles(cfg, classes, site)
            else:
                df = _fetch_with_crawler_rss(cfg, classes, site)
                if df.empty and _deep_get(cfg, "profiles.quick.allow_sitemap_fallback", True):
                    logging.warning("No RSS rows for %s; falling back to Crawler.get_articles().", site)
                    df = _fetch_with_crawler_get_articles(cfg, classes, site)

            df = _postprocess_site_frame(df, cfg, site=site, profile=profile)
            counts[site] = len(df)
            if not df.empty or _deep_get(cfg, "runtime.include_empty_sites", True):
                frames.append(df)
        except Exception as exc:
            _handle_site_error(cfg, errors, site, "quick", exc)
        _sleep_between_sites(cfg)

    combined = _combine_and_postprocess(frames, cfg, profile=profile)
    return _result(combined, cfg, profile, run_mode, counts, errors)


def _run_ml_profile(cfg: Mapping[str, Any], profile: str, run_mode: str) -> Dict[str, Any]:
    classes = _import_vnstock_news()
    sites = _enabled_target_sites(cfg)
    errors: List[Dict[str, Any]] = []
    frames: List[pd.DataFrame] = []
    counts: Dict[str, int] = {}

    # ML defaults to stable BatchCrawler unless config explicitly asks for async_batch.
    use_async = run_mode == "async_batch"

    if use_async:
        async_result = _run_async(_fetch_async_batch_all_sites(cfg, classes, sites, profile="ml"))
        frames = async_result["frames"]
        counts = async_result["counts"]
        errors.extend(async_result["errors"])
    else:
        for site in sites:
            try:
                df = _fetch_with_batch(cfg, classes, site)
                df = _postprocess_site_frame(df, cfg, site=site, profile=profile)
                counts[site] = len(df)
                frames.append(df)
            except Exception as exc:
                _handle_site_error(cfg, errors, site, "ml", exc)
            _sleep_between_sites(cfg)

    combined = _combine_and_postprocess(frames, cfg, profile=profile)
    return _result(combined, cfg, profile, run_mode, counts, errors)


def _run_dl_profile(cfg: Mapping[str, Any], profile: str, run_mode: str) -> Dict[str, Any]:
    classes = _import_vnstock_news()
    sites = _enabled_target_sites(cfg)
    errors: List[Dict[str, Any]] = []
    frames: List[pd.DataFrame] = []
    counts: Dict[str, int] = {}

    if run_mode == "enhanced" and classes.get("EnhancedNewsCrawler") is not None:
        async_result = _run_async(_fetch_enhanced_all_sites(cfg, classes, sites, profile="dl"))
        frames = async_result["frames"]
        counts = async_result["counts"]
        errors.extend(async_result["errors"])
    elif run_mode in {"enhanced", "async_batch"} and classes.get("AsyncBatchCrawler") is not None:
        async_result = _run_async(_fetch_async_batch_all_sites(cfg, classes, sites, profile="dl"))
        frames = async_result["frames"]
        counts = async_result["counts"]
        errors.extend(async_result["errors"])
    else:
        logging.warning("Falling back to BatchCrawler for dl profile.")
        for site in sites:
            try:
                df = _fetch_with_batch(cfg, classes, site)
                df = _postprocess_site_frame(df, cfg, site=site, profile=profile)
                counts[site] = len(df)
                frames.append(df)
            except Exception as exc:
                _handle_site_error(cfg, errors, site, "dl", exc)
            _sleep_between_sites(cfg)

    combined = _combine_and_postprocess(frames, cfg, profile=profile)
    return _result(combined, cfg, profile, run_mode, counts, errors)


def _fetch_with_crawler_rss(cfg: Mapping[str, Any], classes: Mapping[str, Any], site: str) -> pd.DataFrame:
    crawler_cls = _require_class(classes, "Crawler")
    crawler = _build_crawler_instance(cfg, crawler_cls, crawler_key="crawler", site=site)
    params = _method_params(cfg, "crawler", "get_articles_from_feed", site)

    def call() -> Any:
        return _call_compatible(crawler.get_articles_from_feed, **params)

    articles = _retry_sync(call, cfg, site=site, method="Crawler.get_articles_from_feed")
    return _to_dataframe(articles, site=site)


def _fetch_with_crawler_get_articles(cfg: Mapping[str, Any], classes: Mapping[str, Any], site: str) -> pd.DataFrame:
    crawler_cls = _require_class(classes, "Crawler")
    crawler = _build_crawler_instance(cfg, crawler_cls, crawler_key="crawler", site=site)
    params = _method_params(cfg, "crawler", "get_articles", site)
    params = _normalize_optional_source_kwargs(params, source_key="sitemap_url")

    def call() -> Any:
        return _call_compatible(crawler.get_articles, **params)

    articles = _retry_sync(call, cfg, site=site, method="Crawler.get_articles")
    return _to_dataframe(articles, site=site)


def _fetch_with_batch(cfg: Mapping[str, Any], classes: Mapping[str, Any], site: str) -> pd.DataFrame:
    crawler_cls = _require_class(classes, "BatchCrawler")
    crawler = _build_crawler_instance(cfg, crawler_cls, crawler_key="batch", site=site)
    params = _method_params(cfg, "batch", "fetch_articles", site)
    params = _normalize_optional_source_kwargs(params, source_key="sitemap_url")

    def call() -> Any:
        return _call_compatible(crawler.fetch_articles, **params)

    articles = _retry_sync(call, cfg, site=site, method="BatchCrawler.fetch_articles")
    return _to_dataframe(articles, site=site)


async def _fetch_async_batch_all_sites(
    cfg: Mapping[str, Any], classes: Mapping[str, Any], sites: Sequence[str], profile: str
) -> Dict[str, Any]:
    frames: List[pd.DataFrame] = []
    counts: Dict[str, int] = {}
    errors: List[Dict[str, Any]] = []

    for site in sites:
        try:
            sources = _site_sources(cfg, site)
            if not sources:
                logging.warning(
                    "No explicit sitemap/rss sources for async site=%s; falling back to BatchCrawler.",
                    site,
                )
                df = _fetch_with_batch(cfg, classes, site)
            else:
                crawler_cls = _require_class(classes, "AsyncBatchCrawler")
                crawler = _build_crawler_instance(cfg, crawler_cls, crawler_key="async_batch", site=site)
                params = _method_params(cfg, "async_batch", "fetch_articles_async", site)
                params["sources"] = sources

                async def call() -> Any:
                    return await _call_compatible_async(crawler.fetch_articles_async, **params)

                articles = await _retry_async(call, cfg, site=site, method="AsyncBatchCrawler.fetch_articles_async")
                df = _to_dataframe(articles, site=site)

            df = _postprocess_site_frame(df, cfg, site=site, profile=profile)
            counts[site] = len(df)
            frames.append(df)
        except Exception as exc:
            _handle_site_error(cfg, errors, site, f"{profile}/async_batch", exc)
        await _async_sleep_between_sites(cfg)

    return {"frames": frames, "counts": counts, "errors": errors}


async def _fetch_enhanced_all_sites(
    cfg: Mapping[str, Any], classes: Mapping[str, Any], sites: Sequence[str], profile: str
) -> Dict[str, Any]:
    frames: List[pd.DataFrame] = []
    counts: Dict[str, int] = {}
    errors: List[Dict[str, Any]] = []

    for site in sites:
        try:
            sources = _site_sources(cfg, site)
            if not sources:
                strategy = _deep_get(
                    cfg,
                    "profiles.dl.fallback_strategy",
                    "async_then_batch_when_sources_missing",
                )
                if strategy:
                    logging.warning(
                        "No explicit sources for EnhancedNewsCrawler site=%s; falling back to BatchCrawler.",
                        site,
                    )
                    df = _fetch_with_batch(cfg, classes, site)
                else:
                    raise NewsLayerConfigError(
                        f"EnhancedNewsCrawler requires sources for site={site}."
                    )
            else:
                crawler_cls = _require_class(classes, "EnhancedNewsCrawler")
                crawler = _build_crawler_instance(cfg, crawler_cls, crawler_key="enhanced", site=site)
                params = _method_params(cfg, "enhanced", "fetch_articles_async", site)
                params["sources"] = sources
                params.setdefault("site_name", site)

                async def call() -> Any:
                    return await _call_compatible_async(crawler.fetch_articles_async, **params)

                articles = await _retry_async(call, cfg, site=site, method="EnhancedNewsCrawler.fetch_articles_async")
                df = _to_dataframe(articles, site=site)

            df = _postprocess_site_frame(df, cfg, site=site, profile=profile)
            counts[site] = len(df)
            frames.append(df)
        except Exception as exc:
            _handle_site_error(cfg, errors, site, f"{profile}/enhanced", exc)
        await _async_sleep_between_sites(cfg)

    return {"frames": frames, "counts": counts, "errors": errors}


def _build_crawler_instance(cfg: Mapping[str, Any], crawler_cls: Any, crawler_key: str, site: str) -> Any:
    init_cfg = _deep_get(cfg, f"crawlers.{crawler_key}.init", {}) or {}
    kwargs = _resolve_placeholders(init_cfg, cfg=cfg, site=site)

    # Best practice for custom site configs: do not pass site_name together with custom_config.
    custom_config = kwargs.get("custom_config")
    if custom_config:
        kwargs.pop("site_name", None)
    else:
        kwargs.pop("custom_config", None)

    return _construct_compatible(crawler_cls, **kwargs)


def _construct_compatible(cls: Any, **kwargs: Any) -> Any:
    kwargs = _drop_none(kwargs)
    filtered = _filter_kwargs_for_callable(cls, kwargs)
    try:
        return cls(**filtered)
    except TypeError as exc:
        if filtered != kwargs:
            raise
        raise NewsLayerRuntimeError(f"Cannot construct {cls}: {exc}") from exc


def _call_compatible(fn: Callable[..., Any], **kwargs: Any) -> Any:
    kwargs = _drop_none(kwargs)
    filtered = _filter_kwargs_for_callable(fn, kwargs)
    try:
        return fn(**filtered)
    except TypeError as exc:
        # Some package versions expose loose signatures but reject specific kwargs internally.
        # Retry with the minimal signature-filtered set only once.
        if filtered != kwargs:
            return fn(**filtered)
        raise


async def _call_compatible_async(fn: Callable[..., Any], **kwargs: Any) -> Any:
    value = _call_compatible(fn, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


def _filter_kwargs_for_callable(fn: Callable[..., Any], kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return dict(kwargs)

    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)

    allowed = {
        name
        for name, p in params.items()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {k: v for k, v in kwargs.items() if k in allowed}


def _method_params(cfg: Mapping[str, Any], crawler_key: str, method_key: str, site: str) -> Dict[str, Any]:
    params = _deep_get(cfg, f"crawlers.{crawler_key}.methods.{method_key}.params", {}) or {}
    return _resolve_placeholders(params, cfg=cfg, site=site)


def _resolve_placeholders(value: Any, cfg: Mapping[str, Any], site: str) -> Any:
    if isinstance(value, str):
        if value == "$site":
            return site
        if value.startswith("$site."):
            return _deep_get(cfg, f"site_registry.{site}.{value[6:]}", None)
        if value.startswith("$network."):
            return _deep_get(cfg, f"network_settings.{value[9:]}", None)
        if value.startswith("$runtime."):
            return _resolve_runtime_path(cfg, str(_deep_get(cfg, f"runtime.{value[9:]}", "")))
        return value
    if isinstance(value, list):
        return [_resolve_placeholders(v, cfg, site) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_placeholders(v, cfg, site) for k, v in value.items()}
    return value


def _normalize_optional_source_kwargs(params: Dict[str, Any], source_key: str) -> Dict[str, Any]:
    value = params.get(source_key)
    if value in (None, ""):
        params.pop(source_key, None)
    elif isinstance(value, list):
        cleaned = [x for x in value if x]
        if not cleaned:
            params.pop(source_key, None)
        elif len(cleaned) == 1:
            params[source_key] = cleaned[0]
        else:
            params[source_key] = cleaned
    return params


def _site_sources(cfg: Mapping[str, Any], site: str) -> List[str]:
    site_cfg = _deep_get(cfg, f"site_registry.{site}", {}) or {}
    sitemap_urls = site_cfg.get("sitemap_urls") or []
    rss_urls = site_cfg.get("rss_urls") or []
    sources: List[str] = []
    for item in [*sitemap_urls, *rss_urls]:
        if item and item not in sources:
            sources.append(item)
    return sources


def _enabled_target_sites(cfg: Mapping[str, Any]) -> List[str]:
    sites = list(cfg.get("target_sites", []))
    registry = cfg.get("site_registry", {}) or {}
    enabled: List[str] = []
    for site in sites:
        site_cfg = registry.get(site, {})
        if site_cfg.get("enabled", True):
            enabled.append(site)
    return enabled


def _require_class(classes: Mapping[str, Any], name: str) -> Any:
    cls = classes.get(name)
    if cls is None:
        raise NewsLayerRuntimeError(f"vnstock_news class {name} is not available in this environment.")
    return cls


def _retry_sync(fn: Callable[[], Any], cfg: Mapping[str, Any], site: str, method: str) -> Any:
    attempts = int(_deep_get(cfg, "network_settings.retry_attempts", 1) or 1)
    backoff = float(_deep_get(cfg, "network_settings.retry_backoff_seconds", 1.0) or 1.0)
    last_exc: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - errors are logged and optionally fail-fasted.
            last_exc = exc
            if _is_stop_status(exc, cfg) or attempt == attempts:
                break
            sleep_s = backoff * attempt
            logging.warning(
                "Retrying %s for site=%s after error attempt=%s/%s: %s",
                method,
                site,
                attempt,
                attempts,
                exc,
            )
            time.sleep(sleep_s)

    assert last_exc is not None
    raise last_exc


async def _retry_async(fn: Callable[[], Any], cfg: Mapping[str, Any], site: str, method: str) -> Any:
    attempts = int(_deep_get(cfg, "network_settings.retry_attempts", 1) or 1)
    backoff = float(_deep_get(cfg, "network_settings.retry_backoff_seconds", 1.0) or 1.0)
    last_exc: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if _is_stop_status(exc, cfg) or attempt == attempts:
                break
            sleep_s = backoff * attempt
            logging.warning(
                "Retrying %s for site=%s after error attempt=%s/%s: %s",
                method,
                site,
                attempt,
                attempts,
                exc,
            )
            await asyncio.sleep(sleep_s)

    assert last_exc is not None
    raise last_exc


def _is_stop_status(exc: Exception, cfg: Mapping[str, Any]) -> bool:
    message = str(exc)
    stop_statuses = _deep_get(cfg, "network_settings.stop_on_http_status", []) or []
    return any(str(code) in message for code in stop_statuses)


def _handle_site_error(
    cfg: Mapping[str, Any], errors: List[Dict[str, Any]], site: str, stage: str, exc: Exception
) -> None:
    error_record = {
        "site": site,
        "stage": stage,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "time_utc": datetime.now(timezone.utc).isoformat(),
    }
    errors.append(error_record)
    logging.exception("News layer error for site=%s stage=%s", site, stage)
    if _deep_get(cfg, "runtime.fail_fast", False):
        raise NewsLayerRuntimeError(error_record["error"]) from exc


def _to_dataframe(data: Any, site: str) -> pd.DataFrame:
    if data is None:
        df = pd.DataFrame()
    elif isinstance(data, pd.DataFrame):
        df = data.copy()
    elif isinstance(data, list):
        df = pd.DataFrame(data)
    elif isinstance(data, dict):
        # If dict is column-oriented this still works; otherwise creates one row.
        try:
            df = pd.DataFrame(data)
        except ValueError:
            df = pd.DataFrame([data])
    else:
        df = pd.DataFrame([{"raw": data}])

    if "source" not in df.columns:
        df["source"] = site
    else:
        df["source"] = df["source"].fillna(site).replace("", site)
    df["crawl_time_utc"] = datetime.now(timezone.utc).isoformat()
    return df


def _postprocess_site_frame(df: pd.DataFrame, cfg: Mapping[str, Any], site: str, profile: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()
    out.columns = [str(col).strip() for col in out.columns]
    out = _normalize_known_columns(out)

    if _deep_get(cfg, "preprocessing.strip_whitespace", True):
        out = _strip_object_columns(out)

    if _deep_get(cfg, "preprocessing.clean_html", True):
        for col in ["title", "short_description", "content", "tags"]:
            if col in out.columns:
                out[col] = out[col].map(_basic_clean_html)

    if _deep_get(cfg, "preprocessing.parse_publish_time", True):
        out = _parse_publish_time(out, cfg)

    if _deep_get(cfg, "preprocessing.build_text_column", True):
        out = _build_text_column(out, cfg)

    out = _apply_filters(out, cfg)

    if _deep_get(cfg, "preprocessing.drop_rows_without_url", True) and "url" in out.columns:
        out = out[out["url"].notna() & (out["url"].astype(str).str.strip() != "")]

    if profile in {"ml", "dl"} and _deep_get(cfg, "preprocessing.drop_rows_without_text_for_ml_dl", True):
        text_col = str(_deep_get(cfg, "preprocessing.text_column_name", "text"))
        min_chars_key = "preprocessing.min_text_chars_for_dl" if profile == "dl" else "preprocessing.min_text_chars_for_ml"
        min_chars = int(_deep_get(cfg, min_chars_key, 0) or 0)
        if text_col in out.columns:
            out = out[out[text_col].fillna("").astype(str).str.len() >= min_chars]

    if "source" not in out.columns:
        out["source"] = site

    return out.reset_index(drop=True)


def _combine_and_postprocess(frames: Sequence[pd.DataFrame], cfg: Mapping[str, Any], profile: str) -> pd.DataFrame:
    valid = [df for df in frames if isinstance(df, pd.DataFrame) and not df.empty]
    if not valid:
        return pd.DataFrame(columns=_deep_get(cfg, "preprocessing.canonical_columns", []))

    out = pd.concat(valid, ignore_index=True, sort=False)

    if _deep_get(cfg, "preprocessing.deduplicate", True):
        subset = _deep_get(cfg, "preprocessing.deduplicate_subset", ["url"]) or ["url"]
        subset = [col for col in subset if col in out.columns]
        if subset:
            out = out.drop_duplicates(subset=subset, keep="first")

    out = _append_quality_columns(out)
    out = _order_columns(out, cfg)
    _run_quality_checks(out, cfg, profile)
    return out.reset_index(drop=True)


def _normalize_known_columns(df: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "summary": "short_description",
        "description": "short_description",
        "sapo": "short_description",
        "published": "publish_time",
        "published_time": "publish_time",
        "publish_date": "publish_time",
        "pub_date": "publish_time",
        "link": "url",
        "article_url": "url",
        "thumbnail": "image_url",
        "image": "image_url",
        "views": "view_counts",
    }
    rename = {col: aliases[col] for col in df.columns if col in aliases and aliases[col] not in df.columns}
    return df.rename(columns=rename)


def _strip_object_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.select_dtypes(include=["object", "string"]).columns:
        out[col] = out[col].map(lambda x: x.strip() if isinstance(x, str) else x)
    return out


def _basic_clean_html(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = re.sub(r"<script.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_datetime_series_no_infer(values: Any, dayfirst: bool = True) -> pd.Series:
    """
    Parse datetime without Pandas format inference.

    Important:
    - Do NOT call pd.to_datetime(..., errors="coerce") without format.
    - Unmatched values become NaT instead of falling back to dateutil.
    """
    if isinstance(values, pd.Series):
        s = values.copy()
    else:
        s = pd.Series(values)

    if pd.api.types.is_datetime64_any_dtype(s):
        return s

    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")

    text = s.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(_EMPTY_DATE_STRINGS))

    # Remove common timezone suffixes so explicit formats can parse consistently.
    # Example: 2026-07-17T08:24:13+07:00 -> 2026-07-17T08:24:13
    text = text.str.replace(r"\s*(Z|[+-]\d{2}:?\d{2})$", "", regex=True)
    text = text.str.replace(r"\s+(UTC|utc|GMT|gmt)$", "", regex=True)

    for fmt in DATE_FORMATS:
        mask = out.isna() & text.notna()
        if not bool(mask.any()):
            break

        parsed = pd.to_datetime(text.loc[mask], format=fmt, errors="coerce")
        out.loc[mask] = parsed

    return out


def parse_datetime_scalar_no_infer(value: Any, dayfirst: bool = True) -> pd.Timestamp:
    parsed = parse_datetime_series_no_infer([value], dayfirst=dayfirst)
    if parsed.empty:
        return pd.NaT
    return parsed.iloc[0]

def _parse_publish_time(df: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.DataFrame:
    out = df.copy()
    if "publish_time" not in out.columns:
        return out

    out["publish_time"] = parse_datetime_series_no_infer(
        out["publish_time"],
        dayfirst=True,
    )
    return out


def _build_text_column(df: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.DataFrame:
    out = df.copy()
    text_col = str(_deep_get(cfg, "preprocessing.text_column_name", "text"))
    parts = _deep_get(cfg, "preprocessing.text_parts", ["title", "short_description", "content"]) or []
    available = [col for col in parts if col in out.columns]
    if not available:
        out[text_col] = ""
        return out

    out[text_col] = (
        out[available]
        .fillna("")
        .astype(str)
        .agg("\n".join, axis=1)
        .map(lambda x: re.sub(r"\s+", " ", x).strip())
    )
    return out


def _apply_filters(df: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.DataFrame:
    filters = cfg.get("filters", {}) or {}
    if not filters.get("enabled", False) or df.empty:
        return df

    out = df.copy()
    search_cols = [col for col in filters.get("search_columns", []) if col in out.columns]
    if search_cols:
        haystack = out[search_cols].fillna("").astype(str).agg(" ".join, axis=1)
    else:
        haystack = pd.Series([""] * len(out), index=out.index)

    case_sensitive = bool(filters.get("case_sensitive", False))
    if not case_sensitive:
        haystack_cmp = haystack.str.lower()
    else:
        haystack_cmp = haystack

    def normalize_terms(terms: Iterable[str]) -> List[str]:
        values = [str(term) for term in terms if str(term).strip()]
        return values if case_sensitive else [term.lower() for term in values]

    keywords_any = normalize_terms(filters.get("keywords_any", []))
    keywords_all = normalize_terms(filters.get("keywords_all", []))
    symbols_any = normalize_terms(filters.get("symbols_any", []))

    mask = pd.Series(True, index=out.index)
    if keywords_any:
        mask &= haystack_cmp.map(lambda text: any(term in text for term in keywords_any))
    if keywords_all:
        mask &= haystack_cmp.map(lambda text: all(term in text for term in keywords_all))
    if symbols_any:
        mask &= haystack_cmp.map(lambda text: any(term in text for term in symbols_any))

    if "publish_time" in out.columns:
        start = filters.get("start_date")
        end = filters.get("end_date")

        if start:
            start_ts = parse_datetime_scalar_no_infer(start, dayfirst=True)
            if pd.notna(start_ts):
                mask &= out["publish_time"] >= start_ts

        if end:
            end_ts = parse_datetime_scalar_no_infer(end, dayfirst=True)
            if pd.notna(end_ts):
                mask &= out["publish_time"] <= end_ts

    return out[mask].reset_index(drop=True)


def _append_quality_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "text" in out.columns:
        out["text_len"] = out["text"].fillna("").astype(str).str.len()
    if "content" in out.columns:
        out["content_len"] = out["content"].fillna("").astype(str).str.len()
    return out


def _order_columns(df: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.DataFrame:
    canonical = _deep_get(cfg, "preprocessing.canonical_columns", []) or []
    existing_front = [col for col in canonical if col in df.columns]
    rest = [col for col in df.columns if col not in existing_front]
    return df[existing_front + rest]


def _run_quality_checks(df: pd.DataFrame, cfg: Mapping[str, Any], profile: str) -> None:
    if df.empty and _deep_get(cfg, "quality_checks.warn_if_empty", True):
        logging.warning("News layer output is empty for profile=%s.", profile)
        return

    required = _deep_get(cfg, "quality_checks.required_columns", []) or []
    missing = [col for col in required if col not in df.columns]
    if missing and _deep_get(cfg, "quality_checks.warn_if_missing_required_columns", True):
        logging.warning("Missing required output columns: %s", missing)

    max_null_ratio = float(_deep_get(cfg, "quality_checks.max_null_ratio_warning", 0.8) or 0.8)
    for col in required:
        if col in df.columns and len(df) > 0:
            ratio = float(df[col].isna().mean())
            if ratio >= max_null_ratio:
                logging.warning("High null ratio for column %s: %.2f", col, ratio)


def _save_outputs(
    df: pd.DataFrame,
    cfg: Mapping[str, Any],
    profile: str,
    run_mode: str,
    metadata: Mapping[str, Any],
) -> List[str]:
    if not _deep_get(cfg, "output.enabled", True):
        return []

    out_dir = _resolve_runtime_path(cfg, str(_deep_get(cfg, "output.my_path", "./my_path/news")))
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    template = str(_deep_get(cfg, "output.filename_template", "vnstock_news_{profile}_{run_mode}_{timestamp}"))
    stem = template.format(profile=profile, run_mode=run_mode, timestamp=timestamp)
    formats = _deep_get(cfg, "output.formats", ["csv"]) or ["csv"]
    files: List[str] = []

    if _deep_get(cfg, "output.partition_by_site", False) and "source" in df.columns:
        for source, part in df.groupby("source", dropna=False):
            part_stem = f"{stem}_{str(source).replace('/', '_')}"
            files.extend(_write_dataframe_formats(part, out_dir, part_stem, formats, cfg))
    else:
        files.extend(_write_dataframe_formats(df, out_dir, stem, formats, cfg))

    if _deep_get(cfg, "output.save_manifest", True):
        manifest_path = out_dir / f"{stem}_manifest.json"
        manifest = {
            "profile": profile,
            "run_mode": run_mode,
            "rows": int(len(df)),
            "columns": list(df.columns),
            "files": files,
            "metadata": dict(metadata),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=bool(_deep_get(cfg, "output.json_force_ascii", False)), indent=2, default=str),
            encoding="utf-8",
        )
        files.append(str(manifest_path))

    return files


def _write_dataframe_formats(
    df: pd.DataFrame,
    out_dir: Path,
    stem: str,
    formats: Sequence[str],
    cfg: Mapping[str, Any],
) -> List[str]:
    files: List[str] = []
    index = bool(_deep_get(cfg, "output.index", False))

    for fmt in formats:
        fmt_lower = str(fmt).lower()
        if fmt_lower == "csv":
            path = out_dir / f"{stem}.csv"
            df.to_csv(path, index=index, encoding=str(_deep_get(cfg, "output.csv_encoding", "utf-8-sig")))
            files.append(str(path))
        elif fmt_lower in {"jsonl", "ndjson"}:
            path = out_dir / f"{stem}.jsonl"
            df.to_json(
                path,
                orient="records",
                lines=True,
                force_ascii=bool(_deep_get(cfg, "output.json_force_ascii", False)),
                date_format="iso",
            )
            files.append(str(path))
        elif fmt_lower == "json":
            path = out_dir / f"{stem}.json"
            df.to_json(
                path,
                orient="records",
                force_ascii=bool(_deep_get(cfg, "output.json_force_ascii", False)),
                date_format="iso",
                indent=2,
            )
            files.append(str(path))
        elif fmt_lower == "parquet":
            path = out_dir / f"{stem}.parquet"
            try:
                df.to_parquet(path, index=index)
                files.append(str(path))
            except Exception as exc:  # noqa: BLE001
                logging.warning("Could not write parquet output. Install pyarrow/fastparquet. Error: %s", exc)
        else:
            logging.warning("Unsupported output format ignored: %s", fmt)

    return files


def _result(
    df: pd.DataFrame,
    cfg: Mapping[str, Any],
    profile: str,
    run_mode: str,
    counts: Mapping[str, int],
    errors: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return {
        "data": df,
        "files": [],
        "metadata": {
            "profile": profile,
            "run_mode": run_mode,
            "target_sites": _enabled_target_sites(cfg),
            "site_row_counts": dict(counts),
            "row_count": int(len(df)),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        },
        "errors": list(errors),
    }


def _run_async(coro: Any) -> Any:
    """
    Run async code from scripts, notebooks, or existing event loops.

    If an event loop is already running, execute the coroutine in a short-lived thread
    with its own loop. This avoids the common `asyncio.run() cannot be called from a
    running event loop` failure in notebooks.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: Dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _sleep_between_sites(cfg: Mapping[str, Any]) -> None:
    if not _deep_get(cfg, "network_settings.sleep_between_sites", True):
        return
    delay = float(_deep_get(cfg, "network_settings.request_delay", 0.0) or 0.0)
    if delay > 0:
        time.sleep(delay)


async def _async_sleep_between_sites(cfg: Mapping[str, Any]) -> None:
    if not _deep_get(cfg, "network_settings.sleep_between_sites", True):
        return
    delay = float(_deep_get(cfg, "network_settings.request_delay", 0.0) or 0.0)
    if delay > 0:
        await asyncio.sleep(delay)


def _deep_get(mapping: Mapping[str, Any], dotted_path: str, default: Any = None) -> Any:
    current: Any = mapping
    for part in dotted_path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return default
    return current


def _drop_none(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


def _resolve_runtime_path(cfg: Mapping[str, Any], path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path
    # Resolve relative paths from the current working directory, which is more intuitive
    # when users run `python -m Stocks.scripts.get_news_layer` from project root.
    return Path.cwd() / path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run config-driven vnstock_news layer.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to news.json. Default: Stocks/configs/news.json",
    )
    args = parser.parse_args()

    result = get_news_layer(args.config)
    print("Rows:", len(result["data"]))
    print("Files:")
    for file_path in result["files"]:
        print(" -", file_path)
    if result["errors"]:
        print("Errors:")
        for err in result["errors"]:
            print(" -", err)


if __name__ == "__main__":
    main()
