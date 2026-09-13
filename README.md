# E-Commerce Arbitrage Swarm — Hackathon Version

## File map
- `config.py` — thresholds, model name, cache toggle
- `schemas.py` — Pydantic models (Listing + 3 agent output schemas)
- `filters.py` — Phase 1 hard-filter (0 tokens)
- `cache/listings_raw.json` — mock Carousell data so the demo never depends on live scraping
- `agents/_llm.py` — shared "call Claude, force JSON" helper
- `agents/context_analyst.py` — Agent 1
- `agents/vision_authenticator.py` — Agent 2 (scoped to photo/text consistency, not fraud detection)
- `agents/lead_strategist.py` — Agent 3 + margin math
- `orchestrator.py` — LangGraph wiring, includes the one loop-back edge
- `app.py` — Streamlit demo dashboard
- `requirements.txt`

## Not included yet (add for the assignment version)
- Real Playwright scraper (`scraper.py`) — currently reads from cache only
- Telegram/Discord webhook push
- Website frontend (planned to replace Streamlit for the assignment)

## Run
```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
streamlit run app.py
```
