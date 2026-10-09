"""Optional Gemini JSON helper with bounded key failover.

config loads the project's .env. Keep GEMINI_API_KEY as the primary key;
GEMINI_API_KEYS optionally contains comma-separated backup keys. Keys in the
same Google project share quota. Cooldowns are process-local, not distributed.
"""
import json
import math
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from pydantic import BaseModel
import config

_cooldowns: dict[str, float] = {}
_lock = threading.Lock()
_last_status = {"state": "unverified", "message": "AI connection not yet verified."}


def _configured_keys() -> tuple[str, ...]:
    return tuple(dict.fromkeys(key for key in
        [config.GEMINI_API_KEY, *config.GEMINI_API_KEYS] if key))


class KeysCoolingDown(RuntimeError):
    code = 429


def is_enabled() -> bool:
    return bool(_configured_keys())


def ai_status() -> dict:
    if not is_enabled():
        return {"state": "not_configured", "message": "AI is not configured. Local workspace commands are available."}
    with _lock:
        return dict(_last_status)


def failure_status(exc: Exception) -> dict:
    code = getattr(exc, "code", None)
    states = {
        429: ("rate_limited", "AI quota/rate limit reached (429). Using local workspace commands."),
        401: ("access_denied", "Check the Gemini key and project permissions."),
        403: ("access_denied", "Check the Gemini key and project permissions."),
        404: ("model_unavailable", "Configured AI model is unavailable."),
        410: ("model_unavailable", "Configured AI model is unavailable."),
        400: ("invalid_request", "AI configuration/request was rejected."),
    }
    if code in states:
        state, message = states[code]
    elif "timeout" in type(exc).__name__.lower() or "timed out" in str(exc).lower():
        state, message = "timeout", "AI timed out. Using local workspace commands."
    else:
        state, message = "unavailable", "AI request failed. Using local workspace commands."
    return {"state": state, "message": message}


def _retry_delay(exc: Exception) -> float:
    """Respect provider retry hints; otherwise wait at least 60 seconds."""
    delays = [60.0]
    response = getattr(exc, "response", None)
    header = getattr(response, "headers", {}).get("retry-after")
    if header:
        try:
            delays.append(float(header))
        except (TypeError, ValueError):
            try:
                date = parsedate_to_datetime(header)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                delays.append((date - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    payload = getattr(exc, "details", {})
    if isinstance(payload, dict):
        error = payload.get("error", payload)
        details = error.get("details", []) if isinstance(error, dict) else []
        for detail in details if isinstance(details, list) else []:
            if isinstance(detail, dict) and str(detail.get("@type", "")).endswith("google.rpc.RetryInfo"):
                try:
                    delays.append(float(str(detail.get("retryDelay", "60s")).removesuffix("s")))
                except (TypeError, ValueError):
                    pass
    return max(delay for delay in delays if math.isfinite(delay))


def call_json(system_prompt: str, user_content: str | list[object], schema: type[BaseModel], *, timeout_ms: int = 20000) -> BaseModel:
    """Try each available key at most once, and fail over ONLY on HTTP 429.

    No waiting loop: exhausted keys fall back to existing local app commands.
    Each attempt has a timeout. With multiple keys the total latency can grow;
    a slow 429 must not prevent the next configured key from being tried.
    """
    global _last_status
    from google import genai
    from google.genai.errors import ClientError

    generation_config = {
        "system_instruction": system_prompt + "\n\nReturn only valid JSON matching the requested schema. No markdown.",
        "response_mime_type": "application/json",
        "response_json_schema": schema.model_json_schema(),
    }
    try:
        if not is_enabled():
            raise RuntimeError("GEMINI_API_KEY is not configured")
        for key in _configured_keys():
            with _lock:
                if _cooldowns.get(key, 0) > time.monotonic():
                    continue
            client = genai.Client(api_key=key, http_options={
                "timeout": max(10000, timeout_ms), "retry_options": {"attempts": 1},
            })
            try:
                try:
                    response = client.models.generate_content(model=config.CHEAP_MODEL, contents=user_content, config=generation_config)
                except ClientError as exc:
                    if exc.code not in (404, 410) or config.CHEAP_MODEL == config.FALLBACK_MODEL:
                        raise
                    response = client.models.generate_content(model=config.FALLBACK_MODEL, contents=user_content, config=generation_config)
                text = (response.text or "").strip()
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                result = schema(**json.loads(text))
                with _lock:
                    _last_status = {"state": "connected", "message": "AI connected · answers grounded in your board."}
                return result
            except ClientError as exc:
                if exc.code != 429:
                    raise
                with _lock:
                    _cooldowns[key] = time.monotonic() + _retry_delay(exc)
            finally:
                client.close()
        raise KeysCoolingDown("All configured Gemini keys are cooling down; retry later.")
    except Exception as exc:
        with _lock:
            _last_status = failure_status(exc)
        raise
