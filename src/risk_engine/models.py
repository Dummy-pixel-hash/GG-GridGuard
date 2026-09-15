"""
Domain models for the GridGuard risk engine.

All input values are described with their expected ranges and units so that
callers (ingestion layer, tests, future API) have an unambiguous contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


@dataclass
class SensorReadings:
    """
    Normalised sensor telemetry for one asset at one point in time.

    Each field represents the *current severity* of the underlying signal,
    expressed as a 0–100 normalised score where 0 = perfectly healthy and
    100 = maximum observed / alarm-threshold exceeded.

    Attributes:
        temperature_score: Derived from measured temperature relative to the
            asset's rated operating range (0 = cool/nominal, 100 = at or
            beyond thermal limit).
        vibration_score: Vibration level relative to alarm threshold
            (0 = silent, 100 = at/beyond threshold).
        oil_quality_score: Oil degradation index (0 = new oil, 100 = failed
            dielectric / severe contamination).
        partial_discharge_score: Partial-discharge activity (0 = none, 100 =
            continuous / severe PD detected).
        load_score: Current load as a fraction of rated capacity, normalised
            to 0–100 where 100 = fully loaded.  A load_factor_current of 1.0
            (100% of rated) maps to a score of 100.  This signal reflects
            instantaneous thermal and mechanical stress from load, separate
            from the long-run average used in asset_degradation.
        missing_sensor_ratio: Fraction of the four primary diagnostic sensors
            (temperature, vibration, oil, PD) that are unavailable/offline.
            0.0 = all present, 1.0 = all missing.  Missing sensors inflate the
            health score because absent data is a risk, not a guarantee of
            health.  load_factor_current is not counted in this ratio because
            it is a metering channel, not a diagnostic sensor.
    """

    temperature_score: float = 0.0        # 0–100
    vibration_score: float = 0.0          # 0–100
    oil_quality_score: float = 0.0        # 0–100
    partial_discharge_score: float = 0.0  # 0–100
    load_score: float = 0.0               # 0–100  (current load fraction × 100)
    missing_sensor_ratio: float = 0.0     # 0.0–1.0


@dataclass
class WeatherConditions:
    """
    Weather exposure scores for the asset's location over the forecast window.

    Each field is a 0–100 normalised severity; 0 = benign, 100 = extreme.

    Attributes:
        temperature_stress_score: Heat or cold stress relative to the asset's
            operating envelope (high summer heat or deep freeze both score
            high).
        precipitation_score: Rainfall/flooding intensity (0 = dry, 100 =
            extreme rainfall / flood risk).
        wind_storm_score: Wind and storm severity (0 = calm, 100 = hurricane /
            severe storm).
        forecast_hours: Look-ahead window used to derive these scores (default
            72 hours).  Scores already integrate over this window; this field
            is metadata for audit trails.
    """

    temperature_stress_score: float = 0.0  # 0–100
    precipitation_score: float = 0.0       # 0–100
    wind_storm_score: float = 0.0          # 0–100
    forecast_hours: int = 72


@dataclass
class HistoricalFailureRecord:
    """
    Aggregated failure / incident history for one asset.

    Attributes:
        failure_count_last_5yr: Total recorded failures in the last 5 years.
        failures_caused_by_weather: Subset of the above that were
            weather-triggered (amplifies risk when a weather event is also
            forecast).
        mean_time_between_failures_days: Average days between failures.
            0 or None means no prior failures (treated as infinite MTBF).
        last_failure_days_ago: Days since the most recent failure.  None if
            the asset has never failed.
        repeat_failure_flag: True if the most recent failure mode is the same
            as the one before (indicates an underlying fault not yet resolved).
    """

    failure_count_last_5yr: int = 0
    failures_caused_by_weather: int = 0
    mean_time_between_failures_days: Optional[float] = None
    last_failure_days_ago: Optional[int] = None
    repeat_failure_flag: bool = False


@dataclass
class AssetDegradationState:
    """
    Long-run degradation and lifecycle state for one asset.

    Attributes:
        age_years: Asset age in years from commissioning (or from last
            full replacement).
        rated_lifespan_years: Manufacturer / utility rated service life.
            Defaults to 40 years for power transformers.
        cumulative_fault_events: Total number of fault events (not just
            outage-causing failures) in the asset's lifetime.
        maintenance_overdue_days: Days past the scheduled maintenance
            date.  0 = on schedule, negative = performed early.
        insulation_health_score: Insulation condition from DGA / inspection
            (0 = new, 100 = failed/replaced).  Optional; None if unavailable.
        load_factor_avg: Average load as a fraction of rated capacity over
            the asset's life (0.0–1.0).  Higher sustained overloading
            accelerates degradation.
    """

    age_years: float = 0.0
    rated_lifespan_years: float = 40.0
    cumulative_fault_events: int = 0
    maintenance_overdue_days: int = 0
    insulation_health_score: Optional[float] = None  # 0–100
    load_factor_avg: float = 0.5                      # 0.0–1.0


@dataclass
class GridImpactFactors:
    """
    Consequence-of-failure factors that are independent of asset condition.

    Attributes:
        customers_served: Number of end customers on this asset's feeder.
        critical_facility_count: Count of hospitals, water plants, emergency
            services, or other critical facilities downstream.
        peak_load_mw: Peak load in megawatts delivered through this asset.
        downstream_asset_count: Number of other grid assets that would lose
            supply if this asset fails (cascade exposure).
        has_redundant_path: True if an alternative supply path exists (N-1
            compliant) — reduces impact score because automatic transfer
            limits customer impact.
    """

    customers_served: int = 0
    critical_facility_count: int = 0
    peak_load_mw: float = 0.0
    downstream_asset_count: int = 0
    has_redundant_path: bool = True


@dataclass
class RiskInputs:
    """All inputs required to score one asset."""

    asset_id: str
    sensors: SensorReadings = field(default_factory=SensorReadings)
    weather: WeatherConditions = field(default_factory=WeatherConditions)
    history: HistoricalFailureRecord = field(default_factory=HistoricalFailureRecord)
    degradation: AssetDegradationState = field(default_factory=AssetDegradationState)
    grid_impact: GridImpactFactors = field(default_factory=GridImpactFactors)


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Risk classification thresholds per the GridGuard specification."""

    NORMAL = "Normal"      # 0–39
    WATCH = "Watch"        # 40–69
    HIGH = "High"          # 70–84
    CRITICAL = "Critical"  # 85–100


@dataclass
class ComponentScores:
    """
    The five independent component scores (each 0–100) before weighting.

    These are retained in the result so that operators and the AI briefing
    layer can explain *which* dimension drove the overall score.
    """

    sensor_health: float      # 0–100  weight 0.30
    weather_risk: float       # 0–100  weight 0.20
    historical_failure: float # 0–100  weight 0.15
    asset_degradation: float  # 0–100  weight 0.15
    grid_impact: float        # 0–100  weight 0.20


@dataclass
class RiskResult:
    """Fully scored output for one asset."""

    asset_id: str
    overall_risk: float          # 0–100, rounded to 1 decimal place
    risk_level: RiskLevel
    components: ComponentScores
    dominant_factor: str         # name of the component with the highest weighted contribution
