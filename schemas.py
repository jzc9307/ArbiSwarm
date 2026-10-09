"""Typed contracts shared by ingestion, agents, API, and frontends."""
from datetime import datetime
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator

Marketplace = Literal['carousell', 'lazada', 'mudah', 'shopee', 'ebay', 'etsy']


class Listing(BaseModel):
    id: str
    title: str = Field(min_length=1, max_length=300)
    price: float = Field(gt=0)
    description: str = ""
    image_urls: list[str] = Field(default_factory=list)
    seller_rating: Optional[float] = Field(default=None, ge=0, le=5)
    seller_name: Optional[str] = None
    listing_rating: Optional[float] = Field(default=None, ge=0, le=5)
    review_count: Optional[int] = Field(default=None, ge=0)
    sold_count: Optional[int] = Field(default=None, ge=0)
    url: str
    condition: Optional[str] = None
    posted_at: Optional[datetime] = None
    marketplace: Marketplace = "carousell"
    source: Literal["carousell_live", "reef_api", "lazada_live", "mudah_reef", "shopee_browser", "shopee_nexscope", "ebay_api", "etsy_api", "demo_cache"] = "carousell_live"
    source_verified: bool = False
    original_price: Optional[float] = Field(default=None, gt=0)
    original_currency: Optional[str] = Field(default=None, pattern=r'^[A-Z]{3}$')
    fx_rate_to_myr: Optional[float] = Field(default=None, gt=0)
    fx_rate_date: Optional[str] = None
    shipping_cost_myr: Optional[float] = Field(default=None, ge=0)
    landed_cost_verified: bool = True
    cost_warning: Optional[str] = None

    @model_validator(mode="after")
    def require_supported_marketplace_url(self):
        parsed = HttpUrl(self.url)
        host = (parsed.host or "").lower()
        rules = {
            'ebay': (
                {'ebay.com', 'www.ebay.com', 'ebay.co.uk', 'www.ebay.co.uk', 'ebay.com.au', 'www.ebay.com.au', 'ebay.com.sg', 'www.ebay.com.sg'},
                lambda path: bool(re.fullmatch(r'/itm/(?:[^/]+/)?\d+/?', path)),
                'an eBay item page',
            ),
            'etsy': (
                {'etsy.com', 'www.etsy.com'},
                lambda path: bool(re.fullmatch(r'/listing/\d+(?:/[^/]*)?/?', path)),
                'an Etsy listing page',
            ),
            "carousell": (
                {"carousell.com.my", "www.carousell.com.my"},
                lambda path: "/p/" in path,
                "a Carousell product page",
            ),
            "lazada": (
                {"lazada.com.my", "www.lazada.com.my"},
                lambda path: "/products/" in path,
                "a Lazada product page",
            ),
            "mudah": (
                {"mudah.my", "www.mudah.my"},
                lambda path: path.endswith(".htm"),
                "a Mudah listing page",
            ),
            "shopee": (
                {"shopee.com.my", "www.shopee.com.my"},
                lambda path: bool(
                    re.search(r"-i\.\d+\.\d+/?$", path)
                    or re.search(r"/product/\d+/\d+/?$", path)
                ),
                "a Shopee product page",
            ),
        }
        hosts, path_check, label = rules[self.marketplace]
        if host not in hosts or not path_check(parsed.path):
            raise ValueError(f"listing URL must point to {label}")
        if self.marketplace in {'ebay', 'etsy'}:
            if parsed.scheme != 'https':
                raise ValueError('international listing URL must use HTTPS')
            # A retained client record must not turn a search ask into a landed-
            # cost recommendation merely by claiming the unknown costs verified.
            self.landed_cost_verified = False
            self.cost_warning = 'International asking price: shipping, import taxes and payment FX charges require checkout verification.'
        return self


class ContextAnalysis(BaseModel):
    true_condition: str
    flaws_found: list[str] = Field(default_factory=list)
    missing_parts: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    needs_clarification: bool = False


class VisionCheck(BaseModel):
    consistency_score: Optional[int] = Field(default=None, ge=0, le=100)
    mismatches: list[str] = Field(default_factory=list)
    images_checked: int = Field(default=0, ge=0)


class StrategistDecision(BaseModel):
    listing_id: str
    is_profitable: bool = False
    estimated_margin_pct: float = 0.0
    estimated_profit_myr: float = 0.0
    total_cost_myr: float = 0.0
    negotiation_message: Optional[str] = None
    reasoning: str = "Insufficient evidence to recommend this listing."
    risk_level: Literal["low", "medium", "high"] = "medium"
