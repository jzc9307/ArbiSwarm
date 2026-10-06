"""Optional Gemini JSON helper. Importing the app never requires an API key."""
import json

from pydantic import BaseModel

import config


def is_enabled() -> bool:
    return bool(config.GEMINI_API_KEY)


def call_json(system_prompt: str, user_content: str, schema: type[BaseModel]) -> BaseModel:
    if not is_enabled():
        raise RuntimeError("GEMINI_API_KEY is not configured")

    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.CHEAP_MODEL,
        contents=user_content,
        config={
            "system_instruction": system_prompt
            + "\n\nReturn only valid JSON matching the requested schema. No markdown.",
            "response_mime_type": "application/json",
        },
    )
    text = (response.text or "").strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return schema(**json.loads(text))
