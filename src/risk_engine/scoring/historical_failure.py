"""
Historical failure risk scoring (weight: 15% of overall risk).

This score answers: "Given this asset's track record, how likely is it to
fail again soon?"

Scoring formula
---------------
Five sub-signals are combined:

1. Failure frequency (0–40 points)
   ──────────────────────────────
   failure_count_last_5yr is mapped to a 0–40 point contribution:

       0 failures → 0 pts
       1 failure  → 15 pts
       2 failures → 28 pts
       3 failures → 38 pts
       4+ failures → 40 pts  (capped)

   The curve is sub-linear: the first failure is the biggest signal; each
   additional failure adds progressively less because the count is already
   known to be high.

2. Recency penalty (0–25 points)
   ──────────────────────────────
   A recent failure is a stronger predictor than an old one.
   last_failure_days_ago drives a decaying contribution:

       ≤ 30 days  → 25 pts
       ≤ 90 days  → 20 pts
       ≤ 180 days → 12 pts
       ≤ 365 days → 6 pts
       > 365 days → 0 pts
       None (never failed) → 0 pts

3. Repeat-failure flag (0–20 points)
   ────────────────────────────────
   If the most recent failure repeated an identical failure mode, the
   underlying cause is unresolved.  This adds a flat 20 points.

4. Weather-correlated failures (0–15 points)
   ──────────────────────────────────────────
   Proportion of prior failures that were weather-triggered:

       pts = (failures_caused_by_weather / failure_count_last_5yr) * 15

   If failure_count_last_5yr == 0, this contribution is 0.

5. MTBF signal (0–10 points)
   ─────────────────────────
   mean_time_between_failures_days captures how tightly failures are
   clustering.  A short MTBF is a strong predictor of the next failure.

       MTBF ≤ 90 days  → 10 pts  (failing roughly monthly or faster)
       MTBF ≤ 180 days → 7 pts
       MTBF ≤ 365 days → 4 pts
       MTBF > 365 days → 0 pts
       None (< 2 failures, no meaningful MTBF) → 0 pts

Total is capped at 100.
"""

from __future__ import annotations

from ..models import HistoricalFailureRecord

# --- Failure frequency lookup table (count → points) ---------------------
# Sub-linear: index = failure count (0–4+), value = contribution
_FREQUENCY_TABLE = [0, 15, 28, 38, 40]


def _frequency_points(count: int) -> float:
    idx = min(count, len(_FREQUENCY_TABLE) - 1)
    return float(_FREQUENCY_TABLE[idx])


# --- Recency penalty lookup -----------------------------------------------
def _recency_points(last_failure_days_ago: int | None) -> float:
    if last_failure_days_ago is None:
        return 0.0
    if last_failure_days_ago <= 30:
        return 25.0
    if last_failure_days_ago <= 90:
        return 20.0
    if last_failure_days_ago <= 180:
        return 12.0
    if last_failure_days_ago <= 365:
        return 6.0
    return 0.0


# --- MTBF signal ----------------------------------------------------------
def _mtbf_points(mtbf_days: float | None) -> float:
    """
    Return 0–10 points based on mean time between failures.

    Shorter MTBF = higher score (failures clustering more tightly).
    None is returned when there are fewer than 2 failures, which means
    MTBF is undefined; treated as infinite (0 points).
    """
    if mtbf_days is None or mtbf_days <= 0:
        return 0.0
    if mtbf_days <= 90:
        return 10.0
    if mtbf_days <= 180:
        return 7.0
    if mtbf_days <= 365:
        return 4.0
    return 0.0


def score_historical_failure(history: HistoricalFailureRecord) -> float:
    """
    Return a 0–100 historical failure risk score.

    Higher = more failure history / higher repeat-failure risk.

    Args:
        history: Aggregated incident record for the asset.

    Returns:
        Float in [0, 100].
    """
    freq_pts = _frequency_points(history.failure_count_last_5yr)
    recency_pts = _recency_points(history.last_failure_days_ago)
    repeat_pts = 20.0 if history.repeat_failure_flag else 0.0

    if history.failure_count_last_5yr > 0:
        weather_ratio = (
            history.failures_caused_by_weather / history.failure_count_last_5yr
        )
        weather_pts = weather_ratio * 15.0
    else:
        weather_pts = 0.0

    mtbf_pts = _mtbf_points(history.mean_time_between_failures_days)

    total = freq_pts + recency_pts + repeat_pts + weather_pts + mtbf_pts
    return min(100.0, total)
