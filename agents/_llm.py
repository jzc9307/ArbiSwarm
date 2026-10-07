"""Optional Gemini JSON helper. Importing the app never requires an API key."""
import json

from pydantic import BaseModel

import config

_last_status = {"state": "unverified", "message": "AI key configured; connection not yet verified."}


def ai_status() -> dict:
    if not is_enabled():
        return {"state": "not_configured", "message": "AI is not configured. Local workspace commands are available."}
    return dict(_last_status)


def failure_status(exc: Exception) -> dict:
    code = getattr(exc, 'code', None)
    if code == 429:
        return {"state": "rate_limited", "message": "AI quota/rate limit reached (429). Using local workspace commands."}
    if code in (401, 403):
        return {"state": "access_denied", "message": "AI access was denied. Check the Gemini key and project permissions."}
    if code in (404, 410):
        return {"state": "model_unavailable", "message": "Configured AI model is unavailable. Check the model setting."}
    if code == 400:
        return {"state": "invalid_request", "message": "AI configuration/request was rejected (400). Using local workspace commands."}
    if 'timeout' in type(exc).__name__.lower() or 'timed out' in str(exc).lower():
        return {"state": "timeout", "message": "AI timed out. Using local workspace commands."}
    return {"state": "unavailable", "message": "AI request failed. Using local workspace commands."}


def is_enabled() -> bool:
    return bool(config.GEMINI_API_KEY)


def call_json(system_prompt: str, user_content: str, schema: type[BaseModel], *, timeout_ms: int = 20000) -> BaseModel:
    global _last_status
    if not is_enabled():
        raise RuntimeError("GEMINI_API_KEY is not configured")

    from google import genai
    from google.genai.errors import ClientError

    # Gemini rejects explicitly configured deadlines shorter than 10 seconds.
    client = genai.Client(api_key=config.GEMINI_API_KEY, http_options={"timeout": max(10000, timeout_ms), "retry_options": {"attempts": 1}})
    generation_config = {
            "system_instruction": system_prompt
            + "\n\nReturn only valid JSON matching the requested schema. No markdown.",
            "response_mime_type": "application/json",
        }
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
        _last_status = {"state": "connected", "message": "AI connected · answers grounded in your board."}
        return result
    except Exception as exc:
        _last_status = failure_status(exc)
        raise
