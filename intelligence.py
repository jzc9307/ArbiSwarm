"""Deterministic cross-market matching, valuation, and trust signals."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha1
from math import log10
from statistics import median, quantiles
import re

from schemas import Listing
from search_intent import normalize_text, season_key


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
    model_ids: tuple[str, ...] = ()
    format: str | None = None
    season: str | None = None
    audience: str | None = None
    style: str | None = None


def lego_model_ids(text: str) -> tuple[str, ...]:
    # Piece counts, years and prices are not set numbers. Only LEGO/Star Wars
    # context enables this detector; counts followed by pcs/pieces are ignored.
    text = re.sub(r'(lego)(?=\d{5}\b)', r'\1 ', text, flags=re.I)
    if not re.search(r"lego|star\s*wars|falcon", text, re.I):
        return ()
    return tuple(sorted(set(re.findall(r"\b([1-9]\d{4})\b(?!\s*(?:pcs|pieces))", text, re.I))))


@dataclass
class ListingGroup:
    group_id: str
    name: str
    profile: VariantProfile
    listings: list[Listing] = field(default_factory=list)


def _tokens(text: str) -> set[str]:
    text = normalize_text(text)
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
    model_ids = lego_model_ids(title)
    lego = bool(re.search(r"lego|star\s*wars|falcon", lowered))
    format = ('small' if re.search(r"\b(?:mini|micro|midi|small|miniature)\b", lowered)
              else 'ucs' if re.search(r"\bucs\b|ultimate collector|\bbig version\b|\blarge (?:model|version)\b", lowered) else None)
    season = season_key(title)
    audience = ('kids' if re.search(r"\b(?:kids?|children|junior|youth)\b", lowered)
                else 'women' if re.search(r"\bwom[ae]n|\bladies\b", lowered)
                else 'men' if re.search(r"\bmen|\badult\b", lowered) else None)
    styles = [word for word in ('home', 'away', 'third') if re.search(r'\b' + word + r'\b', lowered)]
    style = styles[0] if len(styles) == 1 else ('mixed' if styles else None)

    accessory = bool(tokens & ACCESSORY_WORDS) and not ("blind" in tokens and "box" in tokens)
    compatible = bool(tokens & COMPATIBLE_WORDS) or "compatible with" in lowered
    explicit_full_set = (
        "full set" in lowered or "whole set" in lowered or "complete set" in lowered
        or bool(re.search(r"\b(?:6|12)\s*(?:pcs|pieces|boxes)\b", lowered))
    )
    figure_mention = bool(re.search(r"\bmini\s*fig(?:ure)?s?\b|\bfigures? only\b", lowered))
    included_figures = re.search(r"\b(?:with|includes?|including)\s+(?:\d+\s+)?minifig", lowered)
    minifigure_only = lego and figure_mention and not (
        included_figures or (explicit_full_set and not re.search(r'\bonly\b',lowered))
    )
    incomplete = lego and bool(re.search(r"\bincomplete\b|\bmissing (?:parts|pieces|minifigures)\b|\bparts only\b|\b(?:no|without) minifig", lowered))
    if incomplete:
        minifigure_only = False
    if accessory:
        kind, label = 'accessory', 'Accessory'
        warning = 'Accessory listing—do not compare it with the main product.'
    elif compatible:
        kind, label = 'compatible', 'Compatible / third-party'
        warning = 'Third-party or compatible product—not equivalent to the original branded item.'
    elif minifigure_only:
        kind, label = 'minifigure', 'Minifigure / figures only'
        warning = 'Figures are not the complete building set.'
    elif incomplete:
        kind, label = 'incomplete', 'Incomplete / parts'
        warning = 'Missing parts; complete-set prices are not comparable.'
    elif lego and (model_ids or 'falcon' in tokens):
        kind = 'small_model' if format == 'small' else 'building_set'
        label = ('Small-scale model' if format == 'small' else 'Building set') + (f" · {', '.join(model_ids)}" if model_ids else '')
        warning = 'Title-based identity only; confirm the set number and included pieces.'
    elif explicit_full_set:
        kind = "full_set"
        label = "Full set"
        warning = "Full-set pricing is isolated from single boxes and characters."
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
        model_ids=model_ids, format=format, season=season, audience=audience, style=style,
    )


def description_product_kind(description: str) -> str | None:
    if re.search(r'\b(?:only\s+mini\s*fig(?:ure)?s?|mini\s*fig(?:ure)?s?\s+only)\b',description,re.I):
        return 'minifigure'
    if re.search(r'\b(?:only (?:lighting|led) kit|(?:lighting|led) kit only|display (?:case|stand) only)\b',description,re.I):
        return 'accessory'
    if re.search(r'\bincomplete\b|\bmissing (?:parts|pieces|minifigures)\b',description,re.I):
        return 'incomplete'
    return None


def identity_reason(title: str, query: str, description: str = '') -> str | None:
    """Conservative exact-product intent checks; never authenticate a product."""
    wanted, actual = profile_variant(query), profile_variant(title)
    stated_kind = description_product_kind(description)
    main_product = bool(wanted.tokens & {'jersey', 'phone', 'smartphone', 'iphone', 'headphone', 'headphones', 'earbuds', 'laptop', 'notebook', 'television', 'tv', 'controller', 'gamepad'})
    if main_product and wanted.kind != 'accessory' and actual.kind == 'accessory':
        return 'accessory, not the requested main product'
    if wanted.model_ids:
        if actual.model_ids != wanted.model_ids:
            return f"set number does not match {', '.join(wanted.model_ids)} in the title"
        if wanted.kind == 'building_set' and actual.kind != 'building_set':
            return f"{actual.label}: not the requested complete building set"
        if wanted.kind == 'building_set' and stated_kind:
            return f"seller description states {stated_kind}: not the requested complete building set"
    elif wanted.format == 'ucs' and actual.kind in {'small_model', 'minifigure', 'accessory', 'incomplete'}:
        return f"{actual.label}: not the requested UCS/main model"
    if wanted.season and actual.season != wanted.season:
        return f"season {wanted.season} is not established in the title"
    if wanted.style and wanted.style != 'mixed' and actual.style != wanted.style:
        return f"{wanted.style} variant is not established in the title"
    if wanted.audience and actual.audience != wanted.audience:
        return f"{wanted.audience} sizing is not established in the title"
    size = re.search(r"\b(?:size\s+(XS|S|M|L|XL|XXL|\dXL)|\b(XS|S|M|L|XL|XXL|\dXL)\s+size)\b", query, re.I)
    if size:
        value = next(bit for bit in size.groups() if bit).lower()
        if not re.search(r'\b' + re.escape(value) + r'\b', title, re.I):
            return f"size {value.upper()} is not confirmed in the title"
    return None


def _similar(left: VariantProfile, right: VariantProfile) -> bool:
    if left.kind != right.kind:
        return False
    # An exact model code beats fuzzy title overlap. Missing or multiple model
    # codes never inherit another model's valuation.
    if left.model_ids != right.model_ids:
        return False
    for field_name in ('season', 'audience', 'style'):
        if getattr(left, field_name) != getattr(right, field_name):
            return False
    if left.format and right.format and left.format != right.format:
        return False
    if left.edition != right.edition:
        return False
    if left.character != right.character:
        return False
    if len(left.model_ids) == 1 and left.kind == 'building_set':
        return True
    union = left.tokens | right.tokens
    score = len(left.tokens & right.tokens) / len(union) if union else 0
    return score >= 0.28


def group_listings(listings: list[Listing], query: str) -> list[ListingGroup]:
    groups: list[ListingGroup] = []
    for listing in listings:
        profile = profile_variant(listing.title)
        stated_kind = description_product_kind(listing.description)
        if stated_kind and profile.kind == 'building_set':
            profile.kind = stated_kind
            profile.label = {'minifigure':'Minifigures only', 'accessory':'Accessory', 'incomplete':'Incomplete / parts'}[stated_kind]
            profile.warning = 'Seller description indicates a different product scope; complete-set prices are not comparable.'
        match = next((group for group in groups if _similar(profile, group.profile)), None)
        if match:
            match.listings.append(listing)
            if len(listing.title) < len(match.name):
                match.name = listing.title
            continue
        signature = f"{query.lower()}|{profile.kind}|{profile.model_ids}|{profile.format}|{profile.season}|{profile.audience}|{profile.style}|{profile.edition}|{profile.character}|{' '.join(sorted(profile.tokens))}"
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
