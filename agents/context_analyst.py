import re

from schemas import ContextAnalysis, Listing
from agents._llm import call_json, is_enabled

SYSTEM_PROMPT = """You are the Context Analyst in an e-commerce arbitrage system.
Extract only claims supported by the seller's text. Never infer authenticity. Return:
true_condition, flaws_found, missing_parts, red_flags, and needs_clarification.
Treat vague copy, stock-photo claims, off-platform contact, deposits, and no-return
language as risks. If details are missing, say so instead of inventing them."""

_FLAWS = {
    "dented": "dented packaging",
    "scratch": "scratches mentioned",
    "damaged": "damage mentioned",
    "stain": "stains mentioned",
    "crack": "cracks mentioned",
    "defect": "defect mentioned",
}
_RED_FLAGS = {
    "no return": "seller says no returns",
    "as is": "sold as-is",
    "deposit": "deposit requested",
    "whatsapp": "asks to move conversation off-platform",
    "telegram": "asks to move conversation off-platform",
    "stock photo": "stock photos mentioned",
}


def _deterministic(listing: Listing) -> ContextAnalysis:
    text = f"{listing.title} {listing.description}".lower()
    flaws = [label for word, label in _FLAWS.items() if word in text]
    red_flags = [label for phrase, label in _RED_FLAGS.items() if phrase in text]
    missing: list[str] = []
    if re.search(r"missing|incomplete|not included|without (?:box|card|accessor)", text):
        missing.append("listing indicates missing or incomplete parts")

    if any(word in text for word in ("sealed", "brand new", "unopened", "new in box")):
        condition = "New / sealed"
    elif any(word in text for word in ("damaged", "broken", "crack", "defect")):
        condition = "Damaged"
    elif any(word in text for word in ("used", "preloved", "pre-loved")):
        condition = "Used"
    elif listing.condition:
        condition = listing.condition.replace("_", " ").title()
    else:
        condition = "Unclear"

    vague = len(listing.description.strip()) < 35 or listing.description.strip() == listing.title.strip()
    if vague:
        red_flags.append("description is too thin to verify condition")
    return ContextAnalysis(
        true_condition=condition,
        flaws_found=list(dict.fromkeys(flaws)),
        missing_parts=missing,
        red_flags=list(dict.fromkeys(red_flags)),
        needs_clarification=vague,
    )


def analyze(listing: Listing) -> ContextAnalysis:
    if is_enabled():
        try:
            return call_json(
                SYSTEM_PROMPT,
                f"Title: {listing.title}\nCondition field: {listing.condition or 'unknown'}\n"
                f"Seller description: {listing.description or 'not provided'}",
                ContextAnalysis,
            )
        except Exception:
            pass
    return _deterministic(listing)
