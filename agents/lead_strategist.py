from pydantic import BaseModel

from schemas import ContextAnalysis, Listing, StrategistDecision, VisionCheck
from agents._llm import call_json, is_enabled
import config

SYSTEM_PROMPT = """You are the final strategist. Explain a deterministic arbitrage
decision in plain language and draft one short, polite negotiation message only when
the candidate passed. Never change the supplied financial calculations or claim that
photos prove authenticity. Return JSON with reasoning and negotiation_message."""


class Narrative(BaseModel):
    reasoning: str
    negotiation_message: str | None = None


def calc_economics(listing_price: float, resale_estimate: float) -> tuple[float, float, float]:
    # The platform fee is paid on the resale transaction, not on the purchase.
    total_cost = listing_price + config.SHIPPING_COST_MYR + resale_estimate * config.PLATFORM_FEE_PCT
    profit = resale_estimate - total_cost
    margin_pct = (profit / total_cost * 100) if total_cost else -100.0
    return round(total_cost, 2), round(profit, 2), round(margin_pct, 1)


def calc_margin_pct(listing_price: float, resale_estimate: float) -> float:
    return calc_economics(listing_price, resale_estimate)[2]


def _fallback_narrative(
    listing: Listing,
    analysis: ContextAnalysis,
    margin: float,
    profitable: bool,
) -> Narrative:
    evidence = []
    if analysis.flaws_found:
        evidence.append(analysis.flaws_found[0])
    if analysis.red_flags:
        evidence.append(analysis.red_flags[0])
    evidence_text = f" Key evidence: {', '.join(evidence)}." if evidence else ""
    if profitable:
        target = max(1, round(listing.price * 0.9))
        flaw = analysis.flaws_found[0] if analysis.flaws_found else "the current asking price"
        return Narrative(
            reasoning=f"The verified listing clears the {config.MIN_MARGIN_PCT_TO_ALERT:.0f}% margin rule at {margin:.1f}%.{evidence_text}",
            negotiation_message=f"Hi! Considering {flaw}, would you be open to RM{target}? I can arrange the deal promptly.",
        )
    return Narrative(
        reasoning=f"This listing does not clear the risk-adjusted margin rule; calculated margin is {margin:.1f}%.{evidence_text}",
        negotiation_message=None,
    )


def decide(
    listing: Listing,
    analysis: ContextAnalysis,
    vision: VisionCheck,
    resale_estimate: float,
) -> StrategistDecision:
    total_cost, profit, margin = calc_economics(listing.price, resale_estimate)
    retail_evidence_risk = (
        listing.marketplace in {"lazada", "shopee"}
        and (
            (listing.review_count or 0) < 5
            or (listing.price < resale_estimate * 0.35 and (listing.review_count or 0) < 20)
        )
    )
    hard_risk = bool(analysis.missing_parts) or len(analysis.red_flags) >= 2 or retail_evidence_risk
    vision_risk = vision.consistency_score is not None and vision.consistency_score < 45
    profitable = (
        listing.source_verified
        and margin >= config.MIN_MARGIN_PCT_TO_ALERT
        and profit > 0
        and not hard_risk
        and not vision_risk
    )
    risk = "high" if hard_risk or vision_risk else ("medium" if analysis.red_flags or vision.consistency_score is None else "low")
    narrative = _fallback_narrative(listing, analysis, margin, profitable)

    if is_enabled():
        try:
            narrative = call_json(
                SYSTEM_PROMPT,
                f"Listing: {listing.title}; asking RM{listing.price:.2f}; resale RM{resale_estimate:.2f}\n"
                f"Total cost: RM{total_cost:.2f}; profit: RM{profit:.2f}; margin: {margin:.1f}%\n"
                f"Passed deterministic rules: {profitable}\nContext: {analysis.model_dump_json()}\n"
                f"Vision: {vision.model_dump_json()}",
                Narrative,
            )
        except Exception:
            pass

    return StrategistDecision(
        listing_id=listing.id,
        is_profitable=profitable,
        estimated_margin_pct=margin,
        estimated_profit_myr=profit,
        total_cost_myr=total_cost,
        # Retail marketplaces use fixed/cart pricing; negotiation copy is only
        # useful on peer-to-peer classifieds.
        negotiation_message=(
            narrative.negotiation_message
            if profitable and listing.marketplace in {"carousell", "mudah"}
            else None
        ),
        reasoning=narrative.reasoning,
        risk_level=risk,
    )
