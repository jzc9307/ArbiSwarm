<div align="center">

# 🐝 ArbiSwarm

### Autonomous Multi-Agent E-Commerce Arbitrage

**Hard-filter listings → analyze context → verify images → calculate margins → generate negotiation output**

<p>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white" alt="Streamlit">
  <img src="https://img.shields.io/badge/LangGraph-Multi--Agent-1C3C3C?style=for-the-badge" alt="LangGraph">
  <img src="https://img.shields.io/badge/Anthropic-Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white" alt="Anthropic">
  <img src="https://img.shields.io/badge/Pydantic-Validated-E92063?style=for-the-badge&logo=pydantic&logoColor=white" alt="Pydantic">
</p>

<p>
  <a href="#-overview">Overview</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-configuration">Configuration</a> •
  <a href="#-project-structure">Project Structure</a>
</p>

</div>

---

## ✨ Overview

**ArbiSwarm** is a hackathon-focused multi-agent system for evaluating e-commerce listings for potential resale opportunities.

The current demo uses cached **Carousell Malaysia-style listing data** rather than live scraping. Each candidate passes through a deterministic hard-filter before the AI swarm analyzes the remaining listings.

The goal is to separate cheap, deterministic checks from more expensive AI reasoning:

```text
Cached Listings
      │
      ▼
┌──────────────────────┐
│  Phase 1             │
│  Hard Filter         │
│  0 AI tokens         │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Agent 1             │
│  Context Analyst     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Agent 2             │
│  Vision Authenticator│
└──────────┬───────────┘
           │
     Low confidence?
        /       \
      Yes       No
       │         │
       ▼         │
  Re-analyze     │
       │         │
       └────┬────┘
            ▼
┌──────────────────────┐
│  Agent 3             │
│  Lead Strategist     │
└──────────┬───────────┘
           │
           ▼
   Profitability +
   Reasoning +
   Negotiation
```

---

## 🎯 What It Does

For every candidate listing, ArbiSwarm can:

- 🧹 Remove unsuitable listings before making AI calls
- 📝 Interpret messy seller descriptions
- 🔎 Identify condition issues, missing parts, and red flags
- 👁️ Compare listing photos against the title and description
- 💰 Calculate estimated resale margin using deterministic math
- 🧠 Combine agent findings into a final decision
- 💬 Generate a short negotiation message when appropriate
- 🔁 Re-run the context analysis when the initial confidence is low
- 📊 Display the entire process in a Streamlit dashboard

> **Important:** The Vision Authenticator is intentionally scoped to photo/text consistency. It is **not** a counterfeit or fraud detector.

---

## 🐝 Agent Swarm

| Agent | Responsibility | Output |
|---|---|---|
| 🔎 **Context Analyst** | Reads seller text and evaluates condition | Condition, flaws, missing parts, red flags, clarification flag |
| 👁️ **Vision Authenticator** | Checks whether photos match the listing text | Consistency score + mismatches |
| 🧭 **Lead Strategist** | Combines analysis with margin calculations | Profitability, reasoning, negotiation message |

### 🔁 Conditional Re-analysis

ArbiSwarm includes one controlled feedback loop.

If the Context Analyst marks a listing as requiring clarification, the Vision Agent's findings are attached to the listing description and the Context Analyst gets **one additional pass** before the Lead Strategist makes the final decision.

This keeps the workflow bounded instead of allowing an uncontrolled agent loop.

---

## 💸 Profitability Model

The margin calculation is performed in Python rather than trusting the LLM with arithmetic.

```text
platform_fee = listing_price × 5%
total_cost   = listing_price + platform_fee + RM8 shipping

margin % = ((resale_estimate - total_cost) / total_cost) × 100
```

The current alert threshold is:

```text
Minimum margin: 20%
Maximum listing price: RM60
Minimum seller rating: 4.0
Shipping assumption: RM8
Platform fee: 5%
```

These values are configurable in `config.py`.

---

## 🖥️ Dashboard

The Streamlit application provides a simple workflow:

1. Enter an estimated resale price.
2. Click **🐝 Start Swarm**.
3. Review Phase 1 hard-filter results.
4. Watch each AI agent process the retained listings.
5. Review margin and profitability.
6. Read the reasoning.
7. Copy/use the generated negotiation message when available.

### 📸 Screenshots / Demo

Add your own screenshots or GIFs here once available:

```text
assets/
├── dashboard.png
├── swarm-processing.gif
└── result.png
```

Then embed them like:

```md
![ArbiSwarm Dashboard](assets/dashboard.png)
```

---

## 🧰 Tech Stack

| Technology | Role |
|---|---|
| **Python** | Application logic |
| **Streamlit** | Interactive dashboard |
| **LangGraph** | Agent workflow/orchestration |
| **Anthropic Claude** | LLM-powered analysis |
| **Pydantic** | Strict structured agent outputs |
| **HTTPX** | Image retrieval |
| **Playwright** | Planned/available scraping dependency |
| **JSON** | Cached demo listing data |

The current repository intentionally uses cached listing data so the demo does not depend on live marketplace scraping.

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/jzc9307/ArbiSwarm.git
cd ArbiSwarm
```

### 2. Create a virtual environment

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows**

```powershell
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your Anthropic API key

**macOS / Linux**

```bash
export ANTHROPIC_API_KEY="your-api-key"
```

**Windows PowerShell**

```powershell
$env:ANTHROPIC_API_KEY="your-api-key"
```

### 5. Start the dashboard

```bash
streamlit run app.py
```

Streamlit will provide a local URL in the terminal.

---

## ⚙️ Configuration

The main business rules live in `config.py`:

```python
MAX_PRICE_MYR = 60
MIN_SELLER_RATING = 4.0

PLATFORM_FEE_PCT = 0.05
SHIPPING_COST_MYR = 8
MIN_MARGIN_PCT_TO_ALERT = 20

USE_CACHED_LISTINGS = True
CACHE_PATH = "cache/listings_raw.json"
```

You can adjust these values for different experiments.

### 🤖 Model

The current configuration uses:

```python
CHEAP_MODEL = "claude-haiku-4-5-20251001"
```

Keep API keys in environment variables rather than committing them to the repository.

---

## 🗂️ Project Structure

```text
ArbiSwarm/
├── app.py
├── config.py
├── filters.py
├── schemas.py
├── orchestrator.py
├── context_analyst.py
├── vision_authenticator.py
├── lead_strategist.py
├── _llm.py
├── listings_raw.json
├── requirements.txt
├── E-Commerce Arbitrage Swarm Blueprint.pdf
└── README.md
```

### Core files

| File | Purpose |
|---|---|
| `app.py` | Streamlit dashboard |
| `config.py` | API/model and business-rule configuration |
| `filters.py` | Deterministic Phase 1 filtering |
| `schemas.py` | Pydantic models for listing and agent outputs |
| `orchestrator.py` | LangGraph swarm workflow |
| `context_analyst.py` | Seller-description analysis |
| `vision_authenticator.py` | Photo/text consistency analysis |
| `lead_strategist.py` | Final decision + negotiation generation |
| `_llm.py` | Shared Claude JSON helper |
| `listings_raw.json` | Cached demo listing data |
| `requirements.txt` | Python dependencies |

---

## 🧱 Processing Pipeline

### Phase 1 — Hard Filter

The first phase is intentionally deterministic and costs **0 AI tokens**.

A listing is discarded when:

- Price exceeds `MAX_PRICE_MYR`
- Seller rating is below `MIN_SELLER_RATING`
- Description is empty

This reduces unnecessary model calls before the more expensive analysis stage.

### Phase 2 — Context Analysis

The Context Analyst extracts:

- True condition
- Specific flaws
- Missing parts
- Red flags
- Whether more clarification is needed

### Phase 2 — Vision Authentication

Up to three listing images can be supplied to the Vision Agent.

It checks:

- Color consistency
- Title/photo consistency
- Description/photo consistency
- Obvious catalog/stock-photo usage
- Whether there are enough usable images to judge consistency

### Phase 3 — Lead Strategy

The Lead Strategist receives:

- Original listing
- Context analysis
- Vision analysis
- Deterministically calculated margin

It produces:

- Profitability decision
- Reasoning
- Negotiation message when appropriate

The final margin and profitability flag are overwritten using Python calculations, rather than relying on the model's arithmetic.

---

## 🔌 Current Demo vs. Planned Expansion

| Capability | Current |
|---|:---:|
| Cached listing input | ✅ |
| Deterministic hard filtering | ✅ |
| Context analysis | ✅ |
| Image consistency analysis | ✅ |
| Margin calculation | ✅ |
| Negotiation generation | ✅ |
| LangGraph orchestration | ✅ |
| Streamlit dashboard | ✅ |
| Live marketplace scraper | 🚧 |
| Telegram / Discord alerts | 🚧 |
| Dedicated web frontend | 🚧 |
| Real market-average resale pricing | 🚧 |

The repository README currently identifies live Playwright scraping, Telegram/Discord webhook notifications, and a dedicated website frontend as future additions.

---

## 🧪 Development

Run the filter directly:

```bash
python filters.py
```

Run the Streamlit application:

```bash
streamlit run app.py
```

For development, consider adding:

```text
tests/
├── test_filters.py
├── test_margin.py
├── test_schemas.py
└── test_orchestrator.py
```

Useful areas to test include:

- Price/rating filtering
- Margin calculations
- Empty descriptions
- Agent schema validation
- Conditional re-analysis
- Missing image handling

---

## 🔐 Security & API Keys

Never commit your Anthropic API key.

Use environment variables:

```bash
export ANTHROPIC_API_KEY="..."
```

If a key is accidentally committed:

1. Revoke/rotate it immediately.
2. Remove it from the repository history.
3. Replace it with a new environment variable.
4. Check deployment and CI secrets.

---

## 🗺️ Roadmap

- [ ] Replace cached listings with a real authorized scraper
- [ ] Add live market-price estimation
- [ ] Add persistent opportunity history
- [ ] Add Telegram notifications
- [ ] Add Discord notifications
- [ ] Add a dedicated web frontend
- [ ] Add automated tests
- [ ] Add structured run logs
- [ ] Add configurable marketplace adapters
- [ ] Add better image-handling and retry logic

---

## 🤝 Contributing

Contributions and experiments are welcome.

A useful contribution should ideally:

1. Explain the problem or feature.
2. Keep agent outputs schema-valid.
3. Avoid putting deterministic calculations inside the LLM.
4. Include tests when practical.
5. Avoid committing secrets or credentials.

---

## ⚠️ Disclaimer

ArbiSwarm is an experimental/hackathon project for evaluating e-commerce listings.

Its outputs are estimates generated from listing information, configured assumptions, and AI analysis. They should not be treated as guarantees of authenticity, profitability, seller behavior, resale value, or financial return.

The current Vision Authenticator specifically checks **photo/text consistency** and should not be interpreted as a counterfeit or fraud-detection system.

Use marketplace data and automation only in accordance with the relevant platform's terms and applicable laws.

---

<div align="center">

### 🐝 ArbiSwarm

**From marketplace listings to structured arbitrage decisions.**

Made with Python • LangGraph • Claude • Streamlit

<br>

⭐ If you find the project useful, consider starring the repository.

</div>
