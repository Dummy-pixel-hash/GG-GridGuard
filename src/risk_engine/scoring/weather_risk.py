"""
Weather risk scoring (weight: 20% of overall risk).

Weather is scored as the *combination* of concurrent stressors because
compound events (e.g. high wind during a heat wave) are disproportionately
damaging to already-degraded assets.

Scoring formula
---------------
Base score = weighted average of the three weather dimensions:

    wind/storm severity   45%
    temperature stress    35%
    precipitation         20%

Compound-event multiplier
-------------------------
When two or more dimensions independently score ≥ 50, the conditions are
"compound" (multiple stressors active simultaneously).  The base score is
boosted by a 1.15 multiplier to reflect this disproportionate load, then
capped at 100.

    compound = True if (count of dimensions ≥ 50) ≥ 2
    final = min(100, base * 1.15) if compound else base
"""

from __future__ import annotations

from ..models import WeatherConditions

_WIND_WEIGHT = 0.45
_TEMP_WEIGHT = 0.35
_PRECIP_WEIGHT = 0.20

# Threshold above which a dimension is considered "active"
_ACTIVE_THRESHOLD = 50.0

# Multiplier applied when two or more dimensions are concurrently active
_COMPOUND_MULTIPLIER = 1.15


def score_weather_risk(weather: WeatherConditions) -> float:
    """
    Return a 0–100 weather risk score.

    Higher = more severe / more compound weather exposure.

    Args:
        weather: Normalised weather condition scores for the asset location.

    Returns:
        Float in [0, 100].
    """
    base = (
        weather.wind_storm_score * _WIND_WEIGHT
        + weather.temperature_stress_score * _TEMP_WEIGHT
        + weather.precipitation_score * _PRECIP_WEIGHT
    )

    # Compound event check
    active_dimensions = sum(
        1 for v in (
            weather.wind_storm_score,
            weather.temperature_stress_score,
            weather.precipitation_score,
        )
        if v >= _ACTIVE_THRESHOLD
    )

    if active_dimensions >= 2:
        base = base * _COMPOUND_MULTIPLIER

    return min(100.0, base)
