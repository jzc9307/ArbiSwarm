"""Pydantic models — force every agent to output strict, parseable JSON."""
from pydantic import BaseModel, Field
from typing import Optional


class Listing(BaseModel):
    """A single cached/scraped Carousell listing (post hard-filter)."""
    id: str
    title: str
    price: float
    description: str
    image_urls: list[str]
    seller_rating: float
    url: str


class ContextAnalysis(BaseModel):
    """Agent 1: Context Analyst output."""
    true_condition: str = Field(description="e.g. 'Used - Good', 'Mint', 'Damaged'")
    flaws_found: list[str] = Field(default_factory=list)
    missing_parts: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    needs_clarification: bool = Field(
        default=False,
        description="True if description is too vague to score confidently — triggers loop-back",
    )


class VisionCheck(BaseModel):
    """Agent 2: Vision Authenticator output.
    Scoped to photo-vs-description consistency, NOT counterfeit detection."""
    consistency_score: int = Field(ge=0, le=100, description="Does photo match description/title?")
    mismatches: list[str] = Field(default_factory=list, description="e.g. 'wrong color', 'stock photo used'")


class StrategistDecision(BaseModel):
    """Agent 3: Lead Strategist output."""
    listing_id: str
    is_profitable: bool
    estimated_margin_pct: float
    negotiation_message: Optional[str] = None
    reasoning: str
