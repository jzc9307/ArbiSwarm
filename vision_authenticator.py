import base64
import httpx
from schemas import Listing, VisionCheck
import config
import anthropic
import json

SYSTEM_PROMPT = """You are the Vision Authenticator in an e-commerce arbitrage swarm.
IMPORTANT SCOPE: you are NOT a counterfeit/fraud detector. You check whether the listing
PHOTOS are consistent with the TITLE and DESCRIPTION text - nothing more.
Flag: wrong color vs description, item doesn't match title, obvious stock/catalog photo
instead of a real seller photo, photo count too low to judge.
Output a consistency_score (0-100, where 100 = photos clearly match the text) and
a list of specific mismatches found."""

_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _fetch_image_b64(url: str) -> str | None:
    try:
        resp = httpx.get(url, timeout=5)
        resp.raise_for_status()
        return base64.b64encode(resp.content).decode()
    except Exception:
        return None  # demo cache uses placeholder URLs - real scraper will have real ones


def check(listing: Listing) -> VisionCheck:
    content = [{"type": "text", "text": f"Title: {listing.title}\nDescription: {listing.description}"}]
    for url in listing.image_urls[:3]:  # cap images sent per listing, cost control
        img_b64 = _fetch_image_b64(url)
        if img_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64},
            })

    if len(content) == 1:
        # no real images available (e.g. mock demo data) - return a neutral placeholder
        return VisionCheck(consistency_score=50, mismatches=["no image data available for this demo listing"])

    response = _client.messages.create(
        model=config.CHEAP_MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT + "\n\nRespond with ONLY valid JSON. No preamble, no markdown fences.",
        messages=[{"role": "user", "content": content}],
    )
    text = response.content[0].text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return VisionCheck(**json.loads(text))
