# ArbiSwarm

ArbiSwarm is an evidence-first multi-market arbitrage analyzer for Carousell, Lazada, Mudah, and Shopee Malaysia. Deterministic code owns ingestion, URL validation, relevance filtering, and margin math; three agents inspect context, photos, and risk before a deal reaches the dashboard.

## What changed from the prototype

- One search now fans out to Carousell, Lazada, Mudah, and Shopee and normalizes their different records into one contract.
- Live search uses real marketplace product URLs and never invents ratings, descriptions, or images.
- A Cloudflare/anti-bot challenge produces an honest `503 MARKETPLACE_BLOCKED` response. It does **not** silently return demo listings.
- Demo records are clearly labeled, query-filtered, and point to real product-page URLs.
- Gemini is optional. Without a key, deterministic agent fallbacks keep the pipeline usable.
- Profit is calculated from purchase price + shipping + the fee on the expected resale transaction.
- The API returns source, risk, agent evidence, total cost, expected profit, and margin.
- Secrets are environment-only; there are no API keys in source control.

## Architecture

```text
Carousell ─┐
Lazada ────┤
Mudah ─────┼─► marketplace adapters
Shopee ────┘
                  │
                  ▼
URL + provenance validation ──► relevance / price filters
                                      │
                                      ▼
Context agent ──► Vision agent ──► Strategy agent
                                      │
                                      ▼
                          FastAPI + web dashboard
```

The LangGraph flow still includes one bounded re-analysis handoff when the context agent says the listing text is too vague.

## Run the web app

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
uvicorn api:app --reload
```

The application automatically loads the project-root `.env` file on startup. Variables already exported in the shell take precedence.

Open <http://127.0.0.1:8000>.

## Data modes

### Live market

With `REEF_API_KEY`, the backend uses ReefAPI for Carousell and Mudah. ReefAPI is a third-party provider, not an official marketplace API. Lazada uses its public Malaysian search JSON directly. Shopee uses Nexscope when `NEXSCOPE_API_KEY` is configured; otherwise it makes a best-effort request through a normal browser without stealth or verification bypasses.

Without it, Playwright attempts the public Carousell page. Carousell currently uses anti-bot verification and may block headless browsers. This is treated as a data-source failure, not as permission to fabricate results.

Each source fails independently: if one marketplace is unavailable, results from healthy sources still render with a visible warning. If Shopee requests human verification or stops exposing readable public product cards, ArbiSwarm reports the source failure and continues with the other selected marketplaces.

### Demo snapshot

The bundled snapshot is only for the `Labubu Macaron` demo. A different query returns zero records rather than unrelated Labubu data.

## Optional services

- `GEMINI_API_KEY`: enables LLM context and photo analysis. Without it, rules-based fallbacks run and the UI says `Deterministic mode`.
- `REEF_API_KEY`: provides reliable live Carousell and Mudah search data.
- `NEXSCOPE_API_KEY`: provides reliable Shopee Malaysia keyword-search data. Without it, the public-browser attempt may be rejected by Shopee.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: send alerts for candidates that pass deterministic rules.

See [.env.example](.env.example) for all tunable thresholds.

## API

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'content-type: application/json' \
  -d '{
    "query": "Labubu Macaron",
    "resale_estimate": 90,
    "max_purchase_price": 60,
    "source_mode": "live",
    "marketplaces": ["carousell", "lazada", "mudah", "shopee"]
  }'
```

Health/config mode is available at `GET /api/health`.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover marketplace-specific URL validation, query relevance, economics, low-evidence retail risk gates, provider mapping, partial-source failures, and API behavior.
