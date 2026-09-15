"""
Sensor health scoring (weight: 30% of overall risk).

A sensor health score of 0 means every sensor is nominal; 100 means every
sensor is at or beyond its alarm threshold (or fully offline).

Scoring formula
---------------
Base score = weighted average of five sensor/metering signals:

    temperature       35%
    partial_discharge 30%
    oil_quality       20%
    vibration         10%
    current load       5%

Temperature, PD, oil, and vibration are the four primary diagnostic sensors.
Current load (load_score) is a real-time metering signal: a fully loaded asset
(100%) scores 100 on this dimension, contributing up to 5 points to the sensor
health score.  This reflects the instantaneous thermal and mechanical stress
from load; the long-run load average is already captured in asset_degradation.

The weighting reflects field failure statistics: thermal runaway and partial
discharge are the primary precursors to transformer failure; oil degradation is
a lagging indicator of internal distress; vibration matters more for rotating
plant; load is a context signal, not a fault indicator.

Missing-sensor penalty
----------------------
When sensors are offline the score is *unknown*, not *safe*.  Each missing
sensor fraction (0–1) adds up to 40 points to the base score, capped at 100.

    penalty = missing_sensor_ratio * 40

Only the four primary diagnostic sensors (temperature, vibration, oil, PD) are
counted in missing_sensor_ratio; load_factor_current is a metering channel.
A fully sensor-blind asset (all four offline) receives a penalty of +40, which
at the 30% overall weight contributes 12 points to overall risk — enough to
ensure a fully blind asset cannot be rated Normal on sensor evidence alone.
Previously the cap was 20, meaning an all-blind asset only reached an overall
sensor contribution of 6, which was too conservative to surface as a concern.
"""

from __future__ import annotations

from ..models import SensorReadings

# Weights for the five sensor/metering dimensions (must sum to 1.0)
_TEMPERATURE_WEIGHT = 0.35
_PD_WEIGHT = 0.30
_OIL_WEIGHT = 0.20
_VIBRATION_WEIGHT = 0.10
_LOAD_WEIGHT = 0.05

assert abs(
    _TEMPERATURE_WEIGHT + _PD_WEIGHT + _OIL_WEIGHT + _VIBRATION_WEIGHT + _LOAD_WEIGHT - 1.0
) < 1e-9, "Sensor weights must sum to 1.0"

# Maximum additive penalty for missing sensors (all 4 offline → +40).
# Raised from 20 to 40 so that a fully sensor-blind asset scores ≥ 40 on the
# sensor component, preventing it from appearing Normal on sensor evidence alone.
_MISSING_SENSOR_MAX_PENALTY = 40.0


def score_sensor_health(readings: SensorReadings) -> float:
    """
    Return a 0–100 sensor health risk score.

    Higher = worse condition / higher risk.

    Args:
        readings: Normalised sensor readings for the asset.

    Returns:
        Float in [0, 100].
    """
    base = (
        readings.temperature_score * _TEMPERATURE_WEIGHT
        + readings.partial_discharge_score * _PD_WEIGHT
        + readings.oil_quality_score * _OIL_WEIGHT
        + readings.vibration_score * _VIBRATION_WEIGHT
        + readings.load_score * _LOAD_WEIGHT
    )

    # Conservative: missing sensors inflate the score
    penalty = readings.missing_sensor_ratio * _MISSING_SENSOR_MAX_PENALTY

    return min(100.0, base + penalty)
