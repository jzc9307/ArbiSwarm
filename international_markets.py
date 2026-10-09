"""Official eBay/Etsy search adapters, with explicit MYR conversion evidence.

International asks are comparison evidence, not landed-cost buy signals: import
taxes, payment FX spreads and destination shipping require checkout verification.
"""
import math
import re
import threading
import time
from urllib.parse import urlparse

import httpx
import config


class InternationalSearchError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


_lock = threading.Lock()
_fx_cache: dict[str, tuple[float, str, float]] = {}
_token_cache: tuple[tuple[str, str], str, float] | None = None


def _json_request(method: str, url: str, *, service: str, **kwargs) -> dict:
    """Never relay credential-bearing URLs, headers, or raw upstream bodies."""
    try:
        response = httpx.request(method, url, timeout=20, **kwargs)
        if response.status_code >= 400:
            raise InternationalSearchError(f'{service} returned HTTP {response.status_code}. Check credentials, access approval, or service quota.', response.status_code)
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError('expected object')
        return body
    except InternationalSearchError:
        raise
    except (httpx.HTTPError, ValueError):
        raise InternationalSearchError(f'{service} did not return a usable response. Try again later.') from None


def _number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def _myr_money(amount: dict) -> tuple[float, float, str, float, str] | None:
    if not isinstance(amount, dict):
        return None
    currency = str(amount.get('currency') or amount.get('currency_code') or '').upper()
    value = _number(amount.get('value', amount.get('amount')))
    if value is None or not re.fullmatch(r'[A-Z]{3}', currency):
        return None
    if 'divisor' in amount:
        divisor = _number(amount['divisor'])
        if not divisor:
            return None
        value /= divisor
    if currency == 'MYR':
        return round(value, 2), value, currency, 1.0, ''
    with _lock:
        cached = _fx_cache.get(currency)
    if not cached or cached[2] <= time.monotonic():
        body = _json_request('GET', 'https://api.frankfurter.dev/v1/latest', service='Currency conversion', params={'base': currency, 'symbols': 'MYR'})
        rates = body.get('rates')
        rate = _number(rates.get('MYR')) if isinstance(rates, dict) else None
        date = str(body.get('date') or '')
        if not rate or not date:
            raise InternationalSearchError(f'No verified {currency}→MYR rate is available. Prices were not guessed.')
        cached = (rate, date, time.monotonic() + 3600)
        with _lock:
            _fx_cache[currency] = cached
    return round(value * cached[0], 2), value, currency, cached[0], cached[1]


def _ebay_token(force: bool = False) -> str:
    global _token_cache
    identity = (config.EBAY_CLIENT_ID, config.EBAY_CLIENT_SECRET)
    if not all(identity):
        raise InternationalSearchError('eBay needs EBAY_CLIENT_ID and EBAY_CLIENT_SECRET with Browse API access.')
    # One token mint across concurrent searches, not one token per alias/item.
    with _lock:
        if not force and _token_cache and _token_cache[0] == identity and _token_cache[2] > time.monotonic():
            return _token_cache[1]
        body = _json_request('POST', 'https://api.ebay.com/identity/v1/oauth2/token', service='eBay authorization', auth=identity,
            data={'grant_type': 'client_credentials', 'scope': 'https://api.ebay.com/oauth/api_scope'},
            headers={'content-type': 'application/x-www-form-urlencoded'})
        token = body.get('access_token')
        lifetime = _number(body.get('expires_in'))
        if not isinstance(token, str) or not token or not lifetime or lifetime <= 60:
            raise InternationalSearchError('eBay did not return a usable application token.')
        _token_cache = (identity, token, time.monotonic() + lifetime - 60)
        return token


def _safe_product_url(url, marketplace: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    hosts = {'ebay.com', 'www.ebay.com', 'ebay.co.uk', 'www.ebay.co.uk', 'ebay.com.au', 'www.ebay.com.au', 'ebay.com.sg', 'www.ebay.com.sg'} if marketplace == 'ebay' else {'etsy.com', 'www.etsy.com'}
    path = r'/itm/(?:[^/]+/)?\d+/?$' if marketplace == 'ebay' else r'/listing/\d+(?:/[^/]*)?/?$'
    return parsed.scheme == 'https' and not parsed.username and parsed.hostname in hosts and bool(re.fullmatch(path, parsed.path))


def _record(*, record: dict, market: str, money: tuple, title: str, url: str, images: list, seller: str | None, condition: str | None, description: str, shipping: float | None = None) -> dict:
    converted, original, currency, rate, date = money
    return {
        'id': str(record.get('itemId') if market == 'ebay' else record.get('listing_id')),
        'title': title[:300], 'url': url, 'price': converted,
        'description': description[:1800], 'image_urls': images,
        'seller_name': seller, 'seller_rating': None, 'condition': condition,
        'marketplace': market, 'source': f'{market}_api', 'source_verified': True,
        'original_price': original, 'original_currency': currency, 'fx_rate_to_myr': rate,
        'fx_rate_date': date or None, 'shipping_cost_myr': shipping,
        'landed_cost_verified': False,
        'cost_warning': 'International asking price. Delivery to Malaysia, import taxes and payment FX charges need checkout verification. Not a landed-cost buy recommendation.',
    }


def search_ebay(query: str, limit: int) -> list[dict]:
    token = _ebay_token()
    headers = {'authorization': f'Bearer {token}', 'X-EBAY-C-MARKETPLACE-ID': config.EBAY_MARKETPLACE_ID,
        'X-EBAY-C-ENDUSERCTX': 'contextualLocation=country%3DMY'}
    params = {'q': query, 'limit': min(max(1, limit), 200), 'filter': 'buyingOptions:{FIXED_PRICE},deliveryCountry:MY'}
    try:
        body = _json_request('GET', 'https://api.ebay.com/buy/browse/v1/item_summary/search', service='eBay search', headers=headers, params=params)
    except InternationalSearchError as exc:
        if exc.status_code != 401:
            raise
        # A revoked/expired cached application token gets one fresh mint, never
        # a retry loop. Invalid client credentials still fail independently.
        headers['authorization'] = f'Bearer {_ebay_token(force=True)}'
        body = _json_request('GET', 'https://api.ebay.com/buy/browse/v1/item_summary/search', service='eBay search', headers=headers, params=params)
    rows = []
    records = body.get('itemSummaries', [])
    if not isinstance(records, list):
        raise InternationalSearchError('eBay returned an unexpected search format.')
    for record in records:
        if not isinstance(record, dict):
            continue
        url, title = record.get('itemWebUrl'), str(record.get('title') or '').strip()
        if not record.get('itemId') or not title or not _safe_product_url(url, 'ebay'):
            continue
        if record.get('buyingOptions') and 'FIXED_PRICE' not in record['buyingOptions']:
            continue
        money = _myr_money(record.get('price', {}))
        if not money or money[0] <= 0:
            continue
        images = [img.get('imageUrl') for img in [record.get('image', {}), *(record.get('additionalImages') or [])] if isinstance(img, dict) and str(img.get('imageUrl', '')).startswith('https://')][:5]
        seller = record.get('seller') if isinstance(record.get('seller'), dict) else {}
        description = [title]
        if seller.get('feedbackScore') is not None:
            description.append(f"Seller feedback count: {seller['feedbackScore']} (not a five-star rating)")
        if seller.get('feedbackPercentage') is not None:
            description.append(f"Seller positive feedback: {seller['feedbackPercentage']}%")
        shipping = None
        for option in record.get('shippingOptions') or []:
            if isinstance(option, dict) and option.get('shippingCostType') == 'FIXED':
                converted = _myr_money(option.get('shippingCost', {}))
                if converted:
                    shipping = converted[0] if shipping is None else min(shipping, converted[0])
        rows.append(_record(record=record, market='ebay', money=money, title=title, url=url, images=images,
            seller=seller.get('username'), condition=record.get('condition'), description='. '.join(description), shipping=shipping))
    return rows[:limit]


def search_etsy(query: str, limit: int) -> list[dict]:
    if not config.ETSY_API_KEY or not config.ETSY_SHARED_SECRET:
        raise InternationalSearchError('Etsy needs ETSY_API_KEY and ETSY_SHARED_SECRET with approved API access.')
    headers = {'x-api-key': f'{config.ETSY_API_KEY}:{config.ETSY_SHARED_SECRET}'}
    body = _json_request('GET', 'https://api.etsy.com/v3/application/listings/active', service='Etsy search',
        headers=headers, params={'keywords': query, 'limit': min(max(1, limit), 100), 'buyer_country': 'MY'})
    records = body.get('results', [])
    if not isinstance(records, list):
        raise InternationalSearchError('Etsy returned an unexpected search format.')
    # The active-listings endpoint does NOT support includes=Images. Enrich in
    # one documented batch call, instead of N image requests or fake thumbnails.
    ids = [str(record['listing_id']) for record in records if isinstance(record, dict) and str(record.get('listing_id', '')).isdigit()]
    if ids:
        try:
            enriched = _json_request('GET', 'https://api.etsy.com/v3/application/listings/batch', service='Etsy image evidence',
                headers=headers, params={'listing_ids': ','.join(ids[:100]), 'includes': 'Images', 'buyer_country': 'MY'})
            lookup = {str(item.get('listing_id')): item for item in enriched.get('results', []) if isinstance(item, dict)}
            records = [{**record, **lookup.get(str(record.get('listing_id')), {})} if isinstance(record, dict) else record for record in records]
        except InternationalSearchError:
            pass  # Missing images are truthful placeholders, not search failure.
    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        url, title = record.get('url'), str(record.get('title') or '').strip()
        if not record.get('listing_id') or not title or not _safe_product_url(url, 'etsy'):
            continue
        # Digital patterns/downloads are not physical resale inventory.
        if record.get('is_digital') or record.get('listing_type') == 'download':
            continue
        money = _myr_money(record.get('price', {}))
        if not money or money[0] <= 0:
            continue
        images = [img.get('url_570xN') or img.get('url_fullxfull') for img in record.get('images', record.get('Images', [])) or [] if isinstance(img, dict)]
        images = [img for img in images if isinstance(img, str) and img.startswith('https://')][:5]
        rows.append(_record(record=record, market='etsy', money=money, title=title, url=url, images=images, seller=None,
            condition=None,
            description=str(record.get('description') or title)))
    return rows[:limit]
