"""Optional Gemini JSON helper with bounded key failover.

config loads the project's .env. Keep GEMINI_API_KEY as the primary key;
GEMINI_API_KEYS optionally contains comma-separated backup keys. Keys in the
same Google project share quota. Cooldowns are process-local, not distributed.
"""
import json
import math
import threading
import time
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel
import config
from agents.runtime import record, reserve_attempt, RequestBudgetExceeded

_cooldowns: dict[str, float] = {}
_lock = threading.Lock()
_last_status = {"state": "unverified", "message": "AI connection not yet verified."}
_limits = {}
_project_cooldowns = {}
_model_cooldowns = {}
_unavailable_models = {}
ROLE_SLOTS = {'manager': 0, 'analyst': 1, 'vision': 2, 'reviewer': 3, 'chat': 4}


def _configured_keys() -> tuple[str, ...]:
    return tuple(dict.fromkeys(key for key in
        [config.GEMINI_API_KEY, *config.GEMINI_API_KEYS] if key))


class KeysCoolingDown(RuntimeError):
    code = 429


class LocalQuotaExceeded(RuntimeError):
    code = 429


def _project(index):
    labels = config.GEMINI_KEY_PROJECTS
    label = labels[index] if index < len(labels) else ''
    # Unlabelled credentials share a conservative local allowance. These labels
    # only coordinate budgets; they do not verify Google project ownership.
    return label or 'unassigned'


def _reserve(key, index, model):
    project = _project(index)
    now = time.monotonic()
    day = datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
    with _lock:
        if (_cooldowns.get(key, 0) > now or _project_cooldowns.get((project, model), 0) > now
                or _model_cooldowns.get(model, 0) > now):
            raise KeysCoolingDown('Credential or model is cooling down.')
        bucket = _limits.setdefault((project, model), {'day': day, 'daily': 0, 'minute': deque()})
        if bucket['day'] != day:
            bucket.update(day=day, daily=0)
        while bucket['minute'] and bucket['minute'][0] <= now - 60:
            bucket['minute'].popleft()
        if bucket['daily'] >= config.GEMINI_LOCAL_RPD or len(bucket['minute']) >= config.GEMINI_LOCAL_RPM:
            raise LocalQuotaExceeded('Local project request allowance reached.')
        reserve_attempt()
        bucket['daily'] += 1
        bucket['minute'].append(now)


def runtime_status():
    keys = _configured_keys()
    with _lock:
        return {'configured_key_count': len(keys), 'preferred_role_slots': {
            role: (slot + 1 if slot < len(keys) else None) for role, slot in ROLE_SLOTS.items()},
            'local_rpm': config.GEMINI_LOCAL_RPM, 'local_rpd': config.GEMINI_LOCAL_RPD,
            'max_attempts_per_call': config.GEMINI_MAX_ATTEMPTS,
            'distinct_configured_project_groups': len({_project(i) for i in range(len(keys))}),
            'unlabelled_keys_share_local_budget': any(_project(i) == 'unassigned' for i in range(len(keys))),
            'quota_counts_are_estimates': True,
            'quota_scope': 'Process-local; excludes usage by other apps and resets on server restart.',
            'attempts_observed_today': sum(bucket['daily'] for bucket in _limits.values()
                if bucket['day'] == datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat())}


def is_enabled() -> bool:
    return bool(_configured_keys())


def ai_status() -> dict:
    if not is_enabled():
        return {"state": "not_configured", "message": "AI is not configured. Local workspace commands are available."}
    with _lock:
        return dict(_last_status)


def failure_status(exc: Exception) -> dict:
    if isinstance(exc, RequestBudgetExceeded):
        return {'state': 'budget_limited', 'message': 'This operation reached its Gemini request budget. Saved/local evidence remains available.'}
    if isinstance(exc, LocalQuotaExceeded):
        return {'state': 'budget_limited', 'message': 'Local free-tier request allowance reached. No additional Gemini request was sent.'}
    code = getattr(exc, "code", None)
    states = {
        429: ("rate_limited", "AI quota/rate limit reached (429). Using local workspace commands."),
        401: ("access_denied", "Check the Gemini key and project permissions."),
        403: ("access_denied", "Check the Gemini key and project permissions."),
        404: ("model_unavailable", "Configured AI model is unavailable."),
        410: ("model_unavailable", "Configured AI model is unavailable."),
        400: ("invalid_request", "AI configuration/request was rejected."),
        503: ('unavailable', 'Gemini is temporarily overloaded (503). Local evidence remains available.'),
        504: ('timeout', 'Gemini timed out (504). Local evidence remains available.'),
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


def _has_retry_hint(exc):
    if getattr(getattr(exc, 'response', None), 'headers', {}).get('retry-after'):
        return True
    payload = getattr(exc, 'details', {})
    error = payload.get('error', payload) if isinstance(payload, dict) else {}
    details = error.get('details', []) if isinstance(error, dict) else []
    return isinstance(details, list) and any(isinstance(item, dict) and str(item.get('@type', '')).endswith('google.rpc.RetryInfo') for item in details)


def call_json(system_prompt: str, user_content: str | list[object], schema: type[BaseModel], *, timeout_ms: int = 20000, max_output_tokens: int | None = None, usage: dict | None = None, role: str = 'manager') -> BaseModel:
    """Role-aware, locally budgeted JSON call with bounded retries.

    429 may fail over to an available credential/project. 404/410 may use the
    configured fallback model. 503 gets at most one short same-key retry, unless
    the provider asks us to wait. Every wire attempt counts against run budgets.
    """
    global _last_status
    from google import genai
    from google.genai.errors import ClientError, ServerError

    generation_config = {
        "system_instruction": system_prompt + "\n\nReturn only valid JSON matching the requested schema. No markdown.",
        "response_mime_type": "application/json",
        "response_json_schema": schema.model_json_schema(),
    }
    if max_output_tokens is not None:
        generation_config['max_output_tokens'] = max_output_tokens
    attempts = 0
    last_error = None
    keys = _configured_keys()
    preferred = ROLE_SLOTS.get(role, 0) % max(1, len(keys))
    order = list(range(preferred, len(keys))) + list(range(preferred))

    def generate(client, key, index, model):
        nonlocal attempts
        if attempts >= config.GEMINI_MAX_ATTEMPTS:
            raise last_error or RequestBudgetExceeded('Per-call attempt limit reached.')
        _reserve(key, index, model)
        attempts += 1
        record(role, 'request_started', key_slot=index + 1, model=model)
        try:
            result = client.models.generate_content(model=model, contents=user_content, config=generation_config)
        except Exception as exc:
            record(role, 'request_failed', key_slot=index + 1, model=model, code=getattr(exc, 'code', None))
            raise
        observed = {}
        metadata = getattr(result, 'usage_metadata', None)
        for name in ('prompt_token_count', 'candidates_token_count', 'thoughts_token_count', 'total_token_count'):
            value = getattr(metadata, name, None)
            if type(value) is int and value >= 0:
                observed[name] = value
        if usage is not None:
            usage.update(observed)
        record(role, 'provider_response', key_slot=index + 1, model=model, usage=observed)
        return result

    try:
        if not is_enabled():
            raise RuntimeError("GEMINI_API_KEY is not configured")
        for index in order:
            key = keys[index]
            if attempts >= config.GEMINI_MAX_ATTEMPTS:
                break
            with _lock:
                if _cooldowns.get(key, 0) > time.monotonic():
                    continue
            client = genai.Client(api_key=key, http_options={
                "timeout": max(10000, timeout_ms), "retry_options": {"attempts": 1},
            })
            try:
                model = config.CHEAP_MODEL
                if _unavailable_models.get((key, model), 0) > time.monotonic():
                    model = config.FALLBACK_MODEL
                try:
                    response = generate(client, key, index, model)
                except ClientError as exc:
                    last_error = exc
                    if exc.code not in (404, 410) or model == config.FALLBACK_MODEL:
                        raise
                    with _lock:
                        _unavailable_models[(key, model)] = time.monotonic() + 600
                    model = config.FALLBACK_MODEL
                    response = generate(client, key, index, model)
                except ServerError as exc:
                    last_error = exc
                    if exc.code != 503:
                        raise
                    # One short same-credential retry, never a storm across keys.
                    if _has_retry_hint(exc) or attempts >= config.GEMINI_MAX_ATTEMPTS:
                        with _lock:
                            _model_cooldowns[model] = time.monotonic() + _retry_delay(exc)
                        raise
                    time.sleep(.25)
                    try:
                        response = generate(client, key, index, model)
                    except ServerError as repeated:
                        if repeated.code == 503:
                            with _lock:
                                _model_cooldowns[model] = time.monotonic() + 15
                        raise
                text = (response.text or "").strip()
                text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                result = schema(**json.loads(text))
                record(role, 'json_validated')
                with _lock:
                    _last_status = {"state": "connected", "message": "AI connected · answers grounded in your board."}
                return result
            except ClientError as exc:
                last_error = exc
                if exc.code != 429:
                    raise
                with _lock:
                    _cooldowns[key] = time.monotonic() + _retry_delay(exc)
                    if _project(index) != 'unassigned':
                        _project_cooldowns[(_project(index), model)] = _cooldowns[key]
            except (KeysCoolingDown, LocalQuotaExceeded) as exc:
                last_error = exc
                continue
            finally:
                client.close()
        raise last_error if isinstance(last_error, LocalQuotaExceeded) else KeysCoolingDown("Configured Gemini credentials are cooling down or the attempt budget is exhausted.")
    except Exception as exc:
        with _lock:
            _last_status = failure_status(exc)
        record(role, 'local_fallback', reason=_last_status['state'])
        raise
