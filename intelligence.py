"""Deterministic cross-market matching, valuation, and trust signals."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from math import log10
from statistics import median, quantiles
import re

from schemas import Listing


STOP_WORDS = {
    "a", "an", "and", "authentic", "brand", "buy", "collection", "decorative",
    "fast", "for", "free", "gift", "in", "item", "limited", "malaysia", "new",
    "of", "on", "original", "ready", "sale", "series", "stock", "the", "to",
    "with", "wts", "wtt", "100", "official", "assembl", "assembly", "building",
    "blocks", "block", "construction", "difficulty", "high", "kids", "large",
    "male", "pieces", "scale", "toy", "toys", "ultimate", "ucs",
}
ACCESSORY_WORDS = {
    "case", "clothes", "display", "hanger", "keychain", "outfit", "protector",
    "replacement", "sticker", "strap", "stand", "storage", "light", "lighting",
    "led", "manual", "instructions", "motor",
}
COMPATIBLE_WORDS = {"compatible", "moc", "replica", "clone", "simbricks", "unbranded"}
FULL_SET_WORDS = {"case", "set", "whole", "complete", "tray", "12pcs", "6pcs", "boxset"}
SINGLE_WORDS = {"single", "opened", "confirmed", "character", "loose", "piece", "pcs"}
BLIND_WORDS = {"blind", "random", "sealed", "unopened"}
CHARACTER_PHRASES = (
    "sea salt coconut", "lychee berry", "toffee", "soy milk", "green grape",
    "sesame bean", "secret", "chaser",
)


@dataclass
class VariantProfile:
    kind: str
    label: str
    warning: str | None
    edition: str | None
    character: str | None
    tokens: set[str]


@dataclass
class ListingGroup:
    group_id: str
    name: str
    profile: VariantProfile
    listings: list[Listing] = field(default_factory=list)


def _tokens(text: str) -> set[str]:
    text = re.sub(r"\bstarwars\b", "star wars", text, flags=re.I)
    text = re.sub(r"\bmillenniumfalcon\b", "millennium falcon", text, flags=re.I)
    return {
        token for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in STOP_WORDS
    }


def profile_variant(title: str) -> VariantProfile:
    lowered = title.lower()
    tokens = _tokens(title)
    edition_match = re.search(r"\b(?:v|version)\s*([1-9])\b", lowered)
    edition = f"V{edition_match.group(1)}" if edition_match else None
    character = next((phrase.title() for phrase in CHARACTER_PHRASES if phrase in lowered), None)

    accessory = bool(tokens & ACCESSORY_WORDS) and not ("blind" in tokens and "box" in tokens)
    compatible = bool(tokens & COMPATIBLE_WORDS) or "compatible with" in lowered
    explicit_full_set = (
        "full set" in lowered or "whole set" in lowered or "complete set" in lowered
        or bool(re.search(r"\b(?:6|12)\s*(?:pcs|pieces|boxes)\b", lowered))
    )
    if explicit_full_set and not compatible:
        kind = "full_set"
        label = "Full set"
        warning = "Full-set pricing is isolated from single boxes and characters."
    elif accessory:
        kind = "accessory"
        label = "Accessory"
        warning = "Accessory listing—do not compare it with the main collectible."
    elif compatible:
        kind = "compatible"
        label = "Compatible / third-party"
        warning = "Third-party or compatible product—not equivalent to the original branded item."
    elif tokens & SINGLE_WORDS or character:
        kind = "single"
        label = character or "Single / confirmed item"
        warning = "Confirmed or opened character; not equivalent to a random sealed box."
    elif tokens & BLIND_WORDS or "blind box" in lowered:
        kind = "blind_box"
        label = "Sealed blind box"
        warning = "Character may be random; compare only with other single blind boxes."
    else:
        kind = "unclear"
        label = "Variant unclear"
        warning = "Pack size or exact variant is unclear; verify before buying."

    label_bits = [bit for bit in (edition, label) if bit]
    return VariantProfile(
        kind=kind,
        label=" · ".join(label_bits),
        warning=warning,
        edition=edition,
        character=character,
        tokens=tokens,
    )


def _similar(left: VariantProfile, right: VariantProfile) -> bool:
    if left.kind != right.kind:
        return False
    if left.edition and right.edition and left.edition != right.edition:
        return False
    if left.character and right.character and left.character != right.character:
        return False
    union = left.tokens | right.tokens
    score = len(left.tokens & right.tokens) / len(union) if union else 0
    return score >= 0.28


def group_listings(listings: list[Listing], query: str) -> list[ListingGroup]:
    groups: list[ListingGroup] = []
    for listing in listings:
        profile = profile_variant(listing.title)
        match = next((group for group in groups if _similar(profile, group.profile)), None)
        if match:
            match.listings.append(listing)
            if len(listing.title) < len(match.name):
                match.name = listing.title
            continue
        signature = f"{query.lower()}|{profile.kind}|{profile.edition}|{profile.character}|{' '.join(sorted(profile.tokens))}"
        groups.append(ListingGroup(
            group_id=sha1(signature.encode("utf-8")).hexdigest()[:12],
            name=listing.title,
            profile=profile,
            listings=[listing],
        ))
    return groups


def price_band(prices: list[float]) -> dict:
    clean = sorted(float(price) for price in prices if price > 0)
    if not clean:
        return {"estimate": 0.0, "low": 0.0, "high": 0.0, "confidence": "low", "sample_size": 0}
    estimate = float(median(clean))
    if len(clean) >= 4:
        quartiles = quantiles(clean, n=4, method="inclusive")
        low, high = quartiles[0], quartiles[2]
    elif len(clean) > 1:
        low, high = clean[0], clean[-1]
    else:
        low, high = estimate * 0.9, estimate * 1.1
    dispersion = (high - low) / estimate if estimate else 1
    confidence = "high" if len(clean) >= 5 and dispersion <= 0.35 else (
        "medium" if len(clean) >= 3 and dispersion <= 0.7 else "low"
    )
    return {
        "estimate": round(estimate, 2),
        "low": round(low, 2),
        "high": round(high, 2),
        "confidence": confidence,
        "sample_size": len(clean),
    }


def seller_confidence(listing: Listing, resale_estimate: float, red_flags: list[str]) -> dict:
    score = 35
    reasons: list[str] = []
    if listing.source_verified:
        score += 12
        reasons.append("verified product URL")
    rating = listing.seller_rating or listing.listing_rating
    if rating is not None:
        score += round(max(0, min(20, rating / 5 * 20)))
        reasons.append(f"{rating:.1f}/5 rating evidence")
    else:
        reasons.append("rating unavailable")
    if listing.review_count:
        score += min(15, round(log10(listing.review_count + 1) * 6))
        reasons.append(f"{listing.review_count} reviews")
    if listing.sold_count:
        score += min(12, round(log10(listing.sold_count + 1) * 5))
        reasons.append(f"{listing.sold_count} sold")
    if resale_estimate and listing.price < resale_estimate * 0.35:
        score -= 18
        reasons.append("price is unusually far below market")
    if red_flags:
        score -= min(24, len(red_flags) * 8)
        reasons.append(f"{len(red_flags)} listing risk flag{'s' if len(red_flags) != 1 else ''}")
    score = max(0, min(100, score))
    label = "strong" if score >= 78 else ("established" if score >= 62 else ("limited" if score >= 42 else "caution"))
    return {"score": score, "label": label, "reasons": reasons[:4]}
