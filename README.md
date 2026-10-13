# ArbiSwarm

ArbiSwarm is an evidence-first multi-market arbitrage analyzer for Carousell, Lazada, Mudah, Shopee Malaysia, and optional official eBay/Etsy sources. An adaptive controller invokes specialized Gemini roles only when needed: intent planning, batched evidence analysis, photo comparison, explicit review and conversation. Deterministic code enforces identity checks, URL validation, safety gates and financial calculations. Marketplace retrieval tools are not themselves LLM agents.

## What changed from the prototype

- One search fans out to selected local markets and optional eBay/Etsy adapters, normalizing their records into one contract. International sources require their own approved developer credentials.
- Clear product queries use local identity parsing; conversational goals can invoke a cached Gemini planner for up to three equivalent queries and context-specific concept aliases. An explicit `planning_mode: "ai"` also requests planning. Critical unresolved identity can return a clarification question before retrieval. Numeric model IDs, brands, requested sizes and seasons cannot be silently broadened. This is provisional textual matching, not authentication.
- The purchase budget is optional and starts empty. Search first, then use saved-result filters to explore a price range.
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
Search / contextual chat / photo
              │
              ▼
Adaptive controller + request budget
  ├─ clear query: local parsing
  └─ ambiguous goal: cached manager/planner
              │
              ▼
Concurrent marketplace tools → URL / identity validation
              │
              ▼
Evidence cache → one bounded cross-market analyst batch
  └─ photo search: vision comparison instead of text batch
              │
              ▼
Comparable groups → resale bands → deterministic safety / fees
              │
              ▼
Existing FastAPI response + execution / token evidence

Saved-board commands: local, no Gemini request
Flexible conversation: chat role, bounded board context
Optional deeper review: explicit reviewer, no automatic extra loop
```

The default API no longer runs a context/vision/strategy LLM chain for every listing. The old LangGraph builder remains available for explicit experiments, but normal searches use the bounded batch controller.

### Free-tier call budget and evidence

- A fresh clear text search normally uses **one analyst call**, reviewing at most eight new/changed listings across sources. A conversational goal may add one manager call. Empty candidate pools need no analyst call. Retries count as additional wire attempts; the default search cap is three attempts total.
- Successful evidence is cached for one hour, keyed by the query, matching mode, model, role and listing contents. Changed price/description invalidates it. Repeated searches may review previously unreviewed candidates in another bounded batch; once all relevant evidence is cached, reuse needs no analyst call. Reopening browser history does not call the backend.
- Listings outside the batch remain visible, explicitly unreviewed and unable to create automatic buy recommendations. Invalid, unsupported or uncertain AI findings cannot silently become validated matches. Reviewed matches, uncertain matches and unreviewed offers use separate valuation pools. Source quotes are grounding checks, not proof that the model's interpretation or product authenticity is correct.
- Simple compare/filter/budget/explanation commands use saved-board data without Gemini. Flexible conversation uses the chat role with at most twelve offers and six recent turns; successful identical plans have a fifteen-minute in-memory cache. It is still a bounded assistant, not an unrestricted autonomous purchaser.
- `agent_run` reports actual attempted requests, provider responses, cache reuse and server execution events. Tokens are summed from provider metadata only; missing metadata remains unknown, not zero. Failed requests may consume provider quota even when no token metadata is returned.
- `GET /api/agents/runtime` exposes safe key-slot counts, local scheduler settings and recent runs; it never returns credentials. `POST /api/agents/review` accepts a query and up to three validated listings for an explicitly requested reviewer batch. This endpoint does not send alerts or change financial calculations.

The frontend and its existing response fields are unchanged by this backend refactor. Execution metadata is additive; the existing animated loading percentage is not a live measurement of these server events. The new reviewer endpoint has no new frontend control.

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

Ask Arbi validates commands against the full saved board and active filters; model prompts receive a bounded, selected-aware evidence subset and recent chat turns.
Follow-ups such as `got any just for 250?`, `compare only Shopee` and `show
everything again` update those same board filters without starting a search.
General language interpretation uses Gemini when reachable; recognized local commands deliberately skip the model and are explicitly labeled, not presented as LLM reasoning. Quota/rate-limit (429), access and
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

For five authorized Gemini keys, use the numbered slots in `.env.example`:

```dotenv
GEMINI_API_KEY=primary_key
GEMINI_API_KEY_2=analyst_key
GEMINI_API_KEY_3=vision_key
GEMINI_API_KEY_4=reviewer_key
GEMINI_API_KEY_5=chat_key
```

Slots prefer manager, analyst, vision, reviewer and chat respectively; these are routing preferences, not five mandatory calls per search. Fewer keys still work. `GEMINI_API_KEYS` optionally adds backups after numbered slots; duplicate/empty values are removed. Project labels correspond to the resulting non-empty, deduplicated key order.

Keys belonging to the same Google project share quota. Set `GEMINI_KEY_PROJECTS` to matching labels for shared projects, or different labels only for genuinely independent authorized projects. Unlabelled keys conservatively share one local budget. Labels coordinate local scheduling; they do not verify project ownership or increase Google quota. Defaults are five requests/minute and twenty/day per project/model; confirm your actual project's limits and adjust downward where necessary. Other applications' usage is not visible to these counters.

All Gemini roles share the scheduler. HTTP 429 applies cooldowns and can use another available project within the two-attempt call cap. Known shared-project keys are not cycled to escape that project's cooldown. A 503 gets at most one short same-key retry, unless the provider asks to wait; repeated overload cools the model. A 404/410 can use the configured fallback model and is remembered to avoid repeated bad-model probes. No unbounded retry or per-listing re-analysis loop remains. Errors become explicit local/evidence-hold results, not fake successful AI work.

Budgets, cooldowns, caches and execution history are process-local and reset on restart. They are guardrails, **not a live remaining-quota meter**. Use one backend worker for this local app; deployment requires durable/shared quota coordination. Restart after changing `.env`; the app never rewrites it or exposes keys to the browser. See [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).

Open <http://127.0.0.1:8000>.

## Data modes

### Live market

With `REEF_API_KEY`, the backend uses ReefAPI for Carousell and Mudah. ReefAPI is a third-party provider, not an official marketplace API. Lazada uses its public Malaysian search JSON directly. Shopee uses Nexscope when `NEXSCOPE_API_KEY` is configured; otherwise it makes a best-effort request through a normal browser without stealth or verification bypasses.

Without it, Playwright attempts the public Carousell page. Carousell currently uses anti-bot verification and may block headless browsers. This is treated as a data-source failure, not as permission to fabricate results.

Each source fails independently: if one marketplace is unavailable, results from healthy sources still render with a visible warning. If Shopee requests human verification or stops exposing readable public product cards, ArbiSwarm reports the source failure and continues with the other selected marketplaces.

### eBay and Etsy

The new search checkboxes are opt-in and show `API setup` until credentials are configured. API configuration is not proof of provider access. Both sources participate in grouped results, source refresh, saved-result filters, history, watchlist scans, and chat commands such as `find Liverpool shirt 97/98 on ebay and etsy`.

- eBay: configure `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` for a production application with Browse API access. The app caches an OAuth client-credentials token, searches fixed-price items, and requests delivery eligibility for Malaysia. `EBAY_MARKETPLACE_ID` defaults to `EBAY_US`.
- Etsy: configure `ETSY_API_KEY` (keystring) and `ETSY_SHARED_SECRET` with approved API access. Public active listings are searched with `buyer_country=MY`; a batch request enriches images. Digital downloads are excluded. No seller ratings are invented.
- Foreign currencies use cached [Frankfurter reference rates](https://frankfurter.dev/v1/), with original currency, price, rate and date preserved. Failed conversion is reported; currency values are never mistaken for MYR. Checkout/payment rates may differ.
- International items are comparison evidence only. Returned shipping quotes are included when available; unknown shipping is a flagged lower bound, not the domestic RM8 default. Import taxes and payment charges need checkout verification. International offers cannot emit buy alerts, even if a client claims landed costs were verified.

References: [eBay Browse API](https://www.developer.ebay.com/api-docs/buy/static/api-browse.html), [eBay OAuth](https://www.developer.ebay.com/develop/guides/sell/authorization), [Etsy requests](https://developer.etsy.com/documentation/essentials/requests/), [Etsy official OpenAPI specification](https://www.etsy.com/openapi/generated/oas/3.0.0.json).

### Facebook access research (not integrated)

A general-purpose public Marketplace search integration could not be verified in Meta's accessible developer documentation. Third-party services such as [Social Fetch](https://www.socialfetch.dev/platforms/facebook/marketplace-search) document API-key-based keyword/location search without the customer's Facebook login. That is a technically simpler path, not proof of Meta authorization, coverage or reliability. [Meta requires prior permission for automated collection](https://about.fb.com/news/2021/04/how-we-combat-scraping/); [Social Fetch's DPA](https://www.socialfetch.dev/dpa) assigns permissions/legal-basis responsibility to the customer. Do not supply session cookies, bypass verification, or assume buying an API key grants upstream permission. Confirm authorization and Malaysian coverage before connecting a provider. A manual Facebook search handoff with user-provided listing evidence remains an alternative.

### Demo snapshot

The bundled snapshot is only for the `Labubu Macaron` demo. A different query returns zero records rather than unrelated Labubu data.

## Arbi Lens — search with a photo

Open the camera beside the search field, or the attachment button in Ask Arbi. Choose a JPEG, PNG or WebP (up to 6 MB / 24 megapixels), optionally crop the product, then press **Identify**. Review the visible details, uncertainty and editable search name before confirming a product or similar-products search. Your existing marketplace selection and optional budget still apply.

Lens requires a configured Gemini key and live mode. It identifies a reference, retrieves keyword candidates through the existing marketplace adapters, then visually compares at most six available listing photos in one batch. This is not a marketplace-wide reverse-image index. Results are separated into likely matches, similar products, unverified results and different products; a resemblance is not proof of the exact model, completeness or authenticity. Lens results remain on evidence hold and do not send buy alerts.

Cost controls: images are resized to at most 1024 pixels on their longest edge, recognition and comparison results are cached, and Lens skips the text planner and analyst batch. A fresh scan normally uses one recognition call and one comparison batch, in separate identify/search operations. Follow-up chat receives the reference description and recorded comparison evidence, not the photo again. Provider-reported recognition/comparison token usage is shown when available; later chat usage is separate. Repeated scans, failures or key/model failover can add attempts. No fixed price per photo is promised.

Photos are sent to Gemini only after **Identify**; confirmation also sends up to six retrieved listing photos for comparison. Normalized reference photos and caches are held in process memory, with a 30-minute lifetime and bounded capacity. Metadata is removed; uploaded photos and reusable reference tokens are not saved in browser search history. Saved results retain the product description and comparison findings. Removing the reference clears its server cache; restarting the server also clears all references. Google/provider retention policies still apply. Closing a scan aborts the browser request but may not cancel an already-sent provider call.

Visually different, similar and unchecked offers use separate valuation pools from likely matches. Lens valuations stay low-confidence until exact product identity and condition are independently established.

This implementation is intended for a trusted local, single-process app. Public deployment needs authentication, user-isolated reference storage, shared quota controls and upload rate limits.

## Optional services

- `GEMINI_API_KEY`, `GEMINI_API_KEY_2` through `_5`, `GEMINI_API_KEYS`: optional authorized key pool. A configured key is not proof of a successful AI call. Live results without validated AI evidence remain on hold.
- `GEMINI_MODEL`: defaults to `gemini-3.8-flash`; `GEMINI_FALLBACK_MODEL` defaults to `gemini-3.6-flash`. Choose models actually available to your project. Requests have bounded timeouts and SDK retries disabled; the shared helper performs only the bounded retries described above.
- `GEMINI_KEY_PROJECTS`, `GEMINI_LOCAL_RPM`, `GEMINI_LOCAL_RPD`, `GEMINI_MAX_ATTEMPTS`: project-aware local scheduling and retry caps.
- `AI_OPERATION_BUDGET`, `AI_SHORTLIST_SIZE`, `AI_EVIDENCE_TTL`: per-search attempt cap, analyst batch size and successful evidence cache lifetime.
- `REEF_API_KEY`: provides reliable live Carousell and Mudah search data.
- `NEXSCOPE_API_KEY`: provides reliable Shopee Malaysia keyword-search data. Without it, the public-browser attempt may be rejected by Shopee.
- `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_MARKETPLACE_ID`: official eBay Browse API integration.
- `ETSY_API_KEY`, `ETSY_SHARED_SECRET`: official Etsy search integration.
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

Health/config mode is available at `GET /api/health`; `ai_configured` is separate from verified provider status. Inspect `agent_run` on search/chat/Lens responses and `GET /api/agents/runtime` for execution evidence. Optional search fields `planning_mode` (`auto`, `local`, `ai`) and `analysis_mode` (`smart`, `local`) allow explicit control; local analysis never claims AI review or emits live buy alerts.

## Tests

```bash
python -m unittest discover -s tests -v
node --test tests/chat-state.test.cjs
```

The tests cover marketplace-specific URL validation, query relevance, economics, variant classification, cross-market grouping, valuation confidence, seller trust, low-evidence retail risk gates, provider mapping, partial-source failures, and API behavior.
