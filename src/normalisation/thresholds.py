"""
Alarm thresholds and reference values used by the normalisation layer.

All values are derived from industry standards or common utility practice:
  - IEC 60076-2   (transformer temperature limits)
  - IEC 60156     (oil dielectric strength)
  - ISO 10816     (vibration — adapted for power transformers)
  - Open-Meteo typical extreme values for mid-latitude distribution networks

These are kept separate from the normaliser logic so that an operator or
future ingestion layer can adjust thresholds per asset class without touching
the normalisation functions.

SYNTHETIC / DEMO DATA — thresholds are representative, not site-calibrated.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SensorThresholds:
    """
    Per-measurement alarm / reference thresholds.

    For each sensor the normaliser maps the raw value into [0, 100] using:
        score = clamp((raw - healthy_value) / (alarm_value - healthy_value), 0, 1) * 100

    So:
        raw == healthy_value  → score 0    (nominal)
        raw == alarm_value    → score 100  (alarm threshold reached)
        raw  > alarm_value    → score 100  (clamped at 100)

    For oil_dielectric_kv the mapping is *inverted* (higher kV = healthier):
        score = clamp((healthy_value - raw) / (healthy_value - alarm_value), 0, 1) * 100
    """

    # Top-oil temperature (°C)
    # IEC 60076-2: continuous rated = 55 °C rise over 40 °C ambient → 95 °C,
    # alarm typically set at 98 °C.
    top_oil_temp_healthy_c: float = 55.0   # nominal operating temp
    top_oil_temp_alarm_c: float = 98.0     # alarm threshold

    # Winding hot-spot temperature (°C)
    # IEC 60076-2: alarm at 128 °C (65 °C rise class + 40 °C ambient + tolerance)
    hot_spot_healthy_c: float = 78.0
    hot_spot_alarm_c: float = 128.0

    # Vibration velocity RMS (mm/s)
    # ISO 10816 / typical utility practice for power transformers
    vibration_healthy_mm_s: float = 1.0
    vibration_alarm_mm_s: float = 4.5

    # Oil dielectric strength (kV) — inverted: lower kV = worse
    # IEC 60156: new oil ≥ 70 kV; degraded/alarm < 30 kV
    oil_dielectric_healthy_kv: float = 70.0
    oil_dielectric_alarm_kv: float = 30.0

    # Partial discharge (pC)
    # Background noise level ~ 100 pC; alarm typically > 1000 pC
    pd_healthy_pc: float = 100.0
    pd_alarm_pc: float = 1_000.0


@dataclass(frozen=True)
class WeatherThresholds:
    """
    Reference and alarm values for weather normalisation.

    Temperature stress
    ------------------
    Heat stress: max_temp_c is mapped linearly from temp_neutral_c (25 °C, no
    stress) → temp_alarm_c (45 °C, full alarm).  Temperatures below 25 °C
    produce zero heat stress.

    Cold stress: min_temp_c is mapped linearly from temp_cold_neutral_c (0 °C,
    no stress) → temp_cold_alarm_c (-15 °C, full alarm).  The neutral point
    for cold is 0 °C — temperatures between 0 °C and 25 °C are neither heat-
    nor cold-stressed.  Previously this was incorrectly set to 25 °C, meaning
    any temperature below 25 °C produced spurious cold stress.

    Precipitation
    -------------
    0 mm → 0 score; 100 mm / 72-hour window → saturating alarm (flash-flood
    risk for outdoor switchgear and cable ducts).

    Wind speed
    ----------
    0 km/h → 0; 120 km/h → alarm (structural risk; Beaufort 12 hurricane starts
    at ~118 km/h).

    Storm warning level (0–3) adds a direct boost on top of the raw wind score.
    This represents meteorologist-assessed certainty of a severe event that the
    instantaneous wind-speed number alone may not yet capture (e.g. a developing
    system where peak gusts are still hours away):
        level 0 → 0 pts
        level 1 → 15 pts
        level 2 → 35 pts
        level 3 → 60 pts
    The final wind/storm score is clamped at 100.
    """

    # Heat stress thresholds (applied to max_temp_c)
    temp_neutral_c: float = 25.0    # at or below this → zero heat stress
    temp_alarm_c: float = 45.0      # at or above → heat stress score 100

    # Cold stress thresholds (applied to min_temp_c)
    # Neutral at 0 °C: temperatures between 0 °C and 25 °C are stress-free.
    # Freezing temperatures begin to cause mechanical stress to outdoor equipment.
    temp_cold_neutral_c: float = 0.0   # at or above this → zero cold stress
    temp_cold_alarm_c: float = -15.0   # at or below → cold stress score 100

    # Precipitation
    precip_alarm_mm: float = 100.0   # mm / forecast window

    # Wind speed
    wind_alarm_kmh: float = 120.0    # km/h

    # Storm warning level boost (index = level 0–3)
    storm_level_boost: tuple[float, ...] = (0.0, 15.0, 35.0, 60.0)


# Default instances used by the normaliser (can be overridden per asset class)
DEFAULT_SENSOR_THRESHOLDS = SensorThresholds()
DEFAULT_WEATHER_THRESHOLDS = WeatherThresholds()
