"""Carousell ingestion with strict provenance and anti-bot-aware failures.

No fabricated ratings, descriptions, images, or URLs are produced. A configured
REEF_API_KEY is used first; otherwise Playwright attempts the public search page.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlparse

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import config


CAROUSELL_ORIGIN = "https://www.carousell.com.my"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)


class MarketplaceError(RuntimeError):
    """Base error safe to expose to the API client."""


class MarketplaceBlocked(MarketplaceError):
    """The marketplace challenged the automated browser."""


class MarketplaceUnavailable(MarketplaceError):
    """The configured provider failed or returned an unexpected response."""


def build_search_url(query: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    if not slug:
        raise ValueError("query must contain letters or numbers")
    return f"{CAROUSELL_ORIGIN}/{quote(slug)}/q/"


def _listing_url(raw_url: str) -> str | None:
    absolute = urljoin(CAROUSELL_ORIGIN, raw_url)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.netloc not in {"carousell.com.my", "www.carousell.com.my"}:
        return None
    if not re.search(r"/p/(?:[^/?#]+-)?\d+/?$", parsed.path):
        return None
    return f"https://www.carousell.com.my{parsed.path}"


def _listing_id(url: str) -> str:
    match = re.search(r"(\d+)/?$", urlparse(url).path)
    return match.group(1) if match else url.rstrip("/").rsplit("/", 1)[-1]


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        compact = value.replace(",", "")
        match = re.search(r"(?:RM|MYR)?\s*(\d+(?:\.\d+)?)", compact, re.I)
        if match:
            return float(match.group(1))
    return None


def _valid_images(values: object) -> list[str]:
    if not isinstance(values, list):
        values = [values] if values else []
    images: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("url") or value.get("src")
        if not isinstance(value, str):
            continue
        parsed = urlparse(value)
        if parsed.scheme == "https" and parsed.netloc.endswith(("karousell.com", "carousell.com")):
            images.append(value)
    return list(dict.fromkeys(images))[:5]


def _from_reef_record(record: dict) -> dict | None:
    url = _listing_url(str(record.get("url") or ""))
    price = _number(record.get("price") or record.get("price_text"))
    title = str(record.get("title") or "").strip()
    if not url or not title or not price or price <= 0:
        return None

    seller = record.get("seller") if isinstance(record.get("seller"), dict) else {}
    rating = _number(record.get("seller_rating") or seller.get("rating"))
    card_lines = record.get("card_lines") or []
    description = str(record.get("description") or "").strip()
    if not description and isinstance(card_lines, list):
        description = " ".join(str(line) for line in card_lines if line)

    return {
        "id": str(record.get("listing_id") or record.get("id") or _listing_id(url)),
        "title": title,
        "price": price,
        "description": description,
        "image_urls": _valid_images(record.get("images") or record.get("image")),
        "seller_rating": rating if rating is not None and 0 <= rating <= 5 else None,
        "seller_name": record.get("seller_name") or seller.get("username") or seller.get("name"),
        "condition": record.get("condition_label") or record.get("condition"),
        "posted_at": record.get("posted_at"),
        "url": url,
        "marketplace": "carousell",
        "source": "reef_api",
        "source_verified": True,
    }


def _search_reef(query: str, max_results: int) -> list[dict]:
    try:
        response = httpx.post(
            f"{config.REEF_API_BASE}/carousell/v1/search",
            headers={"x-api-key": config.REEF_API_KEY},
            json={"query": query, "country": "my", "sort": "newest", "exclude_bumped": True},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MarketplaceUnavailable(f"Carousell data provider failed: {exc}") from exc

    if payload.get("ok") is False:
        detail = payload.get("error") or "provider returned an error"
        raise MarketplaceUnavailable(f"Carousell data provider failed: {detail}")
    data = payload.get("data") or payload
    records = data.get("results") or data.get("listings") or []
    listings = [item for record in records if (item := _from_reef_record(record))]
    return listings[:max_results]


def _card_to_listing(anchor) -> dict | None:
    href = anchor.get_attribute("href") or ""
    url = _listing_url(href)
    if not url:
        return None

    text = " ".join((anchor.inner_text() or "").split())
    # `anchors.nth()` returns a Playwright Locator, not an ElementHandle.
    # Keep this helper on the Locator API so it works with current Playwright.
    image = anchor.locator("img").first
    has_image = image.count() > 0
    image_url = image.get_attribute("src") if has_image else None
    image_alt = (image.get_attribute("alt") or "").strip() if has_image else ""
    title = image_alt
    if not title:
        lines = [part.strip() for part in (anchor.inner_text() or "").splitlines() if part.strip()]
        title = next((line for line in lines if not re.search(r"(?:RM|MYR)\s*[\d,]+", line, re.I)), "")
    price = _number(text[text.upper().find("RM") :]) if "RM" in text.upper() else None
    if not title or not price or price <= 0:
        return None

    return {
        "id": _listing_id(url),
        "title": title[:300],
        "price": price,
        "description": text[:1200],
        "image_urls": _valid_images(image_url),
        "seller_rating": None,
        "seller_name": None,
        "url": url,
        "condition": None,
        "marketplace": "carousell",
        "source": "carousell_live",
        "source_verified": True,
    }


def _search_playwright(query: str, max_results: int) -> list[dict]:
    search_url = build_search_url(query)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT, viewport={"width": 1440, "height": 1200})
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(4_000)
                body = page.locator("body").inner_text().lower()
                if "security verification" in body or "just a moment" in page.title().lower():
                    raise MarketplaceBlocked(
                        "Carousell blocked the automated browser. Configure REEF_API_KEY for reliable live data, "
                        "or switch to the clearly labeled demo dataset."
                    )
                anchors = page.locator("a[href*='/p/']")
                listings: list[dict] = []
                seen: set[str] = set()
                for index in range(min(anchors.count(), max_results * 4)):
                    item = _card_to_listing(anchors.nth(index))
                    if item and item["id"] not in seen:
                        seen.add(item["id"])
                        listings.append(item)
                    if len(listings) >= max_results:
                        break
                return listings
            finally:
                browser.close()
    except MarketplaceError:
        raise
    except PlaywrightTimeoutError as exc:
        raise MarketplaceUnavailable("Carousell timed out before search results loaded.") from exc
    except Exception as exc:
        raise MarketplaceUnavailable(f"Live browser search failed: {exc}") from exc


def scrape_carousell(query: str, max_results: int | None = None) -> list[dict]:
    limit = max(1, min(max_results or config.MAX_SEARCH_RESULTS, 48))
    clean_query = " ".join(query.split())
    if len(clean_query) < 2:
        raise ValueError("query must be at least 2 characters")
    if config.REEF_API_KEY:
        return _search_reef(clean_query, limit)
    return _search_playwright(clean_query, limit)
