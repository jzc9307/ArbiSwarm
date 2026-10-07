"""FastAPI boundary for the ingestion, validation, and multi-agent pipeline."""
from pathlib import Path
from typing import Literal, Optional
from datetime import datetime, timezone
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

import config
from filters import hard_filter, load_listings
import marketplaces as marketplace_service
import notify
from intelligence import group_listings, price_band, seller_confidence
from orchestrator import run_swarm
from schemas import Listing
from copilot import ChatRequest, chat
from agents._llm import ai_status

logger = logging.getLogger("arbiswarm")
STATIC_DIR = Path(__file__).resolve().parent / "static"
APP_VERSION = "2.3.0"
app = FastAPI(title="ArbiSwarm API", version=APP_VERSION)


@app.middleware("http")
async def prevent_stale_app_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path in {"/static/app.js", "/static/style.css"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    pricing_mode: Literal["auto", "manual"] = "manual"
    match_mode: Literal['exact', 'related'] = 'exact'
    resale_estimate: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    max_purchase_price: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    source_mode: Literal["live", "demo"] = "live"
    marketplaces: list[Literal["carousell", "lazada", "mudah", "shopee"]] = Field(
        default_factory=lambda: ["carousell", "lazada", "mudah", "shopee"],
        min_length=1,
        max_length=4,
    )
    retained_market_listings: list[Listing] = Field(default_factory=list, max_length=200)
    retained_source_times: dict[str, datetime] = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("enter at least 2 characters")
        return cleaned

    @field_validator("marketplaces")
    @classmethod
    def unique_marketplaces(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def require_manual_resale(self):
        if self.pricing_mode == "manual" and self.resale_estimate is None:
            raise ValueError("manual pricing requires a resale estimate")
        return self


class DecisionOut(BaseModel):
    offer_id: str
    listing_id: str
    title: str
    url: str
    price: float
    image_url: Optional[str] = None
    seller_name: Optional[str] = None
    seller_rating: Optional[float] = None
    listing_rating: Optional[float] = None
    review_count: Optional[int] = None
    sold_count: Optional[int] = None
    marketplace: str
    source: str
    true_condition: str
    flaws_found: list[str]
    red_flags: list[str]
    vision_score: Optional[int]
    images_checked: int
    is_profitable: bool
    estimated_margin_pct: float
    estimated_profit_myr: float
    total_cost_myr: float
    risk_level: str
    reasoning: str
    negotiation_message: Optional[str] = None
    group_id: str
    group_name: str
    variant_label: str
    variant_kind: str
    variant_warning: Optional[str] = None
    resale_estimate_myr: float
    resale_low_myr: float
    resale_high_myr: float
    resale_confidence: str
    resale_sample_size: int
    seller_confidence_score: int
    seller_confidence_label: str
    seller_confidence_reasons: list[str]
    platform_fee_myr: float
    shipping_cost_myr: float
    decision_factors: list[str]
    collected_at: datetime


class ProductGroupOut(BaseModel):
    group_id: str
    name: str
    variant_label: str
    variant_kind: str
    variant_warning: Optional[str] = None
    offer_ids: list[str]
    offer_count: int
    marketplace_count: int
    marketplaces: list[str]
    lowest_price_myr: float
    median_price_myr: float
    highest_price_myr: float
    confidence: str


class SearchResponse(BaseModel):
    query: str
    source_mode: str
    provider: str
    pricing_mode: str
    match_mode: str = 'exact'
    matching_version: int = 2
    collected_at: datetime
    marketplaces: list[str]
    source_counts: dict[str, int]
    source_errors: list[dict]
    ai_mode: Literal["gemini", "deterministic"]
    total_scraped: int
    kept_after_filter: int
    discarded: list[dict]
    decisions: list[DecisionOut]
    product_groups: list[ProductGroupOut]
    market_listings: list[Listing] = Field(default_factory=list)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "version": APP_VERSION,
        "ai_mode": "gemini" if config.GEMINI_API_KEY else "deterministic",
        "ai_status": ai_status(),
        "marketplaces": {
            "carousell": "reef_api" if config.REEF_API_KEY else "direct_browser",
            "lazada": "public_json",
            "mudah": "reef_api" if config.REEF_API_KEY else "not_configured",
            "shopee": "nexscope_api" if config.NEXSCOPE_API_KEY else "public_browser_best_effort",
        },
    }


@app.post("/api/chat")
def copilot_chat(req: ChatRequest) -> dict:
    return chat(req)


@app.post("/api/search", response_model=SearchResponse)
def search(req: SearchRequest) -> SearchResponse:
    ingest_discarded: list[dict] = []
    if req.source_mode == "live":
        try:
            raw, source_counts, source_errors = marketplace_service.search_many(
                req.query, req.marketplaces, config.MAX_SEARCH_RESULTS
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_MARKETPLACE", "message": str(exc)},
            ) from exc
        if source_errors and len(source_errors) == len(req.marketplaces):
            message = "; ".join(f"{item['marketplace']}: {item['message']}" for item in source_errors)
            raise HTTPException(
                status_code=502,
                detail={"code": "ALL_MARKETPLACES_FAILED", "message": message},
            )
        listings = []
        for item in raw:
            try:
                listings.append(Listing(**item))
            except Exception as exc:
                ingest_discarded.append({
                    "id": str(item.get("id") or "unknown"),
                    "title": str(item.get("title") or "Invalid source record"),
                    "reason": f"source validation failed: {exc}",
                })
        provider = "multi_market" if len(req.marketplaces) > 1 else req.marketplaces[0]
        searched_marketplaces = req.marketplaces
    else:
        listings = load_listings(query=req.query)
        provider = "demo_cache"
        searched_marketplaces = ["carousell"]
        source_counts = {"carousell": len(listings)}
        source_errors = []

    # A source refresh carries the other sources' original records, including
    # above-budget comparables. Run the same matching/valuation pipeline again.
    if req.source_mode == "live" and req.retained_market_listings:
        retained = [item for item in req.retained_market_listings if item.marketplace not in req.marketplaces]
        listings.extend(retained)
        for market in sorted({item.marketplace for item in retained}):
            source_counts[market] = sum(item.marketplace == market for item in retained)
        searched_marketplaces = list(dict.fromkeys(req.marketplaces + [item.marketplace for item in retained]))
    listings = list({f"{item.marketplace}:{item.id}": item for item in listings}.values())
    collected_at = datetime.now(timezone.utc)
    # Keep a broad, validated comparison pool for fair-value estimation, then
    # apply the user's acquisition ceiling only to actionable offers.
    # The configurable MAX_PRICE_MYR is only a legacy UI default. It must never
    # silently override a user's explicit acquisition ceiling or remove higher
    # priced comparables from the valuation pool.
    market_pool, evidence_discarded = hard_filter(
        listings,
        query=req.query,
        max_price=float("inf"),
        match_mode=req.match_mode,
    )
    kept, price_discarded = hard_filter(
        market_pool,
        max_price=req.max_purchase_price if req.max_purchase_price is not None else float("inf"),
    )
    discarded = ingest_discarded + evidence_discarded + price_discarded

    groups = group_listings(market_pool, req.query)
    group_lookup: dict[str, tuple] = {}
    group_bands: dict[str, dict] = {}
    for group in groups:
        band = price_band([item.price for item in group.listings])
        group_bands[group.group_id] = band
        for item in group.listings:
            group_lookup[f"{item.marketplace}:{item.id}"] = (group, band)

    decisions: list[DecisionOut] = []
    for listing in kept:
        group, auto_band = group_lookup[f"{listing.marketplace}:{listing.id}"]
        if req.pricing_mode == "auto":
            resale_estimate = auto_band["estimate"]
            resale_low = auto_band["low"]
            resale_high = auto_band["high"]
            resale_confidence = auto_band["confidence"]
            resale_sample_size = auto_band["sample_size"]
        else:
            resale_estimate = float(req.resale_estimate)
            resale_low = resale_estimate
            resale_high = resale_estimate
            resale_confidence = "manual"
            resale_sample_size = 0
        try:
            decision, analysis, vision = run_swarm(listing, resale_estimate, include_evidence=True)
        except Exception as exc:
            logger.exception("Pipeline failed for listing %s", listing.id)
            discarded.append({"id": listing.id, "title": listing.title, "reason": f"analysis failed: {exc}"})
            continue

        trust = seller_confidence(listing, resale_estimate, analysis.red_flags)
        evidence_hold = None
        if req.pricing_mode == 'auto' and resale_confidence == 'low':
            evidence_hold = 'Not enough consistent comparable asking prices to recommend a buy.'
        if req.pricing_mode == 'auto' and resale_sample_size >= 3 and listing.price < resale_estimate * 0.35:
            evidence_hold = 'Ask is far below the comparison median. Confirm the exact item and included parts before treating this as a deal; price alone does not prove a fake.'
        if group.profile.kind in {'unclear', 'incomplete'} and req.pricing_mode == 'auto':
            evidence_hold = 'Product/pack identity is not established well enough for a buy recommendation.'
        if evidence_hold:
            decision.is_profitable = False
            decision.risk_level = 'high'
            decision.negotiation_message = None
            decision.reasoning = f'Needs verification: {evidence_hold} The displayed profit is hypothetical, not a buy signal.'
        factors = [
            "Product URL and marketplace provenance validated.",
            (
                f"Fair-value estimate uses {resale_sample_size} comparable listing"
                f"{'s' if resale_sample_size != 1 else ''}."
                if req.pricing_mode == "auto"
                else "Resale value was supplied manually."
            ),
            f"Variant classified as {group.profile.label.lower()}.",
            f"Seller confidence scored {trust['score']}/100 ({trust['label']}).",
            (
                f"Margin clears the {config.MIN_MARGIN_PCT_TO_ALERT:.0f}% rule."
                if decision.estimated_margin_pct >= config.MIN_MARGIN_PCT_TO_ALERT
                else f"Margin is below the {config.MIN_MARGIN_PCT_TO_ALERT:.0f}% rule."
            ),
        ]
        if group.profile.warning:
            factors.append(group.profile.warning)
        if evidence_hold:
            factors.append(evidence_hold)

        decisions.append(
            DecisionOut(
                offer_id=f"{listing.marketplace}:{listing.id}",
                listing_id=listing.id,
                title=listing.title,
                url=listing.url,
                price=listing.price,
                image_url=listing.image_urls[0] if listing.image_urls else None,
                seller_name=listing.seller_name,
                seller_rating=listing.seller_rating,
                listing_rating=listing.listing_rating,
                review_count=listing.review_count,
                sold_count=listing.sold_count,
                marketplace=listing.marketplace,
                source=listing.source,
                true_condition=analysis.true_condition,
                flaws_found=analysis.flaws_found,
                red_flags=analysis.red_flags,
                vision_score=vision.consistency_score,
                images_checked=vision.images_checked,
                is_profitable=decision.is_profitable,
                estimated_margin_pct=decision.estimated_margin_pct,
                estimated_profit_myr=decision.estimated_profit_myr,
                total_cost_myr=decision.total_cost_myr,
                risk_level=decision.risk_level,
                reasoning=decision.reasoning,
                negotiation_message=decision.negotiation_message,
                group_id=group.group_id,
                group_name=group.name,
                variant_label=group.profile.label,
                variant_kind=group.profile.kind,
                variant_warning=group.profile.warning,
                resale_estimate_myr=resale_estimate,
                resale_low_myr=resale_low,
                resale_high_myr=resale_high,
                resale_confidence=resale_confidence,
                resale_sample_size=resale_sample_size,
                seller_confidence_score=trust["score"],
                seller_confidence_label=trust["label"],
                seller_confidence_reasons=trust["reasons"],
                platform_fee_myr=round(resale_estimate * config.PLATFORM_FEE_PCT, 2),
                shipping_cost_myr=config.SHIPPING_COST_MYR,
                decision_factors=factors,
                collected_at=req.retained_source_times.get(listing.marketplace, collected_at) if listing.marketplace not in req.marketplaces else collected_at,
            )
        )
        if decision.is_profitable:
            notify.send_telegram_alert(listing, decision)

    decisions.sort(key=lambda item: (item.is_profitable, item.estimated_margin_pct), reverse=True)
    product_groups: list[ProductGroupOut] = []
    for group in groups:
        offers = [item for item in decisions if item.group_id == group.group_id]
        if not offers:
            continue
        band = group_bands[group.group_id]
        # The displayed offer range must describe the displayed budget-filtered
        # cards. Valuation still uses the full comparison pool above.
        prices = [item.price for item in offers]
        markets = sorted({item.marketplace for item in offers})
        product_groups.append(ProductGroupOut(
            group_id=group.group_id,
            name=group.name,
            variant_label=group.profile.label,
            variant_kind=group.profile.kind,
            variant_warning=group.profile.warning,
            offer_ids=[item.offer_id for item in offers],
            offer_count=len(offers),
            marketplace_count=len(markets),
            marketplaces=markets,
            lowest_price_myr=round(min(prices), 2),
            median_price_myr=band["estimate"],
            highest_price_myr=round(max(prices), 2),
            confidence=band["confidence"],
        ))
    product_groups.sort(
        key=lambda item: (
            any(decision.is_profitable for decision in decisions if decision.group_id == item.group_id),
            item.marketplace_count,
            item.offer_count,
        ),
        reverse=True,
    )
    return SearchResponse(
        query=req.query,
        source_mode=req.source_mode,
        provider=provider,
        pricing_mode=req.pricing_mode,
        match_mode=req.match_mode,
        collected_at=collected_at,
        marketplaces=searched_marketplaces,
        source_counts=source_counts,
        source_errors=source_errors,
        ai_mode="gemini" if config.GEMINI_API_KEY else "deterministic",
        total_scraped=len(listings),
        kept_after_filter=len(kept),
        discarded=discarded,
        decisions=decisions,
        product_groups=product_groups,
        market_listings=market_pool,
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
