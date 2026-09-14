"""
Risk calculator — combines the five component scores into one overall result.

Overall risk formula (weights sum to 1.0):
    overall = sensor_health     * 0.30
            + weather_risk      * 0.20
            + historical_failure * 0.15
            + asset_degradation  * 0.15
            + grid_impact        * 0.20

Classification:
    0–39   → Normal
    40–69  → Watch
    70–84  → High
    85–100 → Critical
"""

from __future__ import annotations

from .models import (
    RiskInputs,
    ComponentScores,
    RiskResult,
    RiskLevel,
)
from .scoring import (
    score_sensor_health,
    score_weather_risk,
    score_historical_failure,
    score_asset_degradation,
    score_grid_impact,
)

# ── Component weights ───────────────────────────────────────────────────────
_WEIGHTS: dict[str, float] = {
    "sensor_health":      0.30,
    "weather_risk":       0.20,
    "historical_failure": 0.15,
    "asset_degradation":  0.15,
    "grid_impact":        0.20,
}

assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "Weights must sum to 1.0"


def _classify(overall: float) -> RiskLevel:
    """Map a 0–100 score to the appropriate RiskLevel."""
    if overall >= 85.0:
        return RiskLevel.CRITICAL
    if overall >= 70.0:
        return RiskLevel.HIGH
    if overall >= 40.0:
        return RiskLevel.WATCH
    return RiskLevel.NORMAL


def _dominant_factor(components: ComponentScores) -> str:
    """
    Return the name of the component with the highest *weighted* contribution.

    This is the single biggest driver of the overall score, useful for
    operator briefings and AI explanation anchoring.
    """
    weighted = {
        "sensor_health":      components.sensor_health      * _WEIGHTS["sensor_health"],
        "weather_risk":       components.weather_risk        * _WEIGHTS["weather_risk"],
        "historical_failure": components.historical_failure  * _WEIGHTS["historical_failure"],
        "asset_degradation":  components.asset_degradation   * _WEIGHTS["asset_degradation"],
        "grid_impact":        components.grid_impact          * _WEIGHTS["grid_impact"],
    }
    return max(weighted, key=weighted.__getitem__)


def score_asset(inputs: RiskInputs) -> RiskResult:
    """
    Compute the full risk result for a single asset.

    This is the primary public entry point of the risk engine.

    Args:
        inputs: All required inputs for the asset being scored.

    Returns:
        RiskResult containing the overall score, risk level, per-component
        scores, and the name of the dominant contributing factor.
    """
    sensor      = score_sensor_health(inputs.sensors)
    weather     = score_weather_risk(inputs.weather)
    history     = score_historical_failure(inputs.history)
    degradation = score_asset_degradation(inputs.degradation)
    impact      = score_grid_impact(inputs.grid_impact)

    overall = (
        sensor      * _WEIGHTS["sensor_health"]
        + weather   * _WEIGHTS["weather_risk"]
        + history   * _WEIGHTS["historical_failure"]
        + degradation * _WEIGHTS["asset_degradation"]
        + impact    * _WEIGHTS["grid_impact"]
    )
    overall = round(min(100.0, max(0.0, overall)), 1)

    components = ComponentScores(
        sensor_health=round(sensor, 1),
        weather_risk=round(weather, 1),
        historical_failure=round(history, 1),
        asset_degradation=round(degradation, 1),
        grid_impact=round(impact, 1),
    )

    return RiskResult(
        asset_id=inputs.asset_id,
        overall_risk=overall,
        risk_level=_classify(overall),
        components=components,
        dominant_factor=_dominant_factor(components),
    )
