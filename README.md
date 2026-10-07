# ArbiSwarm

ArbiSwarm is an evidence-first multi-market arbitrage analyzer for Carousell, Lazada, Mudah, and Shopee Malaysia. Deterministic code owns ingestion, URL validation, relevance filtering, and margin math; three agents inspect context, photos, and risk before a deal reaches the dashboard.

## What changed from the prototype

- One search now fans out to Carousell, Lazada, Mudah, and Shopee and normalizes their different records into one contract.
- Live search uses real marketplace product URLs and never invents ratings, descriptions, or images.
- A Cloudflare/anti-bot challenge produces an honest `503 MARKETPLACE_BLOCKED` response. It does **not** silently return demo listings.
- Demo records are clearly labeled, query-filtered, and point to real product-page URLs.
- Gemini is optional. Without a key, deterministic agent fallbacks keep the pipeline usable.
- Profit is calculated from purchase price + shipping + the fee on the expected resale transaction.
- Equivalent offers are clustered across marketplaces while full sets, single characters, blind boxes, and accessories stay separated.
- Auto pricing derives a median resale estimate, confidence range, and sample size from comparable live listings; manual pricing remains available.
- Each offer includes seller confidence, collection freshness, transparent fee/shipping math, and the evidence behind the recommendation.
- Browser-local history and watchlists preserve complete results. A watchlist scan raises an in-app alert for a lower best price or new buy signal.
- One marketplace can be refreshed without re-requesting every source. Its records are combined with retained evidence and run through the same backend matching and valuation pipeline; individual collection timestamps are preserved. Older snapshots need a full search before per-source refresh is available.
- Comparison headers show only visible asking prices within the purchase ceiling. Resale estimates can still use above-budget comparable asks; these are not completed-sale prices or authentication evidence.
- Ask Arbi receives the active search, budget, selected offer, displayed calculations, and recent conversation. Its dark-glass window is draggable by the header (or arrow keys on the sparkle button; Home resets position) and supports fullscreen. Hover the context card to unfold actions; click Quick actions on touch devices. Shortcuts fill the composer without sending, and each sent request has its own visible user/assistant turns. Evidence stays collapsed until requested.
- Direct search requests such as `help me search Liverpool jersey 26/27 size M under RM300` fill the search form and run analysis when you press Send. Product/size/season words are passed to marketplace search; unspecified budgets and marketplaces are inherited and shown in the reply. New products use automatic resale pricing. Direct commands work without an AI service; other Gemini-generated changes still require an action-button confirmation. Earlier-board controls and stale shortcut drafts cannot overwrite a newer search. It never buys, sends seller messages, or starts background monitoring. Authentic-only filtering is not implemented.
- The API returns source, risk, agent evidence, total cost, expected profit, margin, product groups, valuation bands, and seller trust signals.
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
                  product matching + valuation + trust
                                      │
                                      ▼
                          FastAPI + web dashboard
```

The LangGraph flow still includes one bounded re-analysis handoff when the context agent says the listing text is too vague.

## Arbi workspace

### Product identity and saved-result filters

Search defaults to **Exact product & variant**. For a LEGO set-number search,
the title must establish that number and the main building set, not a
minifigure, small model, lighting kit, display case or incomplete set. Requested
jersey seasons, home/away styles and explicit sizes are checked too. Unconfirmed
matches appear in **View reasons**. **Include related variants** relaxes these
checks; different set numbers, product types, seasons and audiences still cannot
share resale medians. These are conservative title checks, not authentication.

The glass **Refine your board** bar filters saved offers by marketplace (multiple
chips can be selected), product type and asking-price ceiling. Reset restores
the full saved board without a crawl. Counts, groups and visible price ranges
follow the view; resale estimates retain the original evidence pool. This view
ceiling is separate from the search's max buy price. Old history is preserved
but labeled as needing a rerun for current matching rules.

Ask Arbi receives recent chat turns, the full saved evidence and active filters.
Follow-ups such as `got any just for 250?`, `compare only Shopee` and `show
everything again` update those same board filters without starting a search.
General language interpretation uses Gemini when reachable; local commands are
an explicitly labeled fallback, not an LLM. Quota/rate-limit (429), access and
timeout failures are shown without exposing credentials. A configured key is
not a verified connection. For 429 responses check your Gemini project's quota
and billing; adding a marketplace data key does not enable conversational AI.

Low-confidence automatic estimates and extreme below-median asks cannot create
buy recommendations. Profit figures in such cases are hypothetical pending
identity/inclusion verification. Low prices are not proof of counterfeits.

Selecting “Ask about this” first opens an identity preview (photo if available, full title, source, price, decision). Cancel sends nothing. Confirming selects and highlights that exact board card, then renders an instant evidence review without an AI request. The pinned identity can be reopened at any time.

Workspace controls compare the selected group, locate the original card, draft seller questions, apply a new purchase ceiling, save a live watchlist, or refresh a live source. They use the same search state and backend operations as the main page. Calculations use compact cards with expandable fees. Older board replies become explicitly read-only when the search changes. Free-text conversation remains available; no authenticity rules were changed.

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
- `GEMINI_MODEL`: defaults to `gemini-3.8-flash`. A retired model returning 404/410 is retried once with `GEMINI_FALLBACK_MODEL` (same default), without changing your `.env`. Requests have a 20-second timeout and no automatic SDK retries; local fallbacks remain available.
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
    "pricing_mode": "auto",
    "max_purchase_price": 60,
    "source_mode": "live",
    "marketplaces": ["carousell", "lazada", "mudah", "shopee"]
  }'
```

Health/config mode is available at `GET /api/health`.

## Tests

```bash
python -m unittest discover -s tests -v
node --test tests/chat-state.test.cjs
```

The tests cover marketplace-specific URL validation, query relevance, economics, variant classification, cross-market grouping, valuation confidence, seller trust, low-evidence retail risk gates, provider mapping, partial-source failures, and API behavior.
