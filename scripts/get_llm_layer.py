"""
Production LLM adapter for the Vnstock trading pipeline.

Public entrypoint:
    ask_llm(prompt, config, output_format="trade_decision", return_json=True)

The function is backward-compatible with the original scripts/get_llm_layer.py:
- It keeps the same name `ask_llm`.
- It accepts configs shaped as {'llm_config': {...}} or {'agent': {...}}.
- It returns text by default when output_format='text', and returns validated JSON
  when output_format='trade_decision' or return_json=True.

Recommended env var:
    export GEMINI_API_KEY="..."
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Mapping, Optional, Sequence

TRADE_ACTIONS = {"BUY_CANDIDATE", "WATCHLIST", "HOLD_MONITOR", "REDUCE_OR_EXIT", "IGNORE"}

TRADE_DECISION_SCHEMA: Dict[str, Any] = {
    "action": "BUY_CANDIDATE | WATCHLIST | HOLD_MONITOR | REDUCE_OR_EXIT | IGNORE",
    "confidence": "float from 0.0 to 1.0",
    "horizon": "3M | 1Y | monitoring",
    "entry_price_low": "number or null",
    "entry_price_high": "number or null",
    "stop_loss": "number or null",
    "base_target": "number or null",
    "bull_target": "number or null",
    "bear_target": "number or null",
    "suggested_quantity": "integer or 0",
    "suggested_position_value": "number or 0",
    "buy_strategy": "breakout | pullback | staged_accumulation | wait | reduce | exit",
    "sell_or_reduce_rules": "array of strings",
    "reason": "short Vietnamese explanation",
    "key_risks": "array of strings",
    "monitoring_triggers": "array of strings",
}


def _cfg(config: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(config, Mapping):
        return {}
    if isinstance(config.get("llm_config"), Mapping):
        return dict(config["llm_config"])
    if isinstance(config.get("agent"), Mapping):
        return dict(config["agent"])
    return dict(config)


def _first_non_empty(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return default


def _extract_json_text(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        json.loads(cleaned)
        return cleaned
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        raise ValueError("LLM response does not contain a JSON object")
    return match.group(0)


def parse_json_from_text(text: str) -> Dict[str, Any]:
    return json.loads(_extract_json_text(text))


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


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, (tuple, set)):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str):
        if not value.strip():
            return []
        return [x.strip() for x in re.split(r"[;\n]+", value) if x.strip()]
    return [str(value)]


def normalize_trade_decision(raw: Mapping[str, Any], *, strict: bool = True, defaults: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Coerce/validate the JSON object expected by the trade pipeline."""
    if not isinstance(raw, Mapping):
        raise ValueError("trade_decision output must be a JSON object")
    defaults = dict(defaults or {})
    merged = dict(defaults)
    merged.update(dict(raw))

    action = str(merged.get("action", "")).strip().upper()
    action_aliases = {
        "MUA": "BUY_CANDIDATE",
        "CANH_MUA": "WATCHLIST",
        "THEO_DOI": "WATCHLIST",
        "THEO DÕI": "WATCHLIST",
        "NAM_GIU": "HOLD_MONITOR",
        "NẮM GIỮ": "HOLD_MONITOR",
        "GIU": "HOLD_MONITOR",
        "BÁN": "REDUCE_OR_EXIT",
        "BAN": "REDUCE_OR_EXIT",
        "GIAM": "REDUCE_OR_EXIT",
        "GIẢM": "REDUCE_OR_EXIT",
        "BO_QUA": "IGNORE",
        "BỎ QUA": "IGNORE",
    }
    action = action_aliases.get(action, action)
    if action not in TRADE_ACTIONS:
        if strict:
            raise ValueError(f"Invalid trade action: {action!r}")
        action = "IGNORE"

    confidence = _to_float(merged.get("confidence"), 0.5)
    if confidence is None:
        confidence = 0.5
    if confidence > 1.0:
        confidence = confidence / 100.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "action": action,
        "confidence": confidence,
        "horizon": str(merged.get("horizon", "3M") or "3M"),
        "entry_price_low": _to_float(merged.get("entry_price_low")),
        "entry_price_high": _to_float(merged.get("entry_price_high")),
        "stop_loss": _to_float(merged.get("stop_loss")),
        "base_target": _to_float(merged.get("base_target")),
        "bull_target": _to_float(merged.get("bull_target")),
        "bear_target": _to_float(merged.get("bear_target")),
        "suggested_quantity": _to_int(merged.get("suggested_quantity"), 0),
        "suggested_position_value": _to_float(merged.get("suggested_position_value"), 0.0) or 0.0,
        "buy_strategy": str(merged.get("buy_strategy", "wait") or "wait"),
        "sell_or_reduce_rules": _to_list(merged.get("sell_or_reduce_rules")),
        "reason": str(merged.get("reason", "") or ""),
        "key_risks": _to_list(merged.get("key_risks")),
        "monitoring_triggers": _to_list(merged.get("monitoring_triggers")),
    }


def build_output_instruction(output_format: str = "trade_decision") -> str:
    if output_format == "trade_decision":
        return (
            "\n\nIMPORTANT OUTPUT CONTRACT:\n"
            "Return ONLY valid JSON. Do not wrap in markdown. Do not add commentary.\n"
            "The JSON object must follow this schema exactly:\n"
            f"{json.dumps(TRADE_DECISION_SCHEMA, ensure_ascii=False, indent=2)}\n"
        )
    if output_format == "json":
        return "\n\nReturn ONLY valid JSON. Do not wrap in markdown. Do not add commentary.\n"
    return ""


def call_gemini(prompt: str, config: Mapping[str, Any]) -> str:
    c = _cfg(config)
    api_key_env = str(c.get("api_key_env", "GEMINI_API_KEY"))
    api_key = _first_non_empty(os.getenv(api_key_env), c.get("api_key"), os.getenv("TRADING_LLM_API_KEY"))
    if not api_key:
        raise RuntimeError(f"Missing Gemini API key. Set {api_key_env} or provide llm_config.api_key.")

    model = _first_non_empty(
        c.get("model_type"),
        c.get("llm_model"),
        c.get("model"),
        default="gemini-2.5-flash",
    )
    temperature = _to_float(c.get("temperature"), 0.2)
    max_output_tokens = _to_int(c.get("max_output_tokens"), 4096)
    require_json = bool(c.get("require_json", False))

    try:
        from google import genai
    except Exception as exc:
        raise RuntimeError("google-genai is not installed. Install it in the active venv.") from exc

    client = genai.Client(api_key=api_key)

    # Prefer structured generation config if this google-genai version supports it.
    try:
        from google.genai import types  # type: ignore
        gen_config_kwargs: Dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        if require_json:
            gen_config_kwargs["response_mime_type"] = "application/json"
        response = client.models.generate_content(
            model=str(model),
            contents=prompt,
            config=types.GenerateContentConfig(**gen_config_kwargs),
        )
    except TypeError:
        # Backward-compatible call matching the user's original wrapper.
        response = client.models.generate_content(model=str(model), contents=prompt)
    return getattr(response, "text", "") or ""


def ask_llm(
    prompt: str,
    config: Mapping[str, Any],
    *,
    print_response: bool = False,
    return_json: Optional[bool] = None,
    output_format: str = "text",
    output_schema: Optional[str] = None,
    schema_defaults: Optional[Mapping[str, Any]] = None,
    strict: bool = True,
    raise_on_error: bool = True,
) -> Any:
    """Call the configured LLM and return either raw text or validated JSON.

    Parameters
    ----------
    output_format:
        - "text": return raw text, unless return_json=True.
        - "json": parse raw JSON into dict.
        - "trade_decision": parse and validate the trade analyzer schema.
    return_json:
        Optional backward-compatible flag. If None, it is inferred from output_format.
    strict:
        If True, invalid trade actions raise an exception. The pipeline catches this
        and falls back to the heuristic decision.
    """
    if output_schema:
        output_format = str(output_schema)
    fmt = str(output_format or "text").lower().strip()
    c = _cfg(config)
    if fmt in {"json", "trade_decision"}:
        c["require_json"] = True
    augmented_prompt = prompt + build_output_instruction(fmt)

    retry_attempts = max(1, _to_int(c.get("retry_attempts"), 1))
    retry_sleep = _to_float(c.get("retry_sleep"), 1.0) or 1.0
    last_exc: Optional[BaseException] = None
    text = ""
    for attempt in range(retry_attempts):
        try:
            text = call_gemini(augmented_prompt, {"llm_config": c})
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if attempt < retry_attempts - 1:
                time.sleep(retry_sleep * (attempt + 1))
    if last_exc is not None:
        raise last_exc

    if print_response:
        print("AI phản hồi:\n")
        print(text)

    should_return_json = (fmt in {"json", "trade_decision"}) if return_json is None else bool(return_json)
    if not should_return_json:
        return text

    try:
        parsed = parse_json_from_text(text)
        if fmt == "trade_decision":
            return normalize_trade_decision(parsed, strict=strict, defaults=schema_defaults)
        return parsed
    except Exception as exc:
        if raise_on_error:
            raise
        return {"error": f"{type(exc).__name__}: {exc}", "raw_text": text}