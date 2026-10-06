"""Small Streamlit client kept for lecturers who prefer the original demo format."""
import streamlit as st

from filters import hard_filter, load_listings
import marketplaces as marketplace_service
import notify
from orchestrator import run_swarm
from schemas import Listing

st.set_page_config(page_title="ArbiSwarm", layout="wide")
st.title("ArbiSwarm")
st.caption("Verified source → deterministic filter → three-agent decision")

query = st.text_input("Item", value="Labubu Macaron")
resale_estimate = st.number_input("Expected resale price (RM)", min_value=1.0, value=90.0)
max_price = st.number_input("Maximum purchase price (RM)", min_value=1.0, value=60.0)
source_mode = st.radio("Data source", ["Live market", "Demo snapshot"], horizontal=True)
selected_marketplaces = st.multiselect(
    "Marketplaces",
    ["carousell", "lazada", "mudah", "shopee"],
    default=["carousell", "lazada", "mudah", "shopee"],
    disabled=source_mode != "Live market",
)

if st.button("Run analysis", type="primary"):
    try:
        if source_mode == "Live market":
            raw, counts, errors = marketplace_service.search_many(query, selected_marketplaces, 12)
            listings = [Listing(**item) for item in raw]
            for error in errors:
                st.warning(f"{error['marketplace']}: {error['message']}")
        else:
            listings = load_listings(query=query)
    except (marketplace_service.MarketplaceSearchError, ValueError) as exc:
        st.error(str(exc))
        st.stop()

    kept, discarded = hard_filter(listings, query=query, max_price=max_price)
    st.info(f"Analyzing {len(kept)} of {len(listings)} source records")
    if discarded:
        with st.expander(f"{len(discarded)} filtered out"):
            st.json(discarded)

    for listing in kept:
        decision, analysis, vision = run_swarm(listing, resale_estimate, include_evidence=True)
        with st.container(border=True):
            st.subheader(listing.title)
            a, b, c = st.columns(3)
            a.metric("Ask", f"RM{listing.price:.2f}")
            b.metric("Expected profit", f"RM{decision.estimated_profit_myr:.2f}")
            c.metric("Margin", f"{decision.estimated_margin_pct:.1f}%")
            st.write("**BUY SIGNAL**" if decision.is_profitable else "**PASS**")
            st.write(decision.reasoning)
            st.caption(
                f"Context: {analysis.true_condition} · Vision: "
                f"{vision.consistency_score if vision.consistency_score is not None else 'not scored'} · "
                f"Risk: {decision.risk_level}"
            )
            if decision.negotiation_message:
                st.code(decision.negotiation_message, language=None)
            st.link_button("Open real listing", listing.url)
            if decision.is_profitable and notify.send_telegram_alert(listing, decision):
                st.caption("Alert sent to Telegram")
