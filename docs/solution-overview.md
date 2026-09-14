# Solution Overview

## What We Built

GridGuard is a grid asset intelligence and maintenance-prioritization system.
It fuses the four data dimensions a utility already owns — asset sensor
telemetry, weather forecasts (Open-Meteo), historical incident records, and
asset degradation/lifecycle state — into one explainable **0–100 risk score
per asset**. It then ranks assets by risk **and** grid impact to produce a
prioritized maintenance plan and crew pre-positioning recommendations, with
AI-generated explanations and recommended actions for operators.

GridGuard is a **standalone application**: it runs without IBM Bob installed
or active.  Bob is used during the hackathon as a development and
demonstration interface; it is not a runtime dependency.

## How It Works

1. **Ingest asset state** — sensor telemetry (temperature, vibration, oil
   quality, partial discharge), the asset registry, and degradation signals:
   age, operating history, previous faults, maintenance/repair history,
   accumulated wear.
2. **Ingest weather** — Open-Meteo forecasts (temperature, rainfall,
   wind/storm severity) for each asset's location.
3. **Maintain lifecycle state** — when an asset is repaired or replaced, the
   old asset's full history is preserved (incidents, sensor history,
   maintenance) while the successor asset starts with a clean
   health/degradation state, linked to its predecessor.
4. **Score risk** — the risk engine combines sensor condition, weather
   exposure, incident history, and degradation into a 0–100 composite score
   per asset.  Weights: sensor health 30%, weather 20%, historical failure
   15%, asset degradation 15%, grid impact 20%.  Classification bands:
   Normal (0–39), Watch (40–69), High (70–84), Critical (85–100).
   See `src/risk_engine/` for the full implementation.
5. **Score grid impact** — customers served, critical facilities (hospitals,
   water plants, emergency services), peak load MW, downstream asset cascade
   exposure, and N-1 redundancy determine the consequence-of-failure score.
   Non-critical sub-scores are discounted 40% when a redundant supply path
   exists; critical-facility points are never discounted.
   See `src/risk_engine/scoring/grid_impact.py`.
6. **Prioritize** — assets are ranked by combined risk and grid impact into a
   prioritized maintenance plan; crew pre-positioning focuses on
   weather-exposed, high-impact assets ahead of forecast events.
7. **Explain** — for high-priority assets, an AI briefing explains the
   contributing factors in plain language and recommends concrete actions
   (inspect, accelerate maintenance, transfer load, pre-position crews).
   The briefing service is provider-agnostic: any OpenAI-compatible LLM
   endpoint works (see Configuration below).
8. **Optionally surface via IBM Bob** — during the hackathon, operators can
   ask questions in natural language through Bob; Bob calls GridGuard's tools
   and returns scores, rankings, plans, and briefings in conversation.

## Architecture Diagram

See [architecture.md](architecture.md) for the full diagram and data flow.

```
asset sensors + weather (Open-Meteo) + incident history + degradation/lifecycle
        │
        ▼
  risk engine  ──►  0–100 score per asset  ──►  outage-prone-area views
        │
        ▼
  prioritization (risk × grid impact)  ──►  maintenance plan + crew pre-positioning
        │
        ▼
  AI briefing layer  ──►  grounded prompts  ──►  LLM endpoint (configurable)
        │                                                │
        └──────────────── explanations ◄────────────────┘
        │
        ▼
  operator  (optionally via IBM Bob in hackathon context)
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Fuse four data silos in one engine | The problem is combination, not collection — each source alone under-predicts; together they are actionable weeks in advance |
| Deterministic, interpretable 0–100 risk score | Operators must trust and audit the score, and no labeled failure corpus is available at hackathon scale to train a black-box model. Weights are locked: sensor 30%, weather 20%, historical failure 15%, degradation 15%, grid impact 20%. Tunable by changing constants in `calculator.py`. |
| Risk and grid impact kept separate, combined only at prioritization | "Likely to fail" and "failure is catastrophic" are different questions — a lower-probability failure on a hospital feeder can outrank a likely failure on a redundant branch |
| Lifecycle state machine with preserved lineage | A replacement transformer must not inherit its predecessor's wear, but its history must survive for incident learning — repair/replacement retires the record with history intact and spawns a clean-state successor |
| AI for explanation only, not scoring | Deterministic scoring stays auditable; the LLM adds the "why" and "what to do" operators actually need. The LLM receives pre-computed scores as grounded context and is instructed not to invent values outside that context. |
| Provider-agnostic LLM layer | GridGuard works with any OpenAI-compatible endpoint — self-hosted (Ollama, llama.cpp) or hosted (OpenAI, Groq, Together AI, watsonx). Configured via three env vars: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. Defaults to `MockProvider` when no credentials are set so CI and offline use require no configuration. |
| Open-Meteo for weather | Free, no API key for non-commercial use, global forecast coverage — realistic for a hackathon and credible for a live demo |
| GridGuard runs without IBM Bob | Bob is a hackathon development partner, not a runtime dependency. GridGuard's risk engine, lifecycle engine, weather integration, and AI briefing layer all operate independently. |

## Configuration — LLM Provider

GridGuard's AI briefing layer is provider-agnostic.  Set these environment
variables in `.env` (copy from `src/.env.example`):

```bash
# Point at any OpenAI-compatible endpoint
LLM_BASE_URL=http://localhost:11434/v1  # e.g. Ollama
LLM_API_KEY=                            # empty for local servers
LLM_MODEL=llama3
```

The provider is auto-selected:
- **`openai`** (default) when `LLM_BASE_URL` or `LLM_API_KEY` is set
- **`watsonx`** when `WATSONX_API_KEY` is set and no `LLM_*` vars are present
- **`mock`** when nothing is configured — safe for CI, offline demos, testing

To use IBM watsonx.ai instead:
```bash
GRIDGUARD_LLM_PROVIDER=watsonx
WATSONX_API_KEY=your_key
WATSONX_PROJECT_ID=your_project
LLM_MODEL=ibm/granite-3-8b-instruct
```

## IBM Technologies

- **IBM Bob** — used as the operator-facing interface during the hackathon.
  GridGuard's capabilities (asset risk lookup, ranked priority lists,
  maintenance plan, crew pre-positioning plan, AI briefings) are exposed to
  Bob as callable tools; operators ask natural-language questions and Bob
  invokes GridGuard to answer.  Integration mechanism: MCP tool server
  (planned).  **GridGuard does not require Bob to run.**
- **IBM watsonx.ai** — supported as an optional LLM provider via the
  `ibm_watsonx_ai` SDK (`GRIDGUARD_LLM_PROVIDER=watsonx`).  Not required;
  any OpenAI-compatible endpoint is the primary path.

## Status

491 tests passing, 0 network calls in test suite.

Implemented:
- Risk engine (`src/risk_engine/`) — 61 tests
- Normalisation layer (`src/normalisation/`) + IEC-based thresholds — 110 tests
- Synthetic demo dataset: 8 assets across all four risk bands (`src/data/`)
- Open-Meteo weather integration (`src/weather/`) — 61 tests
  - `fetch_weather(lat, lon) → RawWeatherObservation`; `fetch_weather_with_fallback` for graceful degradation
  - Injectable `HttpClient` — no network calls in tests
- Lifecycle engine (`src/lifecycle/`) — 94 tests
  - State machine: ACTIVE / FAULTED / RETIRED
  - `apply_fault`, `apply_maintenance`, `apply_repair`, `apply_replacement`, `advance_age`
  - All functions pure / immutable
- Storage layer (`src/storage/`) — SQLite, 67 tests
  - Asset registry, lifecycle records, risk results, retired assets
  - Seeder for 8-asset demo dataset
- AI briefing layer (`src/ai_briefing/`) — 98 tests
  - `BriefingContextBuilder` — grounded context from risk engine outputs
  - `OpenAIProvider` — primary runtime provider (OpenAI-compatible endpoints)
  - `WatsonxProvider` — optional IBM watsonx.ai path
  - `MockProvider` — deterministic, no network, used in CI
  - `BriefingService` — four briefing types: concise, why-critical, factors, inspection

Remaining TBD:
- Prioritization ranking API (combining risk + grid impact into ordered list)
- IBM Bob MCP tool surface (tool definitions, parameter schemas)
- Dashboard / operator UI
