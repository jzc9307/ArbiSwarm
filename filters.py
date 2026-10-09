"""Fast deterministic validation before any model call."""
import json
import re
from pathlib import Path

import config
from schemas import Listing
from intelligence import identity_reason, lego_model_ids
from search_intent import query_terms, SearchIntent, plan_search


def load_listings(path: str | Path = config.CACHE_PATH, query: str | None = None) -> list[Listing]:
    with Path(path).open(encoding="utf-8") as handle:
        listings = [Listing(**item) for item in json.load(handle)]
    if not query:
        return listings
    terms = _terms(query)
    return [item for item in listings if _is_relevant(item, terms)]


def _terms(text: str) -> set[str]:
    return query_terms(text)


def _is_relevant(listing: Listing, query_terms: set[str], intent: SearchIntent | None = None) -> bool:
    if not query_terms:
        return False
    if intent:
        return intent.matches(listing.title, listing.description, query_terms)
    haystack = _terms(f"{listing.title} {listing.description}")
    return query_terms.issubset(haystack)


def hard_filter(
    listings: list[Listing],
    *,
    query: str | None = None,
    max_price: float | None = None,
    match_mode: str = 'exact',
    intent: SearchIntent | None = None,
) -> tuple[list[Listing], list[dict]]:
    kept: list[Listing] = []
    discarded: list[dict] = []
    price_limit = config.MAX_PRICE_MYR if max_price is None else max_price
    query_terms = _terms(query or "")
    if query and intent is None:
        intent = plan_search(query, use_ai=False)
    if query and lego_model_ids(query):
        query_terms -= {'big', 'large', 'version', 'ucs', 'complete', 'full', 'set', 'exact', 'only'}

    for listing in listings:
        reason: str | None = None
        if not listing.source_verified:
            reason = "unverified source URL"
        elif query and match_mode == 'exact' and identity_reason(listing.title, query, listing.description):
            reason = identity_reason(listing.title, query, listing.description)
        elif query_terms and not _is_relevant(listing, query_terms, intent):
            reason = "not relevant to the search query"
        elif listing.price > price_limit:
            reason = f"price RM{listing.price:.2f} exceeds RM{price_limit:.2f}"
        elif listing.seller_rating is not None and listing.seller_rating < config.MIN_SELLER_RATING:
            reason = f"seller rating {listing.seller_rating:.1f} is below {config.MIN_SELLER_RATING:.1f}"
        elif not listing.title.strip():
            reason = "missing title"

        if reason:
            discarded.append({"id": listing.id, "title": listing.title, "reason": reason})
        else:
            kept.append(listing)

    return kept, discarded
