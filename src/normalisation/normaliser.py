"""
GridGuard normalisation layer.

Converts a ``RawAssetRecord`` (physical-unit measurements) into a
``RiskInputs`` object (0–100 normalised scores) ready for the risk engine.

Public API
----------
    normalise(record, *, sensor_thresholds=None, weather_thresholds=None) -> RiskInputs
    NormalisationError  — raised when a record is structurally invalid

Design principles
-----------------
1. Every function is pure and stateless — same inputs always produce the
   same outputs.
2. Missing sensor values are handled conservatively: a missing reading
   contributes to ``missing_sensor_ratio`` and the available sensors are
   scored on their own; the missing-sensor penalty in the risk engine then
   accounts for the uncertainty.
3. All scores are clamped to [0, 100]; no value can escape this range.
4. Validation is explicit and fast-fail via ``NormalisationError`` so
   callers know immediately when data is structurally wrong (as opposed to
   merely having extreme readings, which is valid and expected).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from data.raw_types import (
    RawAssetRecord,
    RawSensorTelemetry,
    RawWeatherObservation,
    RawDegradationRecord,
)
from risk_engine.models import (
    AssetDegradationState,
    GridImpactFactors,
    HistoricalFailureRecord,
    RiskInputs,
    SensorReadings,
    WeatherConditions,
)
from normalisation.thresholds import (
    DEFAULT_SENSOR_THRESHOLDS,
    DEFAULT_WEATHER_THRESHOLDS,
    SensorThresholds,
    WeatherThresholds,
)


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

class NormalisationError(ValueError):
    """Raised when a RawAssetRecord contains structurally invalid data."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp a float to [lo, hi]."""
    return max(lo, min(hi, value))


def _linear_score(
    raw: float,
    healthy: float,
    alarm: float,
    inverted: bool = False,
) -> float:
    """
    Map a raw measurement linearly onto [0, 100].

    Args:
        raw:      The measured value.
        healthy:  The value that should produce a score of 0.
        alarm:    The value that should produce a score of 100.
        inverted: If True, higher raw values are *healthier* (e.g. oil kV).

    Returns:
        Float in [0, 100].
    """
    span = alarm - healthy
    if span == 0:
        # Degenerate thresholds — return 0 or 100 based on which side raw is on
        return 0.0 if raw <= healthy else 100.0

    if inverted:
        # Higher raw is healthier: score rises as raw falls below healthy
        score = (healthy - raw) / (healthy - alarm) * 100.0
    else:
        score = (raw - healthy) / span * 100.0

    return _clamp(score)


def _count_missing(*values: Optional[float]) -> int:
    """Count how many of the provided optional values are None."""
    return sum(1 for v in values if v is None)


# ---------------------------------------------------------------------------
# Sensor normalisation
# ---------------------------------------------------------------------------

def _normalise_sensors(
    telemetry: RawSensorTelemetry,
    thresholds: SensorThresholds,
) -> SensorReadings:
    """
    Convert physical-unit sensor readings to normalised 0–100 scores.

    Uses the *worst* available temperature indicator (top-oil or hot-spot)
    for the temperature score so that a missing hot-spot sensor falls back
    to top-oil gracefully without masking risk.

    Missing sensors contribute to ``missing_sensor_ratio`` (4 primary diagnostic
    sensors: temperature, vibration, oil, PD).  ``load_factor_current`` is a
    metering channel and is not counted in missing_sensor_ratio.
    """
    # --- Temperature score: worst of the two temperature sensors available ---
    temp_scores: list[float] = []
    if telemetry.top_oil_temp_c is not None:
        temp_scores.append(_linear_score(
            telemetry.top_oil_temp_c,
            thresholds.top_oil_temp_healthy_c,
            thresholds.top_oil_temp_alarm_c,
        ))
    if telemetry.winding_hot_spot_c is not None:
        temp_scores.append(_linear_score(
            telemetry.winding_hot_spot_c,
            thresholds.hot_spot_healthy_c,
            thresholds.hot_spot_alarm_c,
        ))

    # If both temperature sensors are missing, treat as None (missing)
    temperature_score: Optional[float] = max(temp_scores) if temp_scores else None

    # --- Vibration score ---
    vibration_score: Optional[float] = None
    if telemetry.vibration_mm_s is not None:
        vibration_score = _linear_score(
            telemetry.vibration_mm_s,
            thresholds.vibration_healthy_mm_s,
            thresholds.vibration_alarm_mm_s,
        )

    # --- Oil quality score (inverted: lower kV = worse) ---
    oil_score: Optional[float] = None
    if telemetry.oil_dielectric_kv is not None:
        oil_score = _linear_score(
            telemetry.oil_dielectric_kv,
            thresholds.oil_dielectric_healthy_kv,
            thresholds.oil_dielectric_alarm_kv,
            inverted=True,
        )

    # --- Partial discharge score ---
    pd_score: Optional[float] = None
    if telemetry.partial_discharge_pc is not None:
        pd_score = _linear_score(
            telemetry.partial_discharge_pc,
            thresholds.pd_healthy_pc,
            thresholds.pd_alarm_pc,
        )

    # --- Current load score ---
    # load_factor_current ∈ [0, 1]; a fully loaded asset (1.0) scores 100.
    # None (meter offline) is treated as 0.0 — no load penalty when unknown,
    # as load is a metering channel not a diagnostic alarm.
    load_score: float = 0.0
    if telemetry.load_factor_current is not None:
        load_score = _clamp(telemetry.load_factor_current * 100.0)

    # --- Missing sensor ratio ---
    # The four "primary" diagnostic channels are: temperature, vibration, oil, PD.
    # Temperature counts as missing only if *both* temperature sensors are missing.
    # load_factor_current is NOT counted here (metering, not diagnostics).
    n_missing = _count_missing(temperature_score, vibration_score, oil_score, pd_score)
    missing_ratio = n_missing / 4.0

    return SensorReadings(
        temperature_score=temperature_score if temperature_score is not None else 0.0,
        vibration_score=vibration_score if vibration_score is not None else 0.0,
        oil_quality_score=oil_score if oil_score is not None else 0.0,
        partial_discharge_score=pd_score if pd_score is not None else 0.0,
        load_score=load_score,
        missing_sensor_ratio=missing_ratio,
    )


# ---------------------------------------------------------------------------
# Weather normalisation
# ---------------------------------------------------------------------------

def _normalise_weather(
    obs: RawWeatherObservation,
    thresholds: WeatherThresholds,
) -> WeatherConditions:
    """
    Convert physical-unit weather observations to normalised 0–100 scores.

    Temperature stress
    ------------------
    Uses the *maximum* of heat stress and cold stress so that both extreme
    heat and extreme cold register appropriately.

    Storm warning boost
    -------------------
    The storm_warning_level (0–3) adds a flat bonus to the raw wind/storm
    score, representing meteorological certainty of a severe event that the
    wind-speed number alone may not yet capture.
    """
    # Heat stress: max_temp_c above neutral threshold
    heat_stress = _linear_score(
        obs.max_temp_c,
        thresholds.temp_neutral_c,
        thresholds.temp_alarm_c,
    )

    # Cold stress: min_temp_c below the cold-neutral threshold (0 °C).
    # Temperatures between 0 °C and 25 °C are neither heat- nor cold-stressed.
    cold_stress = 0.0
    if obs.min_temp_c < thresholds.temp_cold_neutral_c:
        cold_stress = _linear_score(
            obs.min_temp_c,
            thresholds.temp_cold_neutral_c,
            thresholds.temp_cold_alarm_c,
            inverted=True,
        )

    temperature_stress_score = _clamp(max(heat_stress, cold_stress))

    # Precipitation
    precipitation_score = _clamp(
        (obs.precipitation_mm / thresholds.precip_alarm_mm) * 100.0
    )

    # Wind / storm severity
    wind_raw = _clamp(
        (obs.wind_speed_max_kmh / thresholds.wind_alarm_kmh) * 100.0
    )
    level = max(0, min(3, obs.storm_warning_level))
    storm_boost = thresholds.storm_level_boost[level]
    wind_storm_score = _clamp(wind_raw + storm_boost)

    return WeatherConditions(
        temperature_stress_score=round(temperature_stress_score, 2),
        precipitation_score=round(precipitation_score, 2),
        wind_storm_score=round(wind_storm_score, 2),
        forecast_hours=obs.forecast_hours,
    )


# ---------------------------------------------------------------------------
# Degradation normalisation
# ---------------------------------------------------------------------------

def _normalise_degradation(
    deg: RawDegradationRecord,
    rated_lifespan_years: float,
) -> AssetDegradationState:
    """
    Pass degradation data through to ``AssetDegradationState``.

    The insulation_health_pct field uses a 0–100% convention where 100% is
    healthy; the risk engine's insulation_health_score uses 0–100 where 100
    is failed.  This function inverts the convention.

    load_factor_current is the *current* load fraction; average_load_factor
    in the degradation record is the historic average.  We use the historic
    average for the degradation state (long-run wear) — the current load
    factor is normalised to load_score and weighted into the sensor-health
    component (5%) as a real-time stress signal.
    """
    insulation_health_score: Optional[float] = None
    if deg.insulation_health_pct is not None:
        # Invert: 100% healthy → score 0; 0% healthy → score 100
        insulation_health_score = _clamp(100.0 - deg.insulation_health_pct)

    return AssetDegradationState(
        age_years=deg.age_years,
        rated_lifespan_years=rated_lifespan_years,
        cumulative_fault_events=deg.cumulative_fault_events,
        maintenance_overdue_days=max(0, deg.maintenance_overdue_days),
        insulation_health_score=insulation_health_score,
        load_factor_avg=_clamp(deg.average_load_factor, 0.0, 1.0),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(record: RawAssetRecord) -> None:
    """
    Raise ``NormalisationError`` if the record contains structurally invalid
    values that would make normalisation produce nonsense outputs.

    This is a fast-fail pre-check; it does *not* reject missing sensor data
    (that is valid — it drives the missing_sensor_ratio instead).
    """
    meta = record.metadata
    if not meta.asset_id or not meta.asset_id.strip():
        raise NormalisationError("asset_id must be a non-empty string")

    if meta.rated_lifespan_years <= 0:
        raise NormalisationError(
            f"[{meta.asset_id}] rated_lifespan_years must be > 0, "
            f"got {meta.rated_lifespan_years}"
        )

    deg = record.degradation
    if deg.age_years < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] age_years must be >= 0, got {deg.age_years}"
        )

    if deg.insulation_health_pct is not None:
        if not (0.0 <= deg.insulation_health_pct <= 100.0):
            raise NormalisationError(
                f"[{meta.asset_id}] insulation_health_pct must be 0–100, "
                f"got {deg.insulation_health_pct}"
            )

    if not (0.0 <= deg.average_load_factor <= 1.0):
        raise NormalisationError(
            f"[{meta.asset_id}] average_load_factor must be 0.0–1.0, "
            f"got {deg.average_load_factor}"
        )

    inc = record.incidents
    if inc.failures_caused_by_weather < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] failures_caused_by_weather must be >= 0"
        )
    if inc.failure_count_last_5yr < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] failure_count_last_5yr must be >= 0"
        )
    if inc.failures_caused_by_weather > inc.failure_count_last_5yr:
        raise NormalisationError(
            f"[{meta.asset_id}] failures_caused_by_weather ({inc.failures_caused_by_weather}) "
            f"> failure_count_last_5yr ({inc.failure_count_last_5yr})"
        )
    if inc.last_failure_days_ago is not None and inc.last_failure_days_ago < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] last_failure_days_ago must be >= 0 or None"
        )

    topo = record.topology
    if topo.customers_served < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] customers_served must be >= 0"
        )
    if topo.critical_facility_count < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] critical_facility_count must be >= 0"
        )
    if topo.peak_load_mw < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] peak_load_mw must be >= 0"
        )
    if topo.downstream_asset_count < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] downstream_asset_count must be >= 0"
        )

    wx = record.weather
    if not (0 <= wx.storm_warning_level <= 3):
        raise NormalisationError(
            f"[{meta.asset_id}] storm_warning_level must be 0–3, "
            f"got {wx.storm_warning_level}"
        )
    if math.isnan(wx.precipitation_mm) or wx.precipitation_mm < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] precipitation_mm must be >= 0"
        )
    if math.isnan(wx.wind_speed_max_kmh) or wx.wind_speed_max_kmh < 0:
        raise NormalisationError(
            f"[{meta.asset_id}] wind_speed_max_kmh must be >= 0"
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def normalise(
    record: RawAssetRecord,
    *,
    sensor_thresholds: Optional[SensorThresholds] = None,
    weather_thresholds: Optional[WeatherThresholds] = None,
) -> RiskInputs:
    """
    Convert a ``RawAssetRecord`` into a ``RiskInputs`` ready for the risk engine.

    Args:
        record:             The raw asset record to normalise.
        sensor_thresholds:  Override the default IEC-based sensor thresholds.
                            Pass ``None`` (default) to use ``DEFAULT_SENSOR_THRESHOLDS``.
        weather_thresholds: Override the default weather thresholds.
                            Pass ``None`` (default) to use ``DEFAULT_WEATHER_THRESHOLDS``.

    Returns:
        ``RiskInputs`` with all scores in [0, 100].

    Raises:
        ``NormalisationError`` if the record contains structurally invalid data.
    """
    _validate(record)

    st = sensor_thresholds or DEFAULT_SENSOR_THRESHOLDS
    wt = weather_thresholds or DEFAULT_WEATHER_THRESHOLDS

    sensors = _normalise_sensors(record.telemetry, st)
    weather = _normalise_weather(record.weather, wt)
    degradation = _normalise_degradation(
        record.degradation, record.metadata.rated_lifespan_years
    )

    history = HistoricalFailureRecord(
        failure_count_last_5yr=record.incidents.failure_count_last_5yr,
        failures_caused_by_weather=record.incidents.failures_caused_by_weather,
        mean_time_between_failures_days=record.incidents.mean_time_between_failures_days,
        last_failure_days_ago=record.incidents.last_failure_days_ago,
        repeat_failure_flag=record.incidents.repeat_mode_flag,
    )

    grid_impact = GridImpactFactors(
        customers_served=record.topology.customers_served,
        critical_facility_count=record.topology.critical_facility_count,
        peak_load_mw=record.topology.peak_load_mw,
        downstream_asset_count=record.topology.downstream_asset_count,
        has_redundant_path=record.topology.has_n1_redundancy,
    )

    return RiskInputs(
        asset_id=record.metadata.asset_id,
        sensors=sensors,
        weather=weather,
        history=history,
        degradation=degradation,
        grid_impact=grid_impact,
    )
