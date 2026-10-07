"""Runtime configuration. Secrets must come from environment variables."""
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load project-local secrets automatically. Existing shell variables win, so
# deployment environments can override .env without editing any files.
load_dotenv(BASE_DIR / ".env", override=False)

# Optional AI enhancement. The deterministic pipeline still works without it.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
CHEAP_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-3.8-flash")

# Optional reliable Carousell data provider. If unset, the app attempts a direct
# browser scrape and reports anti-bot blocks honestly instead of returning fake data.
REEF_API_KEY = os.environ.get("REEF_API_KEY", "").strip()
REEF_API_BASE = os.environ.get("REEF_API_BASE", "https://api.reefapi.com").rstrip("/")

# Optional Shopee keyword-search provider. Shopee gates keyword results for
# automated clients, so this is preferred over the honest best-effort browser.
NEXSCOPE_API_KEY = os.environ.get("NEXSCOPE_API_KEY", "").strip()
NEXSCOPE_SHOPEE_URL = os.environ.get(
    "NEXSCOPE_SHOPEE_URL",
    "https://api.nexscope.ai/api/skill-api/v1/skills/shopee-product-search/run",
).strip()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Deterministic filters and business assumptions.
MAX_PRICE_MYR = float(os.environ.get("MAX_PRICE_MYR", "2500"))
MIN_SELLER_RATING = float(os.environ.get("MIN_SELLER_RATING", "4.0"))
PLATFORM_FEE_PCT = float(os.environ.get("PLATFORM_FEE_PCT", "0.05"))
SHIPPING_COST_MYR = float(os.environ.get("SHIPPING_COST_MYR", "8"))
MIN_MARGIN_PCT_TO_ALERT = float(os.environ.get("MIN_MARGIN_PCT_TO_ALERT", "20"))

MAX_SEARCH_RESULTS = int(os.environ.get("MAX_SEARCH_RESULTS", "12"))
CACHE_PATH = BASE_DIR / "cache" / "listings_raw.json"
