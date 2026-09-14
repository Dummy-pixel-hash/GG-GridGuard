"""GridGuard API package — thin read/serve layer over the existing backend.

This package does NOT reimplement any backend logic.  It only:

1. Loads the synthetic demo records from ``data.demo_assets``.
2. Normalises them with ``normalisation.normaliser.normalise``.
3. Scores them with ``risk_engine.calculator.score_asset``.
4. Seeds / reads the existing SQLite storage layer (assets, topology,
   lifecycle, risk snapshots).
5. Answers operator questions through the existing
   ``ai_briefing.BriefingService`` provider abstraction.

All numbers served to the frontend therefore come straight from the real
risk engine — nothing is hardcoded for display purposes.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

from ai_briefing import (
    BriefingConfig,
    BriefingService,
    BriefingType,
    ConversationTurn,
)
from ai_briefing.context_builder import AssetRegistryInfo, BriefingContextBuilder
from data.demo_assets import ALL_ASSETS
from data.raw_types import RawAssetRecord
from normalisation.normaliser import normalise
from risk_engine.calculator import score_asset
from risk_engine.models import RiskInputs, RiskResult
from storage.connection import get_connection
from storage.repositories.assets import AssetRepository
from storage.repositories.grid_topology import GridTopologyRepository
from storage.repositories.lifecycle import LifecycleRepository
from storage.repositories.retired import RetiredAssetRepository as RetiredRepository
from storage.repositories.risk_results import RiskResultRepository
from storage.schema import create_all_tables
from storage.seeder import seed_demo_assets


# ---------------------------------------------------------------------------
# Minimal .env loader (stdlib only — no python-dotenv dependency)
# ---------------------------------------------------------------------------

def _parse_dotenv(path: str) -> dict[str, str]:
    """Parse a KEY=VALUE dotenv file; ignore blanks, comments, and `export `."""
    values: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if key and key.replace("_", "").isalnum():
                values[key] = val
    return values


def load_dotenv() -> list[str]:
    """Load GridGuard env vars from .env files into os.environ.

    Candidate files (all that exist are applied, later ones win):
      1. ``src/.env`` next to this package's source tree
      2. ``.env`` at the repository root
      3. ``$GRIDGUARD_ENV`` if set (explicit override, wins over both)

    Real environment variables always win — files only fill in what is
    unset.  Returns the list of files that were actually loaded.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.dirname(here)
    repo_root = os.path.dirname(src_dir)
    candidates = [
        os.path.join(src_dir, ".env"),
        os.path.join(repo_root, ".env"),
    ]
    explicit = os.getenv("GRIDGUARD_ENV", "")
    if explicit:
        candidates.append(explicit)
    loaded: list[str] = []
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            for key, val in _parse_dotenv(path).items():
                if key not in os.environ:
                    os.environ[key] = val
            loaded.append(path)
        except OSError:
            continue
    return loaded


# ---------------------------------------------------------------------------
# Status mapping: engine RiskLevel -> operator-facing status
# ---------------------------------------------------------------------------

LEVEL_TO_STATUS = {
    "Normal": "Healthy",
    "Watch": "Monitoring",
    "High": "High",
    "Critical": "Critical",
}

STATUS_ORDER = ["Critical", "High", "Monitoring", "Healthy"]

COMPONENT_LABELS = {
    "sensor_health": "Sensor health",
    "weather_risk": "Weather risk",
    "historical_failure": "Historical failure",
    "asset_degradation": "Asset degradation",
    "grid_impact": "Grid impact",
}

COMPONENT_WEIGHTS = {
    "sensor_health": 0.30,
    "weather_risk": 0.20,
    "historical_failure": 0.15,
    "asset_degradation": 0.15,
    "grid_impact": 0.20,
}

_ACTION_BY_STATUS = {
    "Critical": ("Inspect today", "Immediate — dispatch crew within 24h"),
    "High": ("Inspect this week", "Priority — schedule within 7 days"),
    "Monitoring": ("Plan inspection", "Routine — schedule within 30 days"),
    "Healthy": ("Routine monitoring", "No action — next scheduled check"),
}


# ---------------------------------------------------------------------------
# Grid state
# ---------------------------------------------------------------------------

class GridState:
    """All UI-facing data, computed once at startup from the real backend."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        # Pick up LLM keys / model from .env files (env vars always win).
        self.env_files: list[str] = load_dotenv()
        self.conn: sqlite3.Connection = get_connection(db_path)
        create_all_tables(self.conn)
        seed_demo_assets(self.conn)

        self._asset_repo = AssetRepository(self.conn)
        self._topo_repo = GridTopologyRepository(self.conn)
        self._lifecycle_repo = LifecycleRepository(self.conn)
        self._retired_repo = RetiredRepository(self.conn)
        self._risk_repo = RiskResultRepository(self.conn)

        # Keep raw records by id for telemetry/weather detail.
        self._raw: dict[str, RawAssetRecord] = {
            r.metadata.asset_id: r for r in ALL_ASSETS
        }
        # Normalised inputs + engine results by id.
        self._inputs: dict[str, RiskInputs] = {}
        self._results: dict[str, RiskResult] = {}

        for raw in ALL_ASSETS:
            inputs = normalise(raw)
            result = score_asset(inputs)
            self._inputs[raw.metadata.asset_id] = inputs
            self._results[raw.metadata.asset_id] = result
            # Persist a scoring snapshot (storage layer stays the audit trail).
            try:
                self._risk_repo.insert(result)
            except Exception:
                pass

        self._assets: list[dict] = [
            self._build_asset_view(aid) for aid in sorted(self._raw)
        ]
        self._briefing_service: BriefingService | None = None
        self._provider_warning: str = ""

    # -- public accessors -------------------------------------------------

    @property
    def assets(self) -> list[dict]:
        return self._assets

    def get_asset(self, asset_id: str) -> dict | None:
        for a in self._assets:
            if a["id"] == asset_id:
                return a
        return None

    def summary(self) -> dict:
        counts = {"Healthy": 0, "Monitoring": 0, "High": 0, "Critical": 0}
        for a in self._assets:
            counts[a["status"]] += 1
        risks = [a["overall_risk"] for a in self._assets]
        customers_at_risk = sum(
            a["grid_impact"]["customers_served"]
            for a in self._assets
            if a["status"] in ("High", "Critical")
        )
        critical_facilities = sum(
            a["grid_impact"]["critical_facility_count"]
            for a in self._assets
            if a["status"] in ("High", "Critical")
        )
        regions: dict[str, dict] = {}
        for a in self._assets:
            r = regions.setdefault(
                a["region"], {"assets": 0, "worst_risk": 0.0, "worst_status": "Healthy"}
            )
            r["assets"] += 1
            if a["overall_risk"] > r["worst_risk"]:
                r["worst_risk"] = a["overall_risk"]
                r["worst_status"] = a["status"]
        return {
            "total": len(self._assets),
            "counts": counts,
            "average_risk": round(sum(risks) / len(risks), 1) if risks else 0.0,
            "highest_risk": max(risks) if risks else 0.0,
            "customers_at_risk": customers_at_risk,
            "critical_facilities_exposed": critical_facilities,
            "regions": regions,
        }

    def priorities(self) -> dict:
        """Ranked maintenance plan + crew pre-positioning (derived, not stored).

        Ranking is deterministic: overall engine risk first, grid-impact
        component as the tie-break so that a failure which hurts the grid
        most is worked first.  No scoring logic lives here — this only
        presents ``RiskResult`` outputs as an operator work plan.
        """
        ranked = sorted(
            self._assets,
            key=lambda a: (a["overall_risk"], a["components"]["grid_impact"]),
            reverse=True,
        )
        plan = []
        for i, a in enumerate(ranked, start=1):
            action, detail = _ACTION_BY_STATUS[a["status"]]
            plan.append(
                {
                    "rank": i,
                    "asset_id": a["id"],
                    "substation": a["substation"],
                    "region": a["region"],
                    "status": a["status"],
                    "overall_risk": a["overall_risk"],
                    "dominant_factor": a["dominant_factor"],
                    "dominant_factor_label": a["dominant_factor_label"],
                    "customers_served": a["grid_impact"]["customers_served"],
                    "critical_facilities": a["grid_impact"][
                        "critical_facility_count"
                    ],
                    "has_redundant_path": a["grid_impact"]["has_redundant_path"],
                    "recommended_action": action,
                    "action_detail": detail,
                }
            )
        # Crew pre-positioning: weather-exposed, high-consequence assets.
        crew: dict[str, dict] = {}
        for a in self._assets:
            exposed = (
                a["components"]["weather_risk"] >= 60.0
                or a["weather_raw"]["storm_warning_level"] >= 2
            )
            consequential = (
                a["overall_risk"] >= 70.0
                or a["grid_impact"]["critical_facility_count"] > 0
            )
            if exposed and consequential:
                cell = crew.setdefault(
                    a["region"], {"region": a["region"], "assets": [], "reason": ""}
                )
                cell["assets"].append(a["id"])
        crew_list = []
        for region, cell in crew.items():
            worst = max(
                (x for x in self._assets if x["id"] in cell["assets"]),
                key=lambda x: x["overall_risk"],
            )
            cell["reason"] = (
                f"Storm exposure (weather {worst['components']['weather_risk']}/100, "
                f"warning level {worst['weather_raw']['storm_warning_level']}) on "
                f"{worst['id']} ({worst['status']}, {worst['overall_risk']}/100) — "
                f"stage crews in {region} before the front arrives."
            )
            crew_list.append(cell)
        crew_list.sort(
            key=lambda c: max(
                x["overall_risk"] for x in self._assets if x["id"] in c["assets"]
            ),
            reverse=True,
        )
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {
            "generated_at": generated_at,
            "maintenance_plan": plan,
            "crew_prepositioning": crew_list,
        }

    def briefing_info(self) -> dict:
        # Initialise the provider now so the active backend (or a fallback
        # warning) is known up front instead of on the first question.
        self._service()
        config = BriefingConfig.from_env()
        active = self._briefing_service_provider_name() or config.provider_name
        return {
            "provider": active,
            "model": config.model_id,
            "offline": active == "mock",
            "env_files": self.env_files,
            "warning": self._provider_warning,
        }

    # -- AI briefing router (backend only; frontend never implements AI) ---

    def answer_question(
        self,
        question: str,
        asset_id: str | None = None,
        history: list[dict] | None = None,
    ) -> dict:
        """Route an operator message through the conversational BriefingService.

        All turns go through ``BriefingService.chat()`` which uses a single
        adaptive prompt.  The model sees the conversation history and the
        grounded asset context and decides how much to say — short follow-ups
        get short answers, casual reactions get natural replies, full questions
        get full briefings.

        If the provider call fails, a deterministic grounded fallback is
        composed from the risk-engine outputs so the demo never invents numbers.

        Parameters
        ----------
        question:
            The operator's current message.
        asset_id:
            The asset currently selected in the UI (takes priority over any
            asset ID mentioned in the question text).
        history:
            List of previous turns as ``{"role": "user"|"assistant",
            "content": str}`` dicts.  Serialised form used by the HTTP API.
        """
        target = self._resolve_target(question, asset_id)
        service = self._service()

        # Convert the serialised history dicts into ConversationTurn objects.
        # Guard against non-list values (e.g. a stale client sending a string).
        raw_history = history if isinstance(history, list) else []
        turns: list[ConversationTurn] = []
        for h in raw_history:
            role = str(h.get("role", "user"))
            content = str(h.get("content", ""))
            if content:
                turns.append(ConversationTurn(role=role, content=content))

        briefing_type = BriefingType.CONVERSATIONAL
        text = ""
        asset_ids: list[str] = []
        risks: dict[str, float] = {}
        levels: dict[str, str] = {}

        try:
            if target is not None:
                result = self._results[target]
                inputs = self._inputs[target]
                reg = self._registry(target)
                ctx = BriefingContextBuilder.build(result, inputs, registry=reg)
                res = service.chat(question, history=turns, ctx=ctx)
                briefing_type, text = res.briefing_type, res.text
                asset_ids = [target]
                risks = {target: result.overall_risk}
                levels = {target: result.risk_level.value}
            else:
                # No specific asset — pass a fleet summary as grounded context.
                top = sorted(
                    self._assets,
                    key=lambda a: (a["overall_risk"], a["components"]["grid_impact"]),
                    reverse=True,
                )[:4]
                fleet_summary = _build_fleet_summary(top)
                res = service.chat(question, history=turns, fleet_summary=fleet_summary)
                briefing_type, text = res.briefing_type, res.text
                asset_ids = [a["id"] for a in top]
                risks = {a["id"]: a["overall_risk"] for a in top}
                levels = {a["id"]: a["risk_level"] for a in top}
                # Always append the exact ranked list for fleet questions so the
                # demo answer contains real numbers even with the offline mock.
                text = _with_ranked_list(text, top)
        except Exception:
            briefing_type = BriefingType.CONVERSATIONAL
            text = self._grounded_fallback(question, target)
            if target is not None:
                a = self.get_asset(target)
                assert a is not None
                asset_ids = [target]
                risks = {target: a["overall_risk"]}
                levels = {target: a["risk_level"]}

        info = self.briefing_info()
        return {
            "text": text,
            "briefing_type": str(briefing_type.value)
            if isinstance(briefing_type, BriefingType)
            else str(briefing_type),
            "asset_ids": asset_ids,
            "overall_risks": risks,
            "risk_levels": levels,
            "provider": info["provider"],
            "model": info["model"],
            "grounded": True,
            "notice": self._provider_warning,
        }

    # -- internals ----------------------------------------------------------

    def _service(self) -> BriefingService:
        if self._briefing_service is None:
            config = BriefingConfig.from_env()
            # Force offline-safe mock unless the operator configured a real
            # endpoint — the demo must run with zero credentials.
            if config.provider_name not in ("openai", "watsonx", "mock"):
                config.provider_name = "mock"
            if config.provider_name in ("openai", "watsonx") and not _provider_ready(
                config
            ):
                config.provider_name = "mock"
            try:
                self._briefing_service = BriefingService.from_config(config)
            except Exception as exc:  # missing SDK, bad URL, no network at init…
                self._provider_warning = (
                    f"Configured provider '{config.provider_name}' unavailable "
                    f"({exc}); fell back to offline mock."
                )
                config.provider_name = "mock"
                self._briefing_service = BriefingService.from_config(config)
        return self._briefing_service

    def _briefing_service_provider_name(self) -> str | None:
        provider = getattr(self._briefing_service, "_provider", None)
        if provider is None:
            return None
        return {
            "OpenAIProvider": "openai",
            "WatsonxProvider": "watsonx",
            "MockProvider": "mock",
        }.get(type(provider).__name__, "mock")

    def _registry(self, asset_id: str) -> AssetRegistryInfo:
        a = self.get_asset(asset_id)
        if a is None:
            return AssetRegistryInfo()
        return AssetRegistryInfo(asset_type=a["asset_type"], notes=a["notes"])

    def _resolve_target(
        self, question: str, asset_id: str | None
    ) -> str | None:
        if asset_id and asset_id in self._raw:
            return asset_id
        match = re.search(r"\b(TX-?\d{3})\b", (question or "").upper())
        if match:
            candidate = match.group(1).replace("TX", "TX-") if "-" not in match.group(1) else match.group(1)
            candidate = candidate.upper()
            if candidate in self._raw:
                return candidate
        return None

    def _grounded_fallback(self, question: str, asset_id: str | None) -> str:
        """Deterministic engine-grounded text used only if the LLM call fails."""
        if asset_id is None:
            top = sorted(
                self._assets,
                key=lambda a: (a["overall_risk"], a["components"]["grid_impact"]),
                reverse=True,
            )[:3]
            lines = [
                f"{i}. {a['id']} — {a['status']} ({a['overall_risk']}/100), "
                f"driven by {a['dominant_factor_label']}."
                for i, a in enumerate(top, start=1)
            ]
            return (
                "Inspection priority for today (from live risk-engine scores):\n"
                + "\n".join(lines)
            )
        a = self.get_asset(asset_id)
        assert a is not None
        ranked = sorted(a["components"].items(), key=lambda kv: kv[1], reverse=True)
        top3 = ", ".join(
            f"{COMPONENT_LABELS[k]} {v}/100" for k, v in ranked[:3]
        )
        return (
            f"{a['id']} ({a['substation']}) is rated {a['status']} with an overall "
            f"risk of {a['overall_risk']}/100. Top contributors: {top3}. "
            f"Primary driver: {a['dominant_factor_label']}. "
            f"{_ACTION_BY_STATUS[a['status']][1]}."
        )

    def _build_asset_view(self, asset_id: str) -> dict:
        raw = self._raw[asset_id]
        inputs = self._inputs[asset_id]
        result = self._results[asset_id]
        meta = self._asset_repo.get(asset_id)
        topo = self._topo_repo.get(asset_id)
        lc = self._lifecycle_repo.get(asset_id)

        status = LEVEL_TO_STATUS[result.risk_level.value]
        action, action_detail = _ACTION_BY_STATUS[status]

        # Lifecycle view: prefer the stored record (single source of truth),
        # fall back to the raw snapshot fields if storage is unavailable.
        if lc is not None:
            fault_history = [asdict(e) for e in lc.fault_history]
            maint_history = [asdict(e) for e in lc.maintenance_history]
            lifecycle = {
                "state": lc.state.value,
                "age_years": lc.age_years,
                "rated_lifespan_years": lc.rated_lifespan_years,
                "past_rated_lifespan": lc.is_past_rated_lifespan,
                "remaining_life_years": round(lc.remaining_life_years, 1),
                "insulation_health_pct": lc.insulation_health_pct,
                "cumulative_fault_events": lc.cumulative_fault_events,
                "maintenance_overdue_days": lc.maintenance_overdue_days,
                "average_load_factor": lc.average_load_factor,
                "failure_count_last_5yr": lc.failure_count_last_5yr,
                "failures_caused_by_weather": lc.failures_caused_by_weather,
                "last_failure_days_ago": lc.last_failure_days_ago,
                "repeat_fault_active": lc.repeat_fault_active,
                "fault_history": fault_history,
                "maintenance_history": maint_history,
                "predecessor_asset_id": lc.predecessor_asset_id,
            }
        else:
            d = raw.degradation
            lifecycle = {
                "state": "active",
                "age_years": d.age_years,
                "rated_lifespan_years": meta.rated_lifespan_years if meta else 40.0,
                "past_rated_lifespan": d.age_years
                > (meta.rated_lifespan_years if meta else 40.0),
                "remaining_life_years": round(
                    (meta.rated_lifespan_years if meta else 40.0) - d.age_years, 1
                ),
                "insulation_health_pct": d.insulation_health_pct,
                "cumulative_fault_events": d.cumulative_fault_events,
                "maintenance_overdue_days": d.maintenance_overdue_days,
                "average_load_factor": d.average_load_factor,
                "failure_count_last_5yr": raw.incidents.failure_count_last_5yr,
                "failures_caused_by_weather": raw.incidents.failures_caused_by_weather,
                "last_failure_days_ago": raw.incidents.last_failure_days_ago,
                "repeat_fault_active": raw.incidents.repeat_mode_flag,
                "fault_history": [],
                "maintenance_history": [],
                "predecessor_asset_id": None,
            }

        # Lineage: retired predecessors / successors known to storage.
        lineage: dict = {"predecessor": None, "successor_of_retired": None}
        try:
            if lifecycle["predecessor_asset_id"]:
                pred = self._retired_repo.get(lifecycle["predecessor_asset_id"])
                if pred is not None:
                    lineage["predecessor"] = {
                        "asset_id": pred.asset_id,
                        "age_at_retirement_years": pred.age_at_retirement_years,
                        "retirement_reason": pred.retirement_reason,
                        "successor_asset_id": pred.successor_asset_id,
                    }
            by_succ = self._retired_repo.get_by_successor(asset_id)
            if by_succ is not None:
                lineage["successor_of_retired"] = {
                    "asset_id": by_succ.asset_id,
                    "retirement_reason": by_succ.retirement_reason,
                }
        except Exception:
            pass

        t = raw.telemetry
        w = raw.weather
        return {
            "id": asset_id,
            "asset_type": meta.asset_type if meta else raw.metadata.asset_type,
            "substation": meta.location.substation_name
            if meta
            else raw.metadata.location.substation_name,
            "region": meta.location.region if meta else raw.metadata.location.region,
            "latitude": meta.location.latitude if meta else raw.metadata.location.latitude,
            "longitude": meta.location.longitude
            if meta
            else raw.metadata.location.longitude,
            "rated_kva": meta.rated_kva if meta else raw.metadata.rated_kva,
            "rated_voltage_kv": meta.rated_voltage_kv
            if meta
            else raw.metadata.rated_voltage_kv,
            "commissioned_year": meta.commissioned_year
            if meta
            else raw.metadata.commissioned_year,
            "notes": meta.notes if meta else raw.metadata.notes,
            # Live engine outputs:
            "status": status,
            "risk_level": result.risk_level.value,
            "overall_risk": result.overall_risk,
            "components": {
                "sensor_health": result.components.sensor_health,
                "weather_risk": result.components.weather_risk,
                "historical_failure": result.components.historical_failure,
                "asset_degradation": result.components.asset_degradation,
                "grid_impact": result.components.grid_impact,
            },
            "component_weights": dict(COMPONENT_WEIGHTS),
            "component_labels": dict(COMPONENT_LABELS),
            "dominant_factor": result.dominant_factor,
            "dominant_factor_label": COMPONENT_LABELS.get(
                result.dominant_factor, result.dominant_factor
            ),
            "recommended_action": action,
            "action_detail": action_detail,
            # Raw evidence behind the scores:
            "sensors_raw": {
                "top_oil_temp_c": t.top_oil_temp_c,
                "winding_hot_spot_c": t.winding_hot_spot_c,
                "vibration_mm_s": t.vibration_mm_s,
                "oil_dielectric_kv": t.oil_dielectric_kv,
                "partial_discharge_pc": t.partial_discharge_pc,
                "load_factor_current": t.load_factor_current,
            },
            "sensors_norm": {
                "temperature_score": inputs.sensors.temperature_score,
                "vibration_score": inputs.sensors.vibration_score,
                "oil_quality_score": inputs.sensors.oil_quality_score,
                "partial_discharge_score": inputs.sensors.partial_discharge_score,
                "missing_sensor_ratio": inputs.sensors.missing_sensor_ratio,
            },
            "weather_raw": {
                "max_temp_c": w.max_temp_c,
                "min_temp_c": w.min_temp_c,
                "precipitation_mm": w.precipitation_mm,
                "wind_speed_max_kmh": w.wind_speed_max_kmh,
                "storm_warning_level": w.storm_warning_level,
                "forecast_hours": w.forecast_hours,
            },
            "weather_norm": {
                "temperature_stress_score": inputs.weather.temperature_stress_score,
                "precipitation_score": inputs.weather.precipitation_score,
                "wind_storm_score": inputs.weather.wind_storm_score,
                "forecast_hours": inputs.weather.forecast_hours,
            },
            "history": {
                "failure_count_last_5yr": raw.incidents.failure_count_last_5yr,
                "failures_caused_by_weather": raw.incidents.failures_caused_by_weather,
                "last_failure_days_ago": raw.incidents.last_failure_days_ago,
                "repeat_mode_flag": raw.incidents.repeat_mode_flag,
                "mean_time_between_failures_days": raw.incidents.mean_time_between_failures_days,
            },
            "degradation": {
                "age_years": raw.degradation.age_years,
                "cumulative_fault_events": raw.degradation.cumulative_fault_events,
                "maintenance_overdue_days": raw.degradation.maintenance_overdue_days,
                "insulation_health_pct": raw.degradation.insulation_health_pct,
                "average_load_factor": raw.degradation.average_load_factor,
            },
            "grid_impact": {
                "customers_served": topo.customers_served if topo else 0,
                "critical_facility_count": topo.critical_facility_count if topo else 0,
                "critical_facility_names": list(topo.critical_facility_names)
                if topo
                else [],
                "peak_load_mw": topo.peak_load_mw if topo else 0.0,
                "downstream_asset_count": topo.downstream_asset_count if topo else 0,
                "has_redundant_path": bool(topo.has_n1_redundancy) if topo else True,
            },
            "lifecycle": lifecycle,
            "lineage": lineage,
        }


def _build_fleet_summary(top: list[dict]) -> str:
    """Build a grounded plaintext fleet summary for conversational prompts.

    This is injected as ``fleet_summary`` when no specific asset is selected
    so the model has real numbers to reason over even for fleet-wide questions.
    """
    lines = [
        f"{i}. {a['id']} ({a['substation']}) — {a['status']}, "
        f"risk {a['overall_risk']}/100, "
        f"driven by {a['dominant_factor_label']}, "
        f"{a['grid_impact']['customers_served']:,} customers, "
        f"{'N-1 redundant' if a['grid_impact']['has_redundant_path'] else 'no redundancy'}."
        for i, a in enumerate(top, start=1)
    ]
    return "Top assets by risk (live engine scores):\n" + "\n".join(lines)


def _with_ranked_list(text: str, top: list[dict]) -> str:
    """Append the exact engine-ranked inspection list to a prioritisation answer.

    This is presentation of existing ``RiskResult`` outputs (same ordering as
    the maintenance plan), not a second AI implementation — it guarantees the
    demo answer always contains the real ranked numbers even when the
    offline mock provider returns its generic acknowledgement.
    """
    lines = [
        f"{i}. {a['id']} — {a['status']} ({a['overall_risk']}/100), "
        f"driven by {a['dominant_factor_label']}; "
        f"{a['grid_impact']['customers_served']:,} customers, "
        f"{'N-1 redundant' if a['grid_impact']['has_redundant_path'] else 'no redundancy'}."
        for i, a in enumerate(top, start=1)
    ]
    return text.rstrip() + "\n\nLive ranked list (risk engine):\n" + "\n".join(lines)


def _provider_ready(config: BriefingConfig) -> bool:
    """True when a non-mock provider has the credentials/URL it needs."""
    if config.provider_name == "openai":
        return bool(config.llm_base_url or config.llm_api_key)
    if config.provider_name == "watsonx":
        return bool(config.watsonx_api_key and config.watsonx_project_id)
    return True


def default_db_path() -> str:
    """On-disk demo database next to the repository root (overridable)."""
    env = os.getenv("GRIDGUARD_DB", "")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(repo_root, "gridguard.db")
