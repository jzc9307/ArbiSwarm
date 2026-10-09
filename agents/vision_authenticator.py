from urllib.parse import urlparse

import httpx

from schemas import Listing, VisionCheck
from agents._llm import is_enabled, call_json

SYSTEM_PROMPT = """You compare listing photos with the title and description.
Do not claim an item is authentic or counterfeit. Report only visible consistency,
wrong item/color, obvious catalog imagery, or insufficient photographic evidence.
Return consistency_score, mismatches, and images_checked as JSON."""

_ALLOWED_IMAGE_HOST_SUFFIXES = (
    "karousell.com",
    "carousell.com",
    "slatic.net",
    "lazcdn.com",
    "rnudah.com",
    "mudah.my",
    "ebayimg.com",
    "etsystatic.com",
    "susercontent.com",
)


def _fetch_image(url: str) -> tuple[bytes, str] | None:
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != "https" or parsed.username or not any(host == suffix or host.endswith('.' + suffix) for suffix in _ALLOWED_IMAGE_HOST_SUFFIXES):
        return None
    try:
        response = httpx.get(url, timeout=8, follow_redirects=False)
        response.raise_for_status()
        mime = response.headers.get("content-type", "").split(";", 1)[0]
        if not mime.startswith("image/") or len(response.content) > 8_000_000:
            return None
        return response.content, mime
    except httpx.HTTPError:
        return None


def check(listing: Listing) -> VisionCheck:
    if not listing.image_urls:
        return VisionCheck(
            consistency_score=None,
            mismatches=["no listing photos were available to inspect"],
            images_checked=0,
        )
    if not is_enabled():
        return VisionCheck(
            consistency_score=None,
            mismatches=["photo analysis requires a configured Gemini key"],
            images_checked=0,
        )

    from google.genai import types

    parts: list[object] = [f"Title: {listing.title}\nDescription: {listing.description}"]
    checked = 0
    for url in listing.image_urls[:3]:
        fetched = _fetch_image(url)
        if fetched:
            data, mime = fetched
            parts.append(types.Part.from_bytes(data=data, mime_type=mime))
            checked += 1
    if not checked:
        return VisionCheck(
            consistency_score=None,
            mismatches=["listing photos could not be downloaded safely"],
            images_checked=0,
        )

    try:
        result = call_json(SYSTEM_PROMPT, parts, VisionCheck)
        result.images_checked = checked
        return result
    except Exception:
        return VisionCheck(
            consistency_score=None,
            mismatches=["photo analysis failed; no visual claim was made"],
            images_checked=0,
        )
