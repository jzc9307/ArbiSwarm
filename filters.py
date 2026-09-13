"""Phase 1: Hard-Filter Logic. Pure code, 0 tokens spent."""
import json
from schemas import Listing
import config


def load_listings(path: str = config.CACHE_PATH) -> list[Listing]:
    with open(path) as f:
        raw = json.load(f)
    return [Listing(**item) for item in raw]


def hard_filter(listings: list[Listing]) -> tuple[list[Listing], list[dict]]:
    """Drop overpriced / low-rated / empty listings before any AI call.
    Returns (kept, discarded_with_reason)."""
    kept, discarded = [], []
    for l in listings:
        if l.price > config.MAX_PRICE_MYR:
            discarded.append({"id": l.id, "reason": f"price {l.price} > max {config.MAX_PRICE_MYR}"})
            continue
        if l.seller_rating < config.MIN_SELLER_RATING:
            discarded.append({"id": l.id, "reason": f"rating {l.seller_rating} < min {config.MIN_SELLER_RATING}"})
            continue
        if not l.description.strip():
            discarded.append({"id": l.id, "reason": "empty description"})
            continue
        kept.append(l)
    return kept, discarded


if __name__ == "__main__":
    listings = load_listings()
    kept, discarded = hard_filter(listings)
    print(f"Kept {len(kept)} / {len(listings)}. Discarded: {discarded}")
