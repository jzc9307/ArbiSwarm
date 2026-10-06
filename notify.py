"""Phase 4: push profitable deals to Telegram.
If TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID aren't set, this silently no-ops
so the app still runs fine without a Telegram bot configured (e.g. for demos)."""
import httpx
import logging
from schemas import Listing, StrategistDecision
import config

logger = logging.getLogger("arbitrage_swarm.notify")


def send_telegram_alert(listing: Listing, decision: StrategistDecision) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False  # not configured - not an error, just a no-op

    text = (
        f"🐝 *Profitable deal found*\n\n"
        f"*{listing.title}*\n"
        f"Price: RM{listing.price} · Margin: {decision.estimated_margin_pct}%\n\n"
        f"{decision.reasoning}\n\n"
    )
    if decision.negotiation_message:
        text += f"💬 Suggested message:\n{decision.negotiation_message}\n\n"
    text += listing.url

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
        resp.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send Telegram alert")
        return False  # never let a notification failure break the main pipeline