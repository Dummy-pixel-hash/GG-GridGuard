"""
Sensor health scoring (weight: 30% of overall risk).

A sensor health score of 0 means every sensor is nominal; 100 means every
sensor is at or beyond its alarm threshold (or fully offline).

Scoring formula
---------------
Base score = weighted average of the four sensor dimension scores:

    temperature       40%
    partial_discharge 30%
    oil_quality       20%
    vibration         10%

The weighting reflects field failure statistics: thermal runaway and
partial discharge are the primary precursors to transformer failure; oil
degradation is a lagging indicator of internal distress; vibration matters
more for rotating plant and is weighted lower here.

Missing-sensor penalty
----------------------
When sensors are offline the score is *unknown*, not *safe*.  Each missing
sensor fraction (0–1) adds up to 20 points to the base score, capped at 100.

    penalty = missing_sensor_ratio * 20

This keeps the scoring conservative: an asset with all sensors offline gets
+20 on top of whatever the available sensors report (typically 0 when nothing
is reporting), yielding a minimum score of 20 for a fully blind asset.
"""

from __future__ import annotations

from ..models import SensorReadings

# Weights for the four sensor dimensions
_TEMPERATURE_WEIGHT = 0.40
_PD_WEIGHT = 0.30
_OIL_WEIGHT = 0.20
_VIBRATION_WEIGHT = 0.10

# Maximum additive penalty for missing sensors (all 4 offline → +20)
_MISSING_SENSOR_MAX_PENALTY = 20.0


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
    )

    # Conservative: missing sensors inflate the score
    penalty = readings.missing_sensor_ratio * _MISSING_SENSOR_MAX_PENALTY

    return min(100.0, base + penalty)
