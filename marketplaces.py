"""Marketplace adapters with one normalized Listing-shaped output contract."""
from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlparse

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

import config
import scraper as carousell


SUPPORTED_MARKETPLACES = ("carousell", "lazada", "mudah", "shopee")
DISPLAY_NAMES = {
    "carousell": "Carousell",
    "lazada": "Lazada",
    "mudah": "Mudah",
    "shopee": "Shopee",
}


class MarketplaceSearchError(RuntimeError):
    pass


def _price(value: object) -> float | None:
    try:
        amount = float(str(value).replace("RM", "").replace(",", "").strip())
        return amount if amount > 0 else None
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if value is None:
        return None
    text = str(value).replace(",", "").strip().upper()
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    multiplier = 1_000_000 if "M" in text else (1_000 if "K" in text else 1)
    return int(float(match.group()) * multiplier)


def _images(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    output: list[str] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("url") or item.get("src")
        if not isinstance(item, str):
            continue
        url = urljoin("https:", item)
        if urlparse(url).scheme == "https":
            output.append(url)
    return list(dict.fromkeys(output))[:5]


def _request_reef(engine: str, payload: dict) -> dict:
    if not config.REEF_API_KEY:
        raise MarketplaceSearchError(f"{DISPLAY_NAMES.get(engine, engine)} requires REEF_API_KEY")
    try:
        response = httpx.post(
            f"{config.REEF_API_BASE}/{engine}/v1/search",
            headers={"x-api-key": config.REEF_API_KEY},
            json=payload,
            timeout=35,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MarketplaceSearchError(f"{DISPLAY_NAMES.get(engine, engine)} provider failed: {exc}") from exc
    if body.get("ok") is False:
        error = body.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise MarketplaceSearchError(message or f"{engine} provider returned an error")
    return body.get("data") or body


def search_carousell(query: str, limit: int) -> list[dict]:
    return carousell.scrape_carousell(query, max_results=limit)


def search_lazada(query: str, limit: int) -> list[dict]:
    try:
        response = httpx.get(
            "https://www.lazada.com.my/catalog/",
            params={"ajax": "true", "isFirstRequest": "true", "page": 1, "q": query},
            headers={
                "user-agent": carousell.USER_AGENT,
                "accept": "application/json, text/plain, */*",
                "accept-language": "en-MY,en;q=0.9",
                "referer": "https://www.lazada.com.my/",
            },
            timeout=35,
            follow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        payload = response.json() if "json" in content_type else None
    except (httpx.HTTPError, ValueError):
        payload = None

    # Lazada sometimes returns an HTML session bootstrap to its historical JSON
    # endpoint. A normal public browser page still exposes product cards, so use
    # that as a transparent fallback without attempting to bypass verification.
    if not isinstance(payload, dict):
        return _search_lazada_browser(query, limit)

    records = (payload.get("mods") or {}).get("listItems") or []
    listings: list[dict] = []
    for record in records:
        url = urljoin("https://www.lazada.com.my", str(record.get("itemUrl") or ""))
        title = str(record.get("name") or "").strip()
        price = _price(record.get("price"))
        parsed = urlparse(url)
        if parsed.netloc not in {"lazada.com.my", "www.lazada.com.my"} or "/products/" not in parsed.path:
            continue
        if not title or price is None:
            continue
        rating = _price(record.get("ratingScore"))
        review_count = _integer(record.get("review"))
        sold_count = _integer(record.get("itemSoldCnt") or record.get("itemSoldCntShow"))
        seller = record.get("sellerName") or record.get("seller")
        location = record.get("location")
        sold = record.get("itemSoldCntShow") or record.get("itemSoldCnt")
        description_bits = [title]
        if location:
            description_bits.append(f"Ships from {location}")
        if sold:
            description_bits.append(f"{sold} sold")
        listings.append({
            "id": str(record.get("itemId") or parsed.path),
            "title": title,
            "price": price,
            "description": ". ".join(description_bits),
            "image_urls": _images(record.get("image") or record.get("thumbs")),
            "seller_rating": None,
            "seller_name": str(seller) if seller else None,
            "listing_rating": rating if rating is not None and rating <= 5 else None,
            "review_count": review_count,
            "sold_count": sold_count,
            "url": url,
            "condition": "New retail listing",
            "marketplace": "lazada",
            "source": "lazada_live",
            "source_verified": True,
        })
        if len(listings) >= limit:
            break
    return listings


def _lazada_browser_card(anchor) -> dict | None:
    raw_url = anchor.get_attribute("href") or ""
    url = urljoin("https://www.lazada.com.my", raw_url)
    parsed = urlparse(url)
    if parsed.netloc not in {"lazada.com.my", "www.lazada.com.my"} or "/products/" not in parsed.path:
        return None
    title = " ".join((anchor.inner_text() or "").split())
    if not title:
        return None
    # Current Lazada cards place the title link three wrappers below the full
    # result card. Use content semantics (price/image) rather than class names,
    # which are generated and change frequently.
    card = anchor.locator("xpath=../../..").first
    text = "\n".join(part.strip() for part in (card.inner_text() or "").splitlines() if part.strip())
    price = _price_from_text(text)
    if price is None:
        return None
    image = card.locator("img").first
    image_url = image.get_attribute("src") if image.count() else None
    sold_match = re.search(r"([\d,.]+\s*[kKmM]?)\s+sold", text, re.I)
    review_match = re.search(r"\(([\d,.]+\s*[kKmM]?)\)", text)
    item_match = re.search(r"-i(\d+)\.html", parsed.path)
    return {
        "id": item_match.group(1) if item_match else parsed.path,
        "title": title[:300],
        "price": price,
        "description": text[:1200],
        "image_urls": _images(image_url),
        "seller_rating": None,
        "seller_name": None,
        "listing_rating": None,
        "review_count": _integer(review_match.group(1)) if review_match else None,
        "sold_count": _integer(sold_match.group(1)) if sold_match else None,
        "url": url,
        "condition": "New retail listing",
        "marketplace": "lazada",
        "source": "lazada_live",
        "source_verified": True,
    }


def _search_lazada_browser(query: str, limit: int) -> list[dict]:
    search_url = f"https://www.lazada.com.my/catalog/?q={quote(query)}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=carousell.USER_AGENT,
                viewport={"width": 1440, "height": 1200},
                locale="en-MY",
            )
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(3_000)
                body = page.locator("body").inner_text()
                blocked_terms = ("captcha", "verify you are human", "security verification", "unusual traffic")
                if any(term in body.lower() for term in blocked_terms):
                    raise MarketplaceSearchError(
                        "Lazada requested human verification. ArbiSwarm will not bypass that challenge."
                    )
                anchors = page.locator("a")
                listings: list[dict] = []
                seen: set[str] = set()
                for index in range(anchors.count()):
                    anchor = anchors.nth(index)
                    if "/products/" not in (anchor.get_attribute("href") or ""):
                        continue
                    item = _lazada_browser_card(anchor)
                    if item and item["id"] not in seen:
                        seen.add(item["id"])
                        listings.append(item)
                    if len(listings) >= limit:
                        break
                if not listings:
                    raise MarketplaceSearchError(
                        "Lazada returned no readable public product cards. Try again later."
                    )
                return listings
            finally:
                browser.close()
    except MarketplaceSearchError:
        raise
    except PlaywrightTimeoutError as exc:
        raise MarketplaceSearchError("Lazada timed out before public results loaded.") from exc
    except Exception as exc:
        raise MarketplaceSearchError(f"Lazada public search unavailable: {type(exc).__name__}") from exc


def search_mudah(query: str, limit: int) -> list[dict]:
    data = _request_reef("mudah", {
        "query": query,
        "limit": limit,
        "include_description": True,
        "include_images": True,
    })
    listings: list[dict] = []
    for record in data.get("results") or []:
        url = str(record.get("url") or "")
        parsed = urlparse(url)
        title = str(record.get("title") or "").strip()
        price = _price(record.get("price"))
        if parsed.netloc not in {"mudah.my", "www.mudah.my"} or not parsed.path.endswith(".htm"):
            continue
        if not title or price is None:
            continue
        seller = record.get("seller") if isinstance(record.get("seller"), dict) else {}
        listings.append({
            "id": str(record.get("listing_id") or record.get("ad_id")),
            "title": title,
            "price": price,
            "description": str(record.get("description") or "").strip(),
            "image_urls": _images(record.get("images") or record.get("image")),
            "seller_rating": None,
            "seller_name": seller.get("name"),
            "listing_rating": None,
            "review_count": None,
            "sold_count": None,
            "url": url,
            "condition": record.get("condition"),
            "posted_at": record.get("posted_at"),
            "marketplace": "mudah",
            "source": "mudah_reef",
            "source_verified": True,
        })
    return listings[:limit]


def _shopee_listing_url(raw_url: str) -> str | None:
    absolute = urljoin("https://shopee.com.my", raw_url)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.netloc not in {"shopee.com.my", "www.shopee.com.my"}:
        return None
    product_path = re.search(r"-i\.(\d+)\.(\d+)/?$", parsed.path)
    canonical_path = re.search(r"/product/(\d+)/(\d+)/?$", parsed.path)
    if not product_path and not canonical_path:
        return None
    return f"https://shopee.com.my{parsed.path}"


def _shopee_listing_id(url: str) -> str:
    path = urlparse(url).path
    match = re.search(r"(?:-i\.\d+\.|/product/\d+/)(\d+)/?$", path)
    return match.group(1) if match else path.rstrip("/").rsplit("/", 1)[-1]


def _price_from_text(value: str) -> float | None:
    match = re.search(r"(?:RM|MYR)\s*([\d,]+(?:\.\d{1,2})?)", value, re.I)
    return _price(match.group(1)) if match else None


def _shopee_card_to_listing(anchor) -> dict | None:
    url = _shopee_listing_url(anchor.get_attribute("href") or "")
    if not url:
        return None
    text = " ".join((anchor.inner_text() or "").split())
    price = _price_from_text(text)
    image = anchor.locator("img").first
    has_image = image.count() > 0
    title = (image.get_attribute("alt") or "").strip() if has_image else ""
    if not title:
        lines = [part.strip() for part in (anchor.inner_text() or "").splitlines() if part.strip()]
        title = next((line for line in lines if not re.search(r"(?:RM|MYR)\s*[\d,]+", line, re.I)), "")
    image_url = None
    if has_image:
        image_url = image.get_attribute("src") or image.get_attribute("data-src")
    if not title or price is None:
        return None
    return {
        "id": _shopee_listing_id(url),
        "title": title[:300],
        "price": price,
        "description": text[:1200],
        "image_urls": _images(image_url),
        "seller_rating": None,
        "seller_name": None,
        "listing_rating": None,
        "review_count": None,
        "sold_count": _integer(next((part for part in text.split(" · ") if "sold" in part.lower()), None)),
        "url": url,
        "condition": "New retail listing",
        "marketplace": "shopee",
        "source": "shopee_browser",
        "source_verified": True,
    }


def _shopee_provider_record(record: dict) -> dict | None:
    url = _shopee_listing_url(str(
        record.get("shopeeUrl")
        or record.get("productPageUrl")
        or record.get("productUrl")
        or record.get("url")
        or ""
    ))
    title = str(
        record.get("title")
        or record.get("productName")
        or record.get("productTitle")
        or record.get("name")
        or ""
    ).strip()
    price = _price(record.get("price") or record.get("minPrice") or record.get("priceMin"))
    if not url or not title or price is None:
        return None
    rating = _price(record.get("rating") or record.get("ratingStar"))
    sold = _integer(
        record.get("historicalSold")
        or record.get("totalSaleCnt")
        or record.get("sold")
        or record.get("estimateSold")
    )
    description = str(record.get("description") or "").strip()
    if not description:
        description = f"{title}. {sold} sold" if sold is not None else title
    return {
        "id": str(record.get("pid") or record.get("itemId") or _shopee_listing_id(url)),
        "title": title,
        "price": price,
        "description": description,
        "image_urls": _images(record.get("images") or record.get("imageUrl") or record.get("imageCover")),
        "seller_rating": None,
        "seller_name": (
            record.get("merchant")
            or record.get("shopName")
            or record.get("shopUsername")
            or record.get("userName")
        ),
        "listing_rating": rating if rating is not None and rating <= 5 else None,
        "review_count": _integer(record.get("ratings") or record.get("ratingCount")),
        "sold_count": sold,
        "url": url,
        "condition": "New retail listing",
        "marketplace": "shopee",
        "source": "shopee_nexscope",
        "source_verified": True,
    }


def _search_shopee_provider(query: str, limit: int) -> list[dict]:
    try:
        response = httpx.post(
            config.NEXSCOPE_SHOPEE_URL,
            headers={
                "authorization": f"Bearer {config.NEXSCOPE_API_KEY}",
                "content-type": "application/json",
            },
            json={
                "station": "MY",
                "keyword": query,
                "keywordType": 1,
                "page": 1,
                "pageSize": limit,
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MarketplaceSearchError(f"Shopee data provider failed: {exc}") from exc
    if isinstance(payload, dict) and payload.get("code") not in (None, 0):
        raise MarketplaceSearchError(
            str(payload.get("msg") or "Nexscope rejected the Shopee search request.")
        )
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    records = (data.get("products") or data.get("items") or []) if isinstance(data, dict) else []
    listings = [item for record in records if (item := _shopee_provider_record(record))]
    if not listings:
        if records:
            raise MarketplaceSearchError("Nexscope returned Shopee records without valid Malaysian product URLs.")
        raise MarketplaceSearchError("Nexscope returned zero Shopee matches for this search.")
    return listings[:limit]


def _search_shopee_browser(query: str, limit: int) -> list[dict]:
    """Read Shopee's normal public search page without bypassing challenges."""
    search_url = f"https://shopee.com.my/search?keyword={quote(query)}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=carousell.USER_AGENT,
                viewport={"width": 1440, "height": 1200},
                locale="en-MY",
            )
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(5_000)
                body = page.locator("body").inner_text().lower()
                title = page.title().lower()
                blocked_terms = ("captcha", "verify you are human", "security verification", "unusual traffic")
                if any(term in body or term in title for term in blocked_terms):
                    raise MarketplaceSearchError(
                        "Shopee requested human verification. ArbiSwarm will not bypass that challenge."
                    )
                anchors = page.locator("a[href*='-i.'], a[href*='/product/']")
                listings: list[dict] = []
                seen: set[str] = set()
                for index in range(min(anchors.count(), limit * 5)):
                    item = _shopee_card_to_listing(anchors.nth(index))
                    if item and item["id"] not in seen:
                        seen.add(item["id"])
                        listings.append(item)
                    if len(listings) >= limit:
                        break
                if not listings:
                    raise MarketplaceSearchError(
                        "Shopee returned no readable public product cards. Try again later or use another source."
                    )
                return listings
            finally:
                browser.close()
    except MarketplaceSearchError:
        raise
    except PlaywrightTimeoutError as exc:
        raise MarketplaceSearchError("Shopee timed out before public results loaded.") from exc
    except Exception as exc:
        raise MarketplaceSearchError(f"Shopee public search failed: {exc}") from exc


def search_shopee(query: str, limit: int) -> list[dict]:
    if config.NEXSCOPE_API_KEY:
        return _search_shopee_provider(query, limit)
    return _search_shopee_browser(query, limit)


ADAPTERS = {
    "carousell": search_carousell,
    "lazada": search_lazada,
    "mudah": search_mudah,
    "shopee": search_shopee,
}


def search_many(query: str, selected: list[str], total_limit: int) -> tuple[list[dict], dict, list[dict]]:
    unknown = [name for name in selected if name not in ADAPTERS]
    if unknown:
        raise ValueError(f"unsupported marketplaces: {', '.join(unknown)}")
    per_source_limit = max(3, total_limit // max(1, len(selected)))
    all_listings: list[dict] = []
    counts: dict[str, int] = {}
    errors: list[dict] = []
    for name in selected:
        try:
            rows = ADAPTERS[name](query, per_source_limit)
            counts[name] = len(rows)
            all_listings.extend(rows)
        except (MarketplaceSearchError, carousell.MarketplaceError) as exc:
            counts[name] = 0
            errors.append({"marketplace": name, "message": str(exc)})
    return all_listings, counts, errors
