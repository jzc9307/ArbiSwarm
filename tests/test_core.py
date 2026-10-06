import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

import api
import config
import marketplaces
from agents.lead_strategist import calc_economics, decide
from filters import hard_filter, load_listings
from schemas import ContextAnalysis, Listing, VisionCheck
import scraper


def listing(**updates) -> Listing:
    payload = {
        "id": "1234567890",
        "title": "Labubu Macaron test listing",
        "price": 40,
        "description": "Brand new sealed item with receipt.",
        "image_urls": [],
        "seller_rating": None,
        "url": "https://www.carousell.com.my/p/labubu-macaron-test-1234567890/",
        "source": "carousell_live",
        "source_verified": True,
    }
    payload.update(updates)
    return Listing(**payload)


class ListingValidationTests(unittest.TestCase):
    def test_rejects_non_carousell_url(self):
        with self.assertRaises(ValidationError):
            listing(url="https://example.com/p/1234567890/")

    def test_rejects_search_page_as_listing(self):
        with self.assertRaises(ValidationError):
            listing(url="https://www.carousell.com.my/labubu-macaron/q/")

    def test_accepts_supported_marketplace_product_urls(self):
        lazada = listing(
            marketplace="lazada",
            source="lazada_live",
            url="https://www.lazada.com.my/products/labubu-i123456.html",
        )
        mudah = listing(
            marketplace="mudah",
            source="mudah_reef",
            url="https://www.mudah.my/labubu-123456.htm",
        )
        shopee = listing(
            marketplace="shopee",
            source="shopee_browser",
            url="https://shopee.com.my/Pop-Mart-Labubu-i.123456.987654321",
        )
        self.assertEqual(lazada.marketplace, "lazada")
        self.assertEqual(mudah.marketplace, "mudah")
        self.assertEqual(shopee.marketplace, "shopee")


class FilterTests(unittest.TestCase):
    def test_demo_cache_is_query_aware(self):
        self.assertEqual(load_listings(query="Sony headphones"), [])
        self.assertGreater(len(load_listings(query="Labubu Macaron")), 0)

    def test_unknown_rating_is_not_fabricated_or_rejected(self):
        kept, discarded = hard_filter([listing()], query="Labubu Macaron", max_price=60)
        self.assertEqual(len(kept), 1)
        self.assertEqual(discarded, [])

    def test_price_filter_reports_reason(self):
        kept, discarded = hard_filter([listing(price=75)], query="Labubu Macaron", max_price=60)
        self.assertEqual(kept, [])
        self.assertIn("exceeds", discarded[0]["reason"])


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.old_key = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = ""

    def tearDown(self):
        config.GEMINI_API_KEY = self.old_key

    def test_economics_charges_fee_on_resale(self):
        self.assertEqual(calc_economics(40, 90), (52.5, 37.5, 71.4))

    def test_missing_parts_blocks_high_margin_buy(self):
        decision = decide(
            listing(),
            ContextAnalysis(true_condition="Used", missing_parts=["charger"]),
            VisionCheck(consistency_score=90, images_checked=1),
            100,
        )
        self.assertFalse(decision.is_profitable)
        self.assertEqual(decision.risk_level, "high")

    def test_low_evidence_retail_bargain_is_not_a_buy_signal(self):
        retail_listing = listing(
            marketplace="lazada",
            source="lazada_live",
            url="https://www.lazada.com.my/products/labubu-i123456.html",
            price=15,
            listing_rating=5,
            review_count=2,
        )
        decision = decide(
            retail_listing,
            ContextAnalysis(true_condition="New retail listing"),
            VisionCheck(consistency_score=None, images_checked=0),
            90,
        )
        self.assertFalse(decision.is_profitable)
        self.assertEqual(decision.risk_level, "high")

    def test_retail_buy_signal_does_not_offer_negotiation(self):
        retail_listing = listing(
            marketplace="lazada",
            source="lazada_live",
            url="https://www.lazada.com.my/products/labubu-i123456.html",
            price=40,
            listing_rating=4.9,
            review_count=50,
        )
        decision = decide(
            retail_listing,
            ContextAnalysis(true_condition="New retail listing"),
            VisionCheck(consistency_score=None, images_checked=0),
            90,
        )
        self.assertTrue(decision.is_profitable)
        self.assertIsNone(decision.negotiation_message)


class ScraperTests(unittest.TestCase):
    def test_current_carousell_search_url(self):
        self.assertEqual(
            scraper.build_search_url("Labubu Macaron"),
            "https://www.carousell.com.my/labubu-macaron/q/",
        )

    def test_provider_record_maps_without_fake_rating(self):
        record = scraper._from_reef_record({
            "listing_id": "1452171911",
            "title": "Labubu Macaron",
            "price": 40,
            "url": "https://www.carousell.com.my/p/1452171911/",
            "card_lines": ["Opened box to check card"],
        })
        self.assertEqual(record["seller_rating"], None)
        self.assertEqual(record["source"], "reef_api")

    def test_dom_card_uses_locator_api(self):
        class FakeImageLocator:
            first = None

            def __init__(self):
                self.first = self

            def count(self):
                return 1

            def get_attribute(self, name):
                return {
                    "src": "https://media.karousell.com/photo.jpg",
                    "alt": "Labubu Macaron",
                }.get(name)

        class FakeAnchorLocator:
            def get_attribute(self, name):
                return "/p/labubu-macaron-1452171911/" if name == "href" else None

            def inner_text(self):
                return "Labubu Macaron\nRM40\nBrand new"

            def locator(self, selector):
                self.test_case.assertEqual(selector, "img")
                return FakeImageLocator()

        anchor = FakeAnchorLocator()
        anchor.test_case = self
        record = scraper._card_to_listing(anchor)
        self.assertEqual(record["id"], "1452171911")
        self.assertEqual(record["price"], 40)
        self.assertEqual(record["title"], "Labubu Macaron")


class MarketplaceAdapterTests(unittest.TestCase):
    def test_shopee_card_maps_to_normalized_listing(self):
        class FakeImage:
            @property
            def first(self):
                return self

            def count(self):
                return 1

            def get_attribute(self, name):
                return {
                    "alt": "POP MART Labubu Macaron blind box",
                    "src": "https://down-my.img.susercontent.com/file/example",
                }.get(name)

        class FakeAnchor:
            def get_attribute(self, name):
                return "/POP-MART-Labubu-i.123456.987654321" if name == "href" else None

            def inner_text(self):
                return "POP MART Labubu Macaron blind box · RM29.90 · 2.3k sold"

            def locator(self, _selector):
                return FakeImage()

        row = marketplaces._shopee_card_to_listing(FakeAnchor())
        self.assertIsNotNone(row)
        self.assertEqual(row["marketplace"], "shopee")
        self.assertEqual(row["source"], "shopee_browser")
        self.assertEqual(row["price"], 29.9)
        self.assertEqual(row["sold_count"], 2300)

    def test_shopee_rejects_search_url_as_listing(self):
        self.assertIsNone(marketplaces._shopee_listing_url("https://shopee.com.my/search?keyword=labubu"))

    def test_shopee_provider_maps_real_product_record(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"products": [{
                    "pid": "987654321",
                    "productName": "POP MART Labubu Macaron blind box",
                    "productUrl": "https://shopee.com.my/POP-MART-Labubu-i.123456.987654321",
                    "price": 29.9,
                    "imageUrl": "https://down-my.img.susercontent.com/file/example",
                    "rating": 4.8,
                    "ratings": 52,
                    "historicalSold": 430,
                    "merchant": "popmart.os",
                }]}

        with patch.object(marketplaces.httpx, "post", return_value=FakeResponse()):
            rows = marketplaces._search_shopee_provider("Labubu Macaron", 4)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "shopee_nexscope")
        self.assertEqual(rows[0]["listing_rating"], 4.8)
        self.assertEqual(rows[0]["sold_count"], 430)

    def test_lazada_json_maps_to_normalized_listing(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"mods": {"listItems": [{
                    "itemId": "4681669062",
                    "name": "Labubu Macaron",
                    "itemUrl": "//www.lazada.com.my/products/labubu-i4681669062.html",
                    "price": "15.99",
                    "ratingScore": "4.9",
                    "location": "Selangor",
                    "image": "https://sg-test-11.slatic.net/photo.jpg",
                }]}}

        with patch.object(marketplaces.httpx, "get", return_value=FakeResponse()):
            rows = marketplaces.search_lazada("Labubu Macaron", 4)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["marketplace"], "lazada")
        self.assertEqual(rows[0]["price"], 15.99)
        self.assertEqual(rows[0]["listing_rating"], 4.9)

    def test_mudah_provider_maps_to_normalized_listing(self):
        data = {"results": [{
            "listing_id": "115976451",
            "title": "Labubu Macaron",
            "url": "https://www.mudah.my/labubu-macaron-115976451.htm",
            "price": 50,
            "condition": "Second-hand (Used)",
            "description": "Complete box and card",
            "images": ["https://img.rnudah.com/photo.jpg"],
            "seller": {"name": "Seller"},
        }]}
        with patch.object(marketplaces, "_request_reef", return_value=data):
            rows = marketplaces.search_mudah("Labubu Macaron", 4)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["marketplace"], "mudah")
        self.assertEqual(rows[0]["seller_name"], "Seller")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.old_key = config.GEMINI_API_KEY
        config.GEMINI_API_KEY = ""

    def tearDown(self):
        config.GEMINI_API_KEY = self.old_key

    def test_demo_search_returns_provenance(self):
        response = api.search(api.SearchRequest(
            query="Labubu Macaron",
            resale_estimate=90,
            max_purchase_price=60,
            source_mode="demo",
        ))
        self.assertEqual(response.provider, "demo_cache")
        self.assertEqual(response.ai_mode, "deterministic")
        self.assertTrue(all(item.source == "demo_cache" for item in response.decisions))

    def test_live_block_does_not_fall_back_to_demo(self):
        failed = ([], {"carousell": 0}, [{"marketplace": "carousell", "message": "blocked"}])
        with patch.object(api.marketplace_service, "search_many", return_value=failed):
            with self.assertRaises(HTTPException) as raised:
                api.search(api.SearchRequest(
                    query="camera",
                    resale_estimate=100,
                    source_mode="live",
                    marketplaces=["carousell"],
                ))
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail["code"], "ALL_MARKETPLACES_FAILED")

    def test_partial_marketplace_failure_keeps_good_results(self):
        raw = [listing().model_dump(mode="json")]
        partial = (
            raw,
            {"carousell": 1, "lazada": 0},
            [{"marketplace": "lazada", "message": "temporarily unavailable"}],
        )
        with patch.object(api.marketplace_service, "search_many", return_value=partial):
            response = api.search(api.SearchRequest(
                query="Labubu Macaron",
                resale_estimate=90,
                source_mode="live",
                marketplaces=["carousell", "lazada"],
            ))
        self.assertEqual(len(response.decisions), 1)
        self.assertEqual(response.source_counts["carousell"], 1)
        self.assertEqual(response.source_errors[0]["marketplace"], "lazada")


if __name__ == "__main__":
    unittest.main()
