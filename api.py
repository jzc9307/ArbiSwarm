"""FastAPI boundary for the ingestion, validation, and multi-agent pipeline."""
from pathlib import Path
from typing import Literal, Optional
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import config
from filters import hard_filter, load_listings
import marketplaces as marketplace_service
import notify
from orchestrator import run_swarm
from schemas import Listing

logger = logging.getLogger("arbiswarm")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app = FastAPI(title="ArbiSwarm API", version="1.0.0")


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    resale_estimate: float = Field(gt=0, le=1_000_000)
    max_purchase_price: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    source_mode: Literal["live", "demo"] = "live"
    marketplaces: list[Literal["carousell", "lazada", "mudah", "shopee"]] = Field(
        default_factory=lambda: ["carousell", "lazada", "mudah", "shopee"],
        min_length=1,
        max_length=4,
    )

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


class DecisionOut(BaseModel):
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


class SearchResponse(BaseModel):
    query: str
    source_mode: str
    provider: str
    marketplaces: list[str]
    source_counts: dict[str, int]
    source_errors: list[dict]
    ai_mode: Literal["gemini", "deterministic"]
    total_scraped: int
    kept_after_filter: int
    discarded: list[dict]
    decisions: list[DecisionOut]


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "ai_mode": "gemini" if config.GEMINI_API_KEY else "deterministic",
        "marketplaces": {
            "carousell": "reef_api" if config.REEF_API_KEY else "direct_browser",
            "lazada": "public_json",
            "mudah": "reef_api" if config.REEF_API_KEY else "not_configured",
            "shopee": "nexscope_api" if config.NEXSCOPE_API_KEY else "public_browser_best_effort",
        },
    }


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

    kept, discarded = hard_filter(
        listings,
        query=req.query,
        max_price=req.max_purchase_price,
    )
    discarded = ingest_discarded + discarded

    decisions: list[DecisionOut] = []
    for listing in kept:
        try:
            decision, analysis, vision = run_swarm(listing, req.resale_estimate, include_evidence=True)
        except Exception as exc:
            logger.exception("Pipeline failed for listing %s", listing.id)
            discarded.append({"id": listing.id, "title": listing.title, "reason": f"analysis failed: {exc}"})
            continue

        decisions.append(
            DecisionOut(
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
            )
        )
        if decision.is_profitable:
            notify.send_telegram_alert(listing, decision)

    decisions.sort(key=lambda item: (item.is_profitable, item.estimated_margin_pct), reverse=True)
    return SearchResponse(
        query=req.query,
        source_mode=req.source_mode,
        provider=provider,
        marketplaces=searched_marketplaces,
        source_counts=source_counts,
        source_errors=source_errors,
        ai_mode="gemini" if config.GEMINI_API_KEY else "deterministic",
        total_scraped=len(listings),
        kept_after_filter=len(kept),
        discarded=discarded,
        decisions=decisions,
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
