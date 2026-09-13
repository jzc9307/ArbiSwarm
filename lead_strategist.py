from schemas import Listing, ContextAnalysis, VisionCheck, StrategistDecision
from agents._llm import call_json
import config

SYSTEM_PROMPT = """You are the Lead Strategist in an e-commerce arbitrage swarm.
You receive: the listing, the Context Analyst's condition report, and the Vision
Authenticator's photo-consistency score. Combine these with the margin math you're given
to decide if this is a good flip, and if so, draft a short, casual, polite negotiation
message referencing the SPECIFIC flaw found (e.g. "since the box is dented, would you take RM 50?").
If margin is below threshold or red flags are severe, is_profitable = false and skip the message."""


def calc_margin_pct(listing_price: float, resale_estimate: float) -> float:
    fees = listing_price * config.PLATFORM_FEE_PCT + config.SHIPPING_COST_MYR
    cost = listing_price + fees
    return round(((resale_estimate - cost) / cost) * 100, 1)


def decide(listing: Listing, analysis: ContextAnalysis, vision: VisionCheck, resale_estimate: float) -> StrategistDecision:
    margin_pct = calc_margin_pct(listing.price, resale_estimate)
    user_content = (
        f"Listing: {listing.title}, price RM{listing.price}\n"
        f"Context Analysis: {analysis.model_dump_json()}\n"
        f"Vision Check: {vision.model_dump_json()}\n"
        f"Calculated margin: {margin_pct}% (min required: {config.MIN_MARGIN_PCT_TO_ALERT}%)\n"
        f"Listing ID: {listing.id}"
    )
    decision = call_json(SYSTEM_PROMPT, user_content, StrategistDecision)
    decision.estimated_margin_pct = margin_pct  # trust the math, not the LLM's arithmetic
    decision.is_profitable = margin_pct >= config.MIN_MARGIN_PCT_TO_ALERT
    return decision
