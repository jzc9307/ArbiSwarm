"""Shared helper: call Claude, force strict JSON, parse into a Pydantic model."""
import json
import anthropic
from pydantic import BaseModel
import config

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def call_json(system_prompt: str, user_content: str, schema: type[BaseModel]) -> BaseModel:
    response = _client.messages.create(
        model=config.CHEAP_MODEL,
        max_tokens=500,
        system=system_prompt + "\n\nRespond with ONLY valid JSON matching the required schema. No preamble, no markdown fences.",
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text.strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return schema(**json.loads(text))
