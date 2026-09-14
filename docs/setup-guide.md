# Setup Guide

> **This file is read by the automated evaluation pipeline. Be precise and complete.**

## Prerequisites

- **Python 3.10 or later** — the only runtime requirement
- **Git** — to clone the repository
- **Internet access** (optional) — Open-Meteo weather forecasts and the live LLM endpoint require network; the dashboard runs fully offline without them

No `pip install` is needed. GridGuard uses only the Python standard library at runtime.

## Environment Variables

Copy the example file:

```bash
cp src/.env.example src/.env
# or place it at the repo root:
cp src/.env.example .env
```

The server loads `src/.env`, then `./.env`, then any file pointed to by `GRIDGUARD_ENV`. Real shell environment variables always win over `.env` file values.

### LLM provider (AI briefings)

| Variable | Description | Required |
|---|---|---|
| `LLM_BASE_URL` | Base URL of any OpenAI-compatible endpoint | One of `LLM_BASE_URL` or `LLM_API_KEY` |
| `LLM_API_KEY` | API key for the endpoint | See above |
| `LLM_MODEL` | Model name passed to the endpoint (default: `gpt-4o-mini`) | No |
| `GRIDGUARD_LLM_PROVIDER` | Force provider: `openai` \| `watsonx` \| `mock` | No — auto-detected |
| `GRIDGUARD_LLM_MAX_TOKENS` | Max tokens per briefing (default: `512`) | No |
| `GRIDGUARD_LLM_TEMPERATURE` | Sampling temperature (default: `0.2`) | No |

Provider auto-detection:
- `openai` — when `LLM_BASE_URL` or `LLM_API_KEY` is set
- `watsonx` — when `WATSONX_API_KEY` is set and no `LLM_*` vars are present
- `mock` — when nothing is configured (safe default; AI briefings work offline)

### Optional: IBM watsonx.ai

| Variable | Description | Required |
|---|---|---|
| `WATSONX_API_KEY` | IBM Cloud API key | Only for `GRIDGUARD_LLM_PROVIDER=watsonx` |
| `WATSONX_PROJECT_ID` | watsonx.ai project ID | Same |
| `WATSONX_URL` | Inference endpoint (default: `https://us-south.ml.cloud.ibm.com`) | Same |

### Application

| Variable | Description | Required |
|---|---|---|
| `APP_PORT` | Dashboard port (default: `8000`) | No |
| `GRIDGUARD_DB` | Path to SQLite database file (default: `gridguard.db` at repo root) | No |

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/Dummy-pixel-hash/GG-GridGuard.git
cd GG-GridGuard

# 2. (Optional) configure a live LLM provider
cp src/.env.example src/.env
# Edit src/.env: set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
# Leave blank to use the offline mock provider
```

No further installation step is needed — there are no third-party dependencies at runtime.

## Running the Application

```bash
# From the repository root
python3 run_ui.py               # serves on http://localhost:8000
python3 run_ui.py 8080          # custom port
APP_PORT=8080 python3 run_ui.py # via environment variable
```

What startup does:

1. Loads `.env` files (prints which files were found)
2. Seeds the 8 synthetic demo assets into SQLite (`gridguard.db`, or `GRIDGUARD_DB` if set)
3. Normalises and scores every asset with the live risk engine
4. Persists a risk snapshot per asset in the storage layer
5. Prints the active LLM provider and model (or warns and falls back to mock)
6. Serves the operator dashboard at `http://localhost:8000`

Expected startup output:

```
GridGuard UI: scored 8 assets from the live risk engine.
GridGuard UI: database at /path/to/gridguard.db
GridGuard UI: loaded env from src/.env
GridGuard UI: AI provider 'openai' (model llama3)
GridGuard UI: serving on http://localhost:8000
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Operator dashboard (static HTML) |
| `GET` | `/api/summary` | Fleet counts, averages, customers at risk |
| `GET` | `/api/assets` | All assets with live engine scores |
| `GET` | `/api/assets/<id>` | Full detail for one asset |
| `GET` | `/api/priorities` | Ranked maintenance plan + crew pre-positioning |
| `GET` | `/api/briefing_info` | Active provider, model, offline status |
| `POST` | `/api/briefing` | Conversational AI answer (see below) |

`POST /api/briefing` request body:

```json
{
  "question": "What's wrong with TX-007?",
  "asset_id": "TX-007",
  "history": [
    {"role": "user",      "content": "Previous question"},
    {"role": "assistant", "content": "Previous answer"}
  ]
}
```

`asset_id` and `history` are optional. `history` enables conversational follow-up questions.

## Running Tests

```bash
python3 -m pytest -q
```

546 tests · 0 network calls · no credentials required. All tests pass with the offline mock provider by default.

```bash
# Verbose output with test names
python3 -m pytest -v

# One module only
python3 -m pytest src/tests/test_risk_engine.py -v
```

## LLM Provider Examples

**Ollama (local — no API key needed):**

```bash
# Install and pull a model: https://ollama.com
ollama pull llama3

# In src/.env:
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3
```

**OpenAI:**

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

**Groq (fast, free tier available):**

```bash
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_...
LLM_MODEL=llama-3.1-8b-instant
```

**IBM watsonx.ai:**

```bash
GRIDGUARD_LLM_PROVIDER=watsonx
WATSONX_API_KEY=your_key
WATSONX_PROJECT_ID=your_project_id
LLM_MODEL=ibm/granite-3-8b-instruct
```

Note: `ibm_watsonx_ai` SDK must be installed (`pip install ibm-watsonx-ai`) when using the watsonx provider.

## Troubleshooting

| Issue | Solution |
|---|---|
| `ModuleNotFoundError` | Ensure `python3 run_ui.py` is run from the **repository root** (not from inside `src/`) |
| LLM provider `unavailable` warning | Server fell back to offline mock — briefings still work. Check `LLM_BASE_URL`, `LLM_API_KEY`, and that the endpoint is reachable. |
| `401` from LLM endpoint | Check `LLM_API_KEY` in `.env` |
| `Connection refused` for local model | Ensure Ollama / llama.cpp is running and `LLM_BASE_URL` matches its port |
| Weather fetch fails | Open-Meteo needs no API key — a network error usually means a temporary outage or no internet access. Scores still work without live weather (demo uses synthetic weather data). |
| Port already in use | Set `APP_PORT=8080` in `.env` or pass the port as an argument: `python3 run_ui.py 8080` |
| `gridguard.db` not found | It is created automatically on first run in the repository root. Set `GRIDGUARD_DB` to control the path. |
