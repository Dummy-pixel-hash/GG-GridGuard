"""
Asset degradation scoring (weight: 15% of overall risk).

This score captures long-run wear and lifecycle position — separate from
instantaneous sensor readings.  A brand-new asset with perfect sensors still
accumulates degradation risk as it ages and sustains faults.

Scoring formula
---------------
Four sub-signals are combined:

1. Age ratio (0–35 points)
   ──────────────────────────
   age_years / rated_lifespan_years, capped at 1.0, scaled to 35 points.
   A 40-year-old transformer on a 40-year lifespan → 35 pts.
   Assets past their rated lifespan are capped at 35 pts (not unbounded).

       age_ratio = min(1.0, age_years / rated_lifespan_years)
       pts = age_ratio * 35

2. Accumulated fault events (0–20 points)
   ──────────────────────────────────────
   cumulative_fault_events is sub-linearly mapped:

       0 faults → 0 pts
       1–2      → 8 pts
       3–5      → 14 pts
       6–10     → 18 pts
       11+      → 20 pts  (capped)

3. Maintenance overdue (0–25 points)
   ───────────────────────────────
   maintenance_overdue_days drives a stepped contribution:

       ≤ 0 days (on schedule / early) → 0 pts
       1–30 days overdue              → 8 pts
       31–90 days overdue             → 16 pts
       91–180 days overdue            → 22 pts
       > 180 days overdue             → 25 pts

4. Load stress (0–20 points)
   ──────────────────────────
   Sustained operation above 80% of rated capacity accelerates insulation
   ageing.  The load_factor_avg drives a linear contribution above 0.5:

       load_factor_avg ≤ 0.5 → 0 pts
       load_factor_avg = 1.0 → 20 pts
       linear interpolation between 0.5 and 1.0

       pts = max(0, (load_factor_avg - 0.5) / 0.5) * 20

   If insulation_health_score is available it replaces the age_ratio sub-score
   (items 1 above) because it is a direct measurement of the same phenomenon.
   When insulation_health_score is provided:
       insulation_pts = insulation_health_score * 0.35   (same 35-point scale)

Total is capped at 100.
"""

from __future__ import annotations

from ..models import AssetDegradationState


def _age_points(state: AssetDegradationState) -> float:
    if state.insulation_health_score is not None:
        # Direct measurement supersedes age proxy
        return state.insulation_health_score * 0.35
    age_ratio = min(1.0, state.age_years / max(1.0, state.rated_lifespan_years))
    return age_ratio * 35.0


def _fault_event_points(count: int) -> float:
    if count == 0:
        return 0.0
    if count <= 2:
        return 8.0
    if count <= 5:
        return 14.0
    if count <= 10:
        return 18.0
    return 20.0


def _maintenance_points(overdue_days: int) -> float:
    if overdue_days <= 0:
        return 0.0
    if overdue_days <= 30:
        return 8.0
    if overdue_days <= 90:
        return 16.0
    if overdue_days <= 180:
        return 22.0
    return 25.0


def _load_stress_points(load_factor_avg: float) -> float:
    if load_factor_avg <= 0.5:
        return 0.0
    return ((load_factor_avg - 0.5) / 0.5) * 20.0


def score_asset_degradation(state: AssetDegradationState) -> float:
    """
    Return a 0–100 asset degradation risk score.

    Higher = more degraded / closer to end-of-life.

    Args:
        state: Long-run degradation and lifecycle state for the asset.

    Returns:
        Float in [0, 100].
    """
    age_pts = _age_points(state)
    fault_pts = _fault_event_points(state.cumulative_fault_events)
    maint_pts = _maintenance_points(state.maintenance_overdue_days)
    load_pts = _load_stress_points(state.load_factor_avg)

    total = age_pts + fault_pts + maint_pts + load_pts
    return min(100.0, total)
