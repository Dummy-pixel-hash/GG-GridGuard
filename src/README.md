# GridGuard — Source Code

All application source code lives in this directory.

## Layout

```
src/
├── .env.example             ← Copy to src/.env or ./.env; never commit .env
│
├── risk_engine/             ← Composite 0–100 risk scorer (deterministic)
│   ├── calculator.py        ← score_asset(RiskInputs) → RiskResult
│   ├── models.py            ← RiskInputs, RiskResult, ComponentScores, RiskLevel
│   └── scoring/             ← Five independent component functions
│       ├── sensor_health.py      weight 0.30
│       ├── weather_risk.py       weight 0.20
│       ├── historical_failure.py weight 0.15
│       ├── asset_degradation.py  weight 0.15
│       └── grid_impact.py        weight 0.20
│
├── normalisation/           ← Physical-unit → 0–100 normaliser
│   ├── normaliser.py        ← normalise(RawAssetRecord) → RiskInputs
│   └── thresholds.py        ← IEC-based alarm thresholds (configurable)
│
├── lifecycle/               ← Asset state machine + replacement lineage
│   ├── engine.py            ← apply_fault, apply_repair, apply_replacement, advance_age
│   └── models.py            ← AssetLifecycleRecord, RetiredAssetRecord, FaultEvent, …
│
├── data/                    ← Raw type definitions + 8 synthetic demo assets
│   ├── raw_types.py         ← RawAssetRecord, RawSensorTelemetry, RawWeatherObservation, …
│   └── demo_assets.py       ← TX-001…TX-008 (Normal / Watch / High / Critical)
│
├── weather/                 ← Open-Meteo forecast integration
│   ├── client.py            ← Injectable HttpClient (real + mock)
│   ├── open_meteo.py        ← fetch_weather(lat, lon) → RawWeatherObservation
│   └── storm_classifier.py  ← Storm severity from wind speed
│
├── storage/                 ← SQLite persistence layer
│   ├── schema.py            ← create_all_tables()
│   ├── connection.py        ← get_connection(path)
│   ├── seeder.py            ← seed_demo_assets() — idempotent
│   ├── serialisation.py     ← JSON helpers for list fields
│   └── repositories/        ← AssetRepository, LifecycleRepository,
│                               RiskResultRepository, RetiredAssetRepository,
│                               GridTopologyRepository
│
├── ai_briefing/             ← Conversational AI layer (provider-agnostic)
│   ├── service.py           ← BriefingService: chat(), brief(), why_risk_level(), …
│   ├── prompts.py           ← Grounded + conversational prompt templates
│   ├── context_builder.py   ← RiskResult + RiskInputs → BriefingContext
│   ├── provider.py          ← OpenAIProvider, WatsonxProvider, MockProvider
│   └── config.py            ← BriefingConfig.from_env()
│
├── api/
│   ├── grid_service.py      ← GridState: startup scoring, answer_question()
│   └── server.py            ← Stdlib HTTP server + static file serving
│
├── frontend/
│   ├── index.html           ← Operator dashboard (single-page)
│   ├── app.js               ← Dashboard logic + AI assistant chat panel
│   └── styles.css
│
└── tests/                   ← 546 tests, 0 network calls
    ├── fixtures.py              Shared RiskInputs fixtures (Normal/Watch/High/Critical)
    ├── test_risk_engine.py      61 tests
    ├── test_normalisation.py   110 tests
    ├── test_lifecycle.py        94 tests
    ├── test_storage.py          67 tests
    ├── test_weather.py          61 tests
    ├── test_ai_briefing.py     145 tests
    └── test_api_service.py       8 tests
```

## Running Tests

```bash
# From the repository root
python3 -m pytest -q
```

## Running the Dashboard

```bash
# From the repository root (no pip install needed)
python3 run_ui.py
# → http://localhost:8000
```
