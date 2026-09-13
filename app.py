import streamlit as st
from filters import load_listings, hard_filter
from orchestrator import run_swarm

st.set_page_config(page_title="Arbitrage Swarm", layout="wide")
st.title("🧠 E-Commerce Arbitrage Swarm")
st.caption("Carousell Malaysia · Hard-filter → 3-agent swarm → negotiation output")

# NOTE: resale_estimate is hardcoded per-search for the hackathon demo.
# Full version should pull a real market-average price (e.g. average of top N sold listings).
resale_estimate = st.number_input("Estimated resale price (RM)", value=90.0, step=5.0)

if st.button("🐝 Start Swarm"):
    listings = load_listings()
    kept, discarded = hard_filter(listings)

    st.subheader(f"Phase 1: Hard-Filter — kept {len(kept)}/{len(listings)}")
    if discarded:
        with st.expander("Discarded listings"):
            st.json(discarded)

    st.subheader("Phase 2 & 3: Swarm decisions")
    for listing in kept:
        with st.status(f"Processing {listing.title}...", expanded=True) as status:
            st.write("🔎 Agent 1 (Context Analyst) reading description...")
            st.write("👁️ Agent 2 (Vision Authenticator) checking photos...")
            st.write("🧭 Agent 3 (Lead Strategist) deciding...")
            decision = run_swarm(listing, resale_estimate)
            status.update(label=f"{listing.title} — done", state="complete")

        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("Margin", f"{decision.estimated_margin_pct}%")
            st.write("✅ Profitable" if decision.is_profitable else "❌ Pass")
        with col2:
            st.write("**Reasoning:**", decision.reasoning)
            if decision.negotiation_message:
                st.text_area("Negotiation message", decision.negotiation_message, key=listing.id)
        st.divider()
