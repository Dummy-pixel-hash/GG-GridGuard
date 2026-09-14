"""
BriefingContext — structured, grounded context assembled from risk-engine results.

This module is the "grounding layer".  Every piece of data the LLM receives
comes from the deterministic risk engine; no values are invented or estimated
by the model.

Design principle
----------------
The LLM is given a structured JSON-serialisable ``BriefingContext`` that
contains exactly the facts the prompt needs.  The prompt template then
instructs the model to reason *only* over the provided context and to refuse
to speculate about values not present.  This prevents hallucinated sensor
readings, invented incidents, or fabricated scores.

Usage
-----
    from normalisation.normaliser import normalise
    from risk_engine.calculator import score_asset
    from ai_briefing.context_builder import BriefingContextBuilder

    raw_inputs = normalise(raw_record)
    result = score_asset(raw_inputs)
    context = BriefingContextBuilder.build(result, raw_inputs)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from risk_engine.models import RiskInputs, RiskResult


# ---------------------------------------------------------------------------
# Human-readable labels used in context and prompts
# ---------------------------------------------------------------------------

_COMPONENT_LABELS: dict[str, str] = {
    "sensor_health":      "sensor health",
    "weather_risk":       "weather risk",
    "historical_failure": "historical failure rate",
    "asset_degradation":  "asset degradation",
    "grid_impact":        "grid impact",
}

_SEVERITY_LABEL: dict[str, str] = {
    "sensor_health":      (
        "abnormal sensor readings (temperature, partial discharge, oil quality, vibration)"
    ),
    "weather_risk":       (
        "severe weather exposure (wind, precipitation, temperature stress)"
    ),
    "historical_failure": (
        "a history of past failures and repeat-fault patterns"
    ),
    "asset_degradation":  (
        "long-run asset degradation (age, insulation condition, maintenance overdue)"
    ),
    "grid_impact":        (
        "high consequence of failure (customers served, critical facilities, cascade exposure)"
    ),
}


# ---------------------------------------------------------------------------
# Context dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SensorContext:
    """Grounded sensor facts for the briefing."""
    temperature_score: float
    vibration_score: float
    oil_quality_score: float
    partial_discharge_score: float
    missing_sensor_ratio: float
    missing_sensor_pct: int = 0  # human-readable percentage

    def __post_init__(self) -> None:
        self.missing_sensor_pct = round(self.missing_sensor_ratio * 100)


@dataclass
class WeatherContext:
    """Grounded weather facts for the briefing."""
    temperature_stress_score: float
    precipitation_score: float
    wind_storm_score: float
    forecast_hours: int


@dataclass
class HistoryContext:
    """Grounded failure history facts for the briefing."""
    failure_count_last_5yr: int
    failures_caused_by_weather: int
    last_failure_days_ago: Optional[int]
    repeat_failure_flag: bool
    mean_time_between_failures_days: Optional[float]


@dataclass
class DegradationContext:
    """Grounded degradation facts for the briefing."""
    age_years: float
    rated_lifespan_years: float
    past_rated_lifespan: bool
    cumulative_fault_events: int
    maintenance_overdue_days: int
    insulation_health_score: Optional[float]   # 0–100 (100 = fully failed)
    load_factor_avg: float


@dataclass
class GridImpactContext:
    """Grounded grid-impact facts for the briefing."""
    customers_served: int
    critical_facility_count: int
    peak_load_mw: float
    downstream_asset_count: int
    has_redundant_path: bool


@dataclass
class ComponentScoreContext:
    """All five component scores in one place for easy prompt injection."""
    sensor_health: float
    weather_risk: float
    historical_failure: float
    asset_degradation: float
    grid_impact: float

    def as_ranked_list(self) -> list[tuple[str, float]]:
        """Return component names and scores sorted from highest to lowest."""
        pairs = [
            ("sensor_health",      self.sensor_health),
            ("weather_risk",       self.weather_risk),
            ("historical_failure", self.historical_failure),
            ("asset_degradation",  self.asset_degradation),
            ("grid_impact",        self.grid_impact),
        ]
        return sorted(pairs, key=lambda x: x[1], reverse=True)


@dataclass
class BriefingContext:
    """
    Complete grounded context for one asset briefing.

    All values come directly from the deterministic risk engine.
    The LLM must reference only the data in this context when generating
    an explanation.

    Attributes
    ----------
    asset_id:
        The asset being briefed.
    asset_type:
        Human-readable type string (e.g. "transformer"), if available.
    overall_risk:
        Overall composite risk score, 0–100.
    risk_level:
        Risk classification string: "Normal" | "Watch" | "High" | "Critical".
    dominant_factor:
        The name of the component with the highest weighted contribution.
    dominant_factor_label:
        Human-readable version of dominant_factor.
    dominant_factor_description:
        One-sentence description of what drives this factor.
    components:
        All five component scores.
    sensors, weather, history, degradation, grid_impact:
        Raw inputs that fed into the component scores.
    notes:
        Free-text asset notes from the registry, if any.
    """

    asset_id: str
    asset_type: str
    overall_risk: float
    risk_level: str
    dominant_factor: str
    dominant_factor_label: str
    dominant_factor_description: str

    components: ComponentScoreContext
    sensors: SensorContext
    weather: WeatherContext
    history: HistoryContext
    degradation: DegradationContext
    grid_impact: GridImpactContext

    notes: str = ""

    def to_dict(self) -> dict:
        """Serialise to a plain dict for prompt injection."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

@dataclass
class AssetRegistryInfo:
    """
    Optional supplementary asset registry data.

    Pass this to ``BriefingContextBuilder.build()`` when you want asset_type
    and notes included in the context.  If omitted, both fields default to
    empty strings.
    """
    asset_type: str = "unknown"
    notes: str = ""


class BriefingContextBuilder:
    """
    Assembles a ``BriefingContext`` from risk-engine outputs.

    This is the only place where raw ``RiskResult`` and ``RiskInputs`` data
    is converted into the structure the briefing prompts consume.  Every fact
    in the resulting context is directly traceable to the risk engine.
    """

    @staticmethod
    def build(
        result: RiskResult,
        inputs: RiskInputs,
        *,
        registry: Optional[AssetRegistryInfo] = None,
    ) -> BriefingContext:
        """
        Build a ``BriefingContext`` from risk engine outputs.

        Parameters
        ----------
        result:
            Output of ``score_asset(inputs)``.
        inputs:
            The same ``RiskInputs`` that were passed to ``score_asset()``.
        registry:
            Optional static registry info (asset type, notes).

        Returns
        -------
        BriefingContext
            Fully populated grounded context ready for prompt injection.
        """
        reg = registry or AssetRegistryInfo()
        dom = result.dominant_factor

        return BriefingContext(
            asset_id=result.asset_id,
            asset_type=reg.asset_type,
            overall_risk=result.overall_risk,
            risk_level=result.risk_level.value,
            dominant_factor=dom,
            dominant_factor_label=_COMPONENT_LABELS.get(dom, dom),
            dominant_factor_description=_SEVERITY_LABEL.get(dom, dom),

            components=ComponentScoreContext(
                sensor_health=result.components.sensor_health,
                weather_risk=result.components.weather_risk,
                historical_failure=result.components.historical_failure,
                asset_degradation=result.components.asset_degradation,
                grid_impact=result.components.grid_impact,
            ),

            sensors=SensorContext(
                temperature_score=inputs.sensors.temperature_score,
                vibration_score=inputs.sensors.vibration_score,
                oil_quality_score=inputs.sensors.oil_quality_score,
                partial_discharge_score=inputs.sensors.partial_discharge_score,
                missing_sensor_ratio=inputs.sensors.missing_sensor_ratio,
            ),

            weather=WeatherContext(
                temperature_stress_score=inputs.weather.temperature_stress_score,
                precipitation_score=inputs.weather.precipitation_score,
                wind_storm_score=inputs.weather.wind_storm_score,
                forecast_hours=inputs.weather.forecast_hours,
            ),

            history=HistoryContext(
                failure_count_last_5yr=inputs.history.failure_count_last_5yr,
                failures_caused_by_weather=inputs.history.failures_caused_by_weather,
                last_failure_days_ago=inputs.history.last_failure_days_ago,
                repeat_failure_flag=inputs.history.repeat_failure_flag,
                mean_time_between_failures_days=inputs.history.mean_time_between_failures_days,
            ),

            degradation=DegradationContext(
                age_years=inputs.degradation.age_years,
                rated_lifespan_years=inputs.degradation.rated_lifespan_years,
                past_rated_lifespan=(
                    inputs.degradation.age_years > inputs.degradation.rated_lifespan_years
                ),
                cumulative_fault_events=inputs.degradation.cumulative_fault_events,
                maintenance_overdue_days=inputs.degradation.maintenance_overdue_days,
                insulation_health_score=inputs.degradation.insulation_health_score,
                load_factor_avg=inputs.degradation.load_factor_avg,
            ),

            grid_impact=GridImpactContext(
                customers_served=inputs.grid_impact.customers_served,
                critical_facility_count=inputs.grid_impact.critical_facility_count,
                peak_load_mw=inputs.grid_impact.peak_load_mw,
                downstream_asset_count=inputs.grid_impact.downstream_asset_count,
                has_redundant_path=inputs.grid_impact.has_redundant_path,
            ),

            notes=reg.notes,
        )
