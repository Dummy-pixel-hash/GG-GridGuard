"""
GridGuard lifecycle engine — pure transition functions.

Each function takes an ``AssetLifecycleRecord`` (and an event) and returns a
**new** ``AssetLifecycleRecord`` with updated state.  The input record is
never mutated.  This makes the engine deterministic, side-effect-free, and
straightforward to test.

Public API
----------
    apply_fault(record, event)         -> AssetLifecycleRecord
    apply_maintenance(record, event)   -> AssetLifecycleRecord
    apply_repair(record, event)        -> AssetLifecycleRecord
    apply_replacement(record, event)   -> ReplacementResult
    advance_age(record, years)         -> AssetLifecycleRecord
    LifecycleError                     — invalid-transition exception

State transition rules
----------------------
apply_fault:
    ACTIVE  → FAULTED   (always allowed on active assets)
    FAULTED → FAULTED   (additional fault on an already-faulted asset; allowed)
    RETIRED → LifecycleError

apply_maintenance:
    ACTIVE → ACTIVE     (scheduled maintenance; asset stays active)
    FAULTED → LifecycleError  (must repair or replace a faulted asset first)
    RETIRED → LifecycleError

apply_repair:
    FAULTED → ACTIVE    (repair restores operation; identity and history kept)
    ACTIVE  → ACTIVE    (preventive/proactive repair on a non-faulted asset)
    RETIRED → LifecycleError

apply_replacement:
    ACTIVE  → RETIRED + new ACTIVE  (retirement + successor with clean state)
    FAULTED → RETIRED + new ACTIVE  (decommission after catastrophic fault)
    RETIRED → LifecycleError        (cannot replace an already-retired asset)

advance_age:
    ACTIVE  → ACTIVE    (time passing; age_years incremented, overdue grows)
    FAULTED → FAULTED   (time passes while asset awaits repair)
    RETIRED → LifecycleError

Degradation model details
-------------------------
Fault stress
    Each fault event adds ``stress_increment`` points to the asset's
    accumulated degradation.  Stress is modelled as a *reduction* of
    insulation health:

        new_insulation_health_pct = max(0, old - stress_increment)

    If insulation_health_pct is None (not yet measured), the first fault that
    specifies a non-zero stress_increment will initialise it to
    (100 - stress_increment), representing a healthy asset that just took
    damage.

Repair health improvement
    ``MaintenanceEvent.insulation_health_improvement`` is added to
    ``insulation_health_pct``, clamped to 100.  A major repair also resets
    ``repeat_fault_active``.

Maintenance overdue counter
    ``maintenance_overdue_days`` reflects how many days past the scheduled
    maintenance date the asset currently is.  It is *not* automatically
    incremented by ``advance_age`` — that would unconditionally mark every
    asset as overdue the instant time advances, regardless of whether a
    maintenance cycle has actually elapsed.  Callers that need to model
    time-based overdue accrual should compute the days past the next
    scheduled date and set ``maintenance_overdue_days`` explicitly before
    calling the risk engine.  ``apply_maintenance`` and ``apply_repair``
    reduce it by ``event.overdue_days_resolved``, clamped to 0.

5-year failure window
    ``failure_count_last_5yr`` counts confirmed outage-causing failures
    (``FaultSeverity.MODERATE | MAJOR | CRITICAL``) whose ``days_ago`` is
    ≤ 1825 (5 × 365).  MINOR faults increment cumulative_fault_events but
    do not count as failures in the 5-year window.
"""

from __future__ import annotations

import copy
from typing import Optional

from lifecycle.models import (
    AssetLifecycleRecord,
    FaultEvent,
    FaultSeverity,
    MaintenanceEvent,
    ReplacementEvent,
    ReplacementResult,
    RetiredAssetRecord,
    LifecycleState,
    _fault_stress,
)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class LifecycleError(ValueError):
    """Raised when a lifecycle transition is invalid for the current state."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Fault severities that count as a confirmed failure in the 5-year window
_FAILURE_SEVERITIES = {FaultSeverity.MODERATE, FaultSeverity.MAJOR, FaultSeverity.CRITICAL}

# 5-year window in days
_FIVE_YEAR_DAYS = 5 * 365


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _recompute_5yr_window(record: AssetLifecycleRecord) -> tuple[int, int, Optional[int]]:
    """
    Recompute the 5-year failure summary from the full fault history.

    Returns (failure_count_last_5yr, failures_caused_by_weather, last_failure_days_ago).

    This keeps the summary fields consistent whenever a fault is added.
    We walk the fault history rather than incrementally adjusting counts so
    that the result is always correct regardless of event ordering.
    """
    count = 0
    weather_count = 0
    min_days: Optional[int] = None

    for event in record.fault_history:
        is_failure = event.severity in _FAILURE_SEVERITIES
        in_window  = event.days_ago <= _FIVE_YEAR_DAYS

        if is_failure and in_window:
            count += 1
            if event.weather_related:
                weather_count += 1
            if min_days is None or event.days_ago < min_days:
                min_days = event.days_ago

    return count, weather_count, min_days


# ---------------------------------------------------------------------------
# Public transition functions
# ---------------------------------------------------------------------------

def apply_fault(
    record: AssetLifecycleRecord,
    event: FaultEvent,
) -> AssetLifecycleRecord:
    """
    Apply a fault event to an asset.

    Valid in states: ACTIVE, FAULTED.
    New state: FAULTED.

    Updates:
    - state → FAULTED
    - cumulative_fault_events += 1
    - insulation_health_pct reduced by fault stress
    - failure_count_last_5yr / failures_caused_by_weather / last_failure_days_ago
      recomputed from the full fault history
    - repeat_fault_active set to event.repeat_mode

    Args:
        record: Current asset lifecycle record (not mutated).
        event:  The fault that occurred.

    Returns:
        New ``AssetLifecycleRecord`` with updated state.

    Raises:
        ``LifecycleError`` if the asset is RETIRED.
    """
    if record.state == LifecycleState.RETIRED:
        raise LifecycleError(
            f"Cannot apply fault to retired asset '{record.asset_id}'"
        )

    r = copy.deepcopy(record)

    # Append to history
    r.fault_history.append(copy.deepcopy(event))

    # State transition
    r.state = LifecycleState.FAULTED

    # Cumulative fault events (all severities)
    r.cumulative_fault_events += 1

    # Insulation stress
    stress = _fault_stress(event)
    if stress > 0:
        current = r.insulation_health_pct if r.insulation_health_pct is not None else 100.0
        r.insulation_health_pct = _clamp(current - stress)

    # Repeat-fault flag
    r.repeat_fault_active = event.repeat_mode

    # Recompute 5-year summary from full history
    r.failure_count_last_5yr, r.failures_caused_by_weather, r.last_failure_days_ago = (
        _recompute_5yr_window(r)
    )

    return r


def apply_maintenance(
    record: AssetLifecycleRecord,
    event: MaintenanceEvent,
) -> AssetLifecycleRecord:
    """
    Apply a scheduled maintenance event.

    Valid in states: ACTIVE only.
    New state: ACTIVE.

    Updates:
    - maintenance_overdue_days reduced by event.overdue_days_resolved (≥ 0)
    - insulation_health_pct improved by event.insulation_health_improvement
      (if specified)
    - maintenance_history appended

    Does NOT change state (scheduled maintenance does not restore a faulted asset).
    Use ``apply_repair`` for post-fault restoration.

    Raises:
        ``LifecycleError`` if asset is FAULTED or RETIRED.
    """
    if record.state == LifecycleState.FAULTED:
        raise LifecycleError(
            f"Cannot apply routine maintenance to faulted asset '{record.asset_id}'. "
            "Use apply_repair() to restore a faulted asset."
        )
    if record.state == LifecycleState.RETIRED:
        raise LifecycleError(
            f"Cannot apply maintenance to retired asset '{record.asset_id}'"
        )

    r = copy.deepcopy(record)
    r.maintenance_history.append(copy.deepcopy(event))

    # Reduce overdue counter
    resolved = max(0, event.overdue_days_resolved)
    r.maintenance_overdue_days = max(0, r.maintenance_overdue_days - resolved)

    # Improve insulation if specified
    if event.insulation_health_improvement is not None:
        current = r.insulation_health_pct if r.insulation_health_pct is not None else 0.0
        r.insulation_health_pct = _clamp(current + event.insulation_health_improvement)

    return r


def apply_repair(
    record: AssetLifecycleRecord,
    event: MaintenanceEvent,
) -> AssetLifecycleRecord:
    """
    Apply a repair event, restoring a faulted asset to active service.

    Valid in states: FAULTED (primary use), ACTIVE (preventive repair).
    New state: ACTIVE.

    Updates:
    - state → ACTIVE
    - maintenance_overdue_days reduced by event.overdue_days_resolved
    - insulation_health_pct improved by event.insulation_health_improvement
    - repeat_fault_active reset to False if event.is_major_repair is True
    - maintenance_history appended

    Raises:
        ``LifecycleError`` if asset is RETIRED.
    """
    if record.state == LifecycleState.RETIRED:
        raise LifecycleError(
            f"Cannot repair retired asset '{record.asset_id}'"
        )

    r = copy.deepcopy(record)
    r.maintenance_history.append(copy.deepcopy(event))

    # Restore to active
    r.state = LifecycleState.ACTIVE

    # Reduce overdue counter
    resolved = max(0, event.overdue_days_resolved)
    r.maintenance_overdue_days = max(0, r.maintenance_overdue_days - resolved)

    # Improve insulation if specified
    if event.insulation_health_improvement is not None:
        current = r.insulation_health_pct if r.insulation_health_pct is not None else 0.0
        r.insulation_health_pct = _clamp(current + event.insulation_health_improvement)

    # Major repair resolves the repeat-fault flag (root cause addressed)
    if event.is_major_repair:
        r.repeat_fault_active = False

    return r


def apply_replacement(
    record: AssetLifecycleRecord,
    event: ReplacementEvent,
) -> ReplacementResult:
    """
    Retire the current physical asset and create a successor with a clean
    health/degradation state.

    Valid in states: ACTIVE, FAULTED.

    The retired record preserves the FULL fault and maintenance history of
    the physical unit removed from service.  The successor record starts
    with age 0, insulation 100%, no fault events, and no overdue maintenance,
    but carries the predecessor_asset_id link for lineage tracing.

    The successor INHERITS:
    - rated_kva from the predecessor (unless overridden in the event)
    - grid topology fields are NOT part of the lifecycle record; the caller
      is responsible for updating the network model separately.

    Raises:
        ``LifecycleError`` if asset is RETIRED or if new_asset_id == asset_id.
    """
    if record.state == LifecycleState.RETIRED:
        raise LifecycleError(
            f"Cannot replace already-retired asset '{record.asset_id}'"
        )
    if event.new_asset_id == record.asset_id:
        raise LifecycleError(
            f"Successor asset_id must differ from the current asset_id "
            f"(both are '{record.asset_id}')"
        )

    # --- Build the retired record ---
    retired = RetiredAssetRecord(
        asset_id=record.asset_id,
        state=LifecycleState.RETIRED,
        age_at_retirement_years=record.age_years,
        rated_lifespan_years=record.rated_lifespan_years,
        rated_kva=record.rated_kva,
        insulation_health_pct_at_retirement=record.insulation_health_pct,
        cumulative_fault_events=record.cumulative_fault_events,
        total_failure_count=record.failure_count_last_5yr,
        failures_caused_by_weather=record.failures_caused_by_weather,
        fault_history=copy.deepcopy(record.fault_history),
        maintenance_history=copy.deepcopy(record.maintenance_history),
        retirement_reason=event.reason,
        successor_asset_id=event.new_asset_id,
    )

    # --- Build the successor record (clean health state) ---
    successor = AssetLifecycleRecord(
        asset_id=event.new_asset_id,
        state=LifecycleState.ACTIVE,
        age_years=0.0,
        rated_lifespan_years=event.new_rated_lifespan_years,
        rated_kva=event.rated_kva if event.rated_kva is not None else record.rated_kva,
        insulation_health_pct=100.0,   # brand-new insulation
        cumulative_fault_events=0,
        maintenance_overdue_days=0,
        average_load_factor=event.replacement_load_factor_avg,
        failure_count_last_5yr=0,
        failures_caused_by_weather=0,
        last_failure_days_ago=None,
        repeat_fault_active=False,
        fault_history=[],
        maintenance_history=[],
        predecessor_asset_id=record.asset_id,
    )

    return ReplacementResult(successor=successor, retired=retired)


def advance_age(
    record: AssetLifecycleRecord,
    years: float,
) -> AssetLifecycleRecord:
    """
    Advance the asset's age by ``years``.

    Valid in states: ACTIVE, FAULTED.

    Updates:
    - age_years += years

    Does NOT modify ``maintenance_overdue_days``.  Overdue accrual depends on
    the asset's maintenance schedule (interval and last-maintenance date), which
    the lifecycle engine does not track.  Callers that need to model overdue
    accrual should compute the elapsed days past the next scheduled date and
    update ``maintenance_overdue_days`` via ``apply_maintenance`` /
    ``apply_repair``, or set it directly before calling the risk engine.

    Does not change state or modify fault/maintenance history.

    Args:
        record: Current asset lifecycle record (not mutated).
        years:  Number of years to advance (must be > 0).

    Returns:
        New ``AssetLifecycleRecord`` with updated age.

    Raises:
        ``LifecycleError`` if years ≤ 0 or asset is RETIRED.
    """
    if record.state == LifecycleState.RETIRED:
        raise LifecycleError(
            f"Cannot advance age of retired asset '{record.asset_id}'"
        )
    if years <= 0:
        raise LifecycleError(
            f"advance_age requires years > 0, got {years}"
        )

    r = copy.deepcopy(record)
    r.age_years += years
    return r
