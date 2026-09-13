import os

# --- API ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CHEAP_MODEL = "claude-haiku-4-5-20251001"  # fast + cheap for the swarm agents

# --- Hard-filter thresholds (Phase 1, 0 tokens) ---
MAX_PRICE_MYR = 60
MIN_SELLER_RATING = 4.0

# --- Business logic ---
PLATFORM_FEE_PCT = 0.05
SHIPPING_COST_MYR = 8
MIN_MARGIN_PCT_TO_ALERT = 20

# --- Demo reliability ---
USE_CACHED_LISTINGS = True  # True = read cache/listings_raw.json instead of live scraping
CACHE_PATH = "cache/listings_raw.json"
