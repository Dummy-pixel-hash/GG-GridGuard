"""
Grid impact scoring (weight: 20% of overall risk).

This score captures the *consequence* of failure — independent of
probability.  A healthy asset that feeds a hospital still demands attention
if it fails; a degraded asset on a redundant spur is lower priority.

Scoring formula
---------------
Four sub-signals are combined:

1. Customer exposure (0–30 points)
   ──────────────────────────────
   Customers served, scaled against a reference value of 50 000 customers
   (a typical large urban distribution feeder):

       pts = min(1.0, customers_served / 50_000) * 30

2. Critical facility weight (0–35 points)
   ──────────────────────────────────────
   Each critical facility (hospital, water plant, emergency services)
   downstream adds 12 points, capped at 35:

       pts = min(35, critical_facility_count * 12)

3. Downstream cascade exposure (0–20 points)
   ──────────────────────────────────────────
   Number of downstream assets that lose supply:
   Scaled against a reference of 10 downstream assets:

       pts = min(1.0, downstream_asset_count / 10) * 20

4. Load magnitude (0–15 points)
   ─────────────────────────────
   Peak load in MW, scaled against 50 MW reference:

       pts = min(1.0, peak_load_mw / 50.0) * 15

Redundancy discount
-------------------
If has_redundant_path is True, automatic transfer limits customer impact.
The total (before capping) is multiplied by 0.60, reducing the impact score
by 40%.  Critical-facility points are not discounted because even N-1
switching introduces brief interruptions that are unacceptable for hospitals.

    non_critical_pts = customer_pts + cascade_pts + load_pts
    discounted = non_critical_pts * 0.60 if has_redundant_path else non_critical_pts
    total = discounted + critical_pts

Total is capped at 100.
"""

from __future__ import annotations

from ..models import GridImpactFactors

_CUSTOMER_REFERENCE = 50_000
_DOWNSTREAM_REFERENCE = 10
_LOAD_REFERENCE_MW = 50.0
_CRITICAL_FACILITY_PTS_EACH = 12.0
_CRITICAL_FACILITY_MAX = 35.0

_REDUNDANCY_DISCOUNT = 0.60  # fraction of non-critical points retained when redundant


def score_grid_impact(factors: GridImpactFactors) -> float:
    """
    Return a 0–100 grid impact (consequence-of-failure) score.

    Higher = more customers / critical facilities impacted if this asset fails.

    Args:
        factors: Consequence-of-failure factors for the asset.

    Returns:
        Float in [0, 100].
    """
    customer_pts = min(1.0, factors.customers_served / _CUSTOMER_REFERENCE) * 30.0

    critical_pts = min(
        _CRITICAL_FACILITY_MAX,
        factors.critical_facility_count * _CRITICAL_FACILITY_PTS_EACH,
    )

    cascade_pts = (
        min(1.0, factors.downstream_asset_count / _DOWNSTREAM_REFERENCE) * 20.0
    )

    load_pts = min(1.0, factors.peak_load_mw / _LOAD_REFERENCE_MW) * 15.0

    non_critical = customer_pts + cascade_pts + load_pts

    if factors.has_redundant_path:
        non_critical *= _REDUNDANCY_DISCOUNT

    total = non_critical + critical_pts
    return min(100.0, total)
