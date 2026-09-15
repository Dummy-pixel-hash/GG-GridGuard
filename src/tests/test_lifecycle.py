"""
Unit tests for the GridGuard lifecycle engine.

Coverage
--------
  1.  AssetLifecycleRecord helpers (to_raw_degradation, to_raw_incidents,
      is_past_rated_lifespan, remaining_life_years)
  2.  apply_fault — state transitions, stress accumulation, 5-yr window,
      repeat-mode flag, weather-related counting, minor faults
  3.  apply_maintenance — valid path, overdue reduction, insulation improvement,
      invalid-state guards
  4.  apply_repair — fault-to-active restoration, major repair flag,
      insulation improvement, active-asset preventive repair
  5.  apply_replacement — successor clean state, retired record history,
      lineage link, invalid guards (retired asset, same ID)
  6.  advance_age — age increment, overdue accumulation, invalid inputs
  7.  Immutability — input records are never mutated by any engine function
  8.  Multi-event sequences — realistic chains of events
  9.  Integration — lifecycle → to_raw_*() → normalise() → score_asset()
  10. Determinism — same inputs always produce same outputs

All data is synthetic / invented for test purposes.
"""

from __future__ import annotations

import copy

import pytest

from lifecycle import (
    AssetLifecycleRecord,
    FaultEvent,
    FaultSeverity,
    LifecycleError,
    LifecycleState,
    MaintenanceEvent,
    ReplacementEvent,
    ReplacementResult,
    RetiredAssetRecord,
    advance_age,
    apply_fault,
    apply_maintenance,
    apply_repair,
    apply_replacement,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _active_asset(
    asset_id: str = "TX-TEST",
    age_years: float = 10.0,
    insulation_health_pct: float = 90.0,
    maintenance_overdue_days: int = 0,
    average_load_factor: float = 0.5,
) -> AssetLifecycleRecord:
    return AssetLifecycleRecord(
        asset_id=asset_id,
        state=LifecycleState.ACTIVE,
        age_years=age_years,
        rated_lifespan_years=40.0,
        rated_kva=25_000.0,
        insulation_health_pct=insulation_health_pct,
        cumulative_fault_events=0,
        maintenance_overdue_days=maintenance_overdue_days,
        average_load_factor=average_load_factor,
    )


def _minor_fault() -> FaultEvent:
    return FaultEvent(severity=FaultSeverity.MINOR, days_ago=5)


def _major_fault(*, days_ago: int = 10, weather: bool = False,
                 repeat: bool = False) -> FaultEvent:
    return FaultEvent(
        severity=FaultSeverity.MAJOR,
        days_ago=days_ago,
        weather_related=weather,
        repeat_mode=repeat,
    )


def _maintenance(*, resolved: int = 60, improvement: float = 5.0,
                 major: bool = False) -> MaintenanceEvent:
    return MaintenanceEvent(
        days_ago=0,
        overdue_days_resolved=resolved,
        insulation_health_improvement=improvement,
        is_major_repair=major,
    )


# ===========================================================================
# 1. AssetLifecycleRecord helpers
# ===========================================================================

class TestAssetLifecycleRecordHelpers:

    def test_not_past_lifespan_when_young(self):
        r = _active_asset(age_years=10.0)
        r.rated_lifespan_years = 40.0
        assert r.is_past_rated_lifespan is False

    def test_past_lifespan_when_old(self):
        r = _active_asset(age_years=41.0)
        r.rated_lifespan_years = 40.0
        assert r.is_past_rated_lifespan is True

    def test_exactly_at_lifespan_is_not_past(self):
        r = _active_asset(age_years=40.0)
        r.rated_lifespan_years = 40.0
        assert r.is_past_rated_lifespan is False

    def test_remaining_life_positive(self):
        r = _active_asset(age_years=10.0)
        r.rated_lifespan_years = 40.0
        assert r.remaining_life_years == pytest.approx(30.0)

    def test_remaining_life_negative_past_end(self):
        r = _active_asset(age_years=45.0)
        r.rated_lifespan_years = 40.0
        assert r.remaining_life_years == pytest.approx(-5.0)

    def test_to_raw_degradation_fields(self):
        r = _active_asset(age_years=15.0, insulation_health_pct=80.0,
                          maintenance_overdue_days=30)
        raw = r.to_raw_degradation()
        assert raw.age_years == 15.0
        assert raw.insulation_health_pct == 80.0
        assert raw.maintenance_overdue_days == 30
        assert raw.average_load_factor == r.average_load_factor

    def test_to_raw_incidents_fields(self):
        r = _active_asset()
        r.failure_count_last_5yr = 2
        r.failures_caused_by_weather = 1
        r.last_failure_days_ago = 90
        r.repeat_fault_active = True
        inc = r.to_raw_incidents()
        assert inc.failure_count_last_5yr == 2
        assert inc.failures_caused_by_weather == 1
        assert inc.last_failure_days_ago == 90
        assert inc.repeat_mode_flag is True


# ===========================================================================
# 2. apply_fault
# ===========================================================================

class TestApplyFault:

    def test_active_becomes_faulted(self):
        r = _active_asset()
        result = apply_fault(r, _major_fault())
        assert result.state == LifecycleState.FAULTED

    def test_faulted_stays_faulted(self):
        r = _active_asset()
        r1 = apply_fault(r, _major_fault())
        r2 = apply_fault(r1, _minor_fault())
        assert r2.state == LifecycleState.FAULTED

    def test_retired_raises(self):
        r = _active_asset()
        r.state = LifecycleState.RETIRED
        with pytest.raises(LifecycleError, match="retired"):
            apply_fault(r, _major_fault())

    def test_cumulative_fault_events_incremented(self):
        r = _active_asset()
        r1 = apply_fault(r, _minor_fault())
        r2 = apply_fault(r1, _minor_fault())
        assert r2.cumulative_fault_events == 2

    def test_major_fault_reduces_insulation(self):
        r = _active_asset(insulation_health_pct=80.0)
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=0))
        # Default MAJOR stress = 14.0; 80 - 14 = 66
        assert result.insulation_health_pct == pytest.approx(66.0)

    def test_minor_fault_reduces_insulation_less(self):
        r = _active_asset(insulation_health_pct=80.0)
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.MINOR, days_ago=0))
        # Default MINOR stress = 2.0; 80 - 2 = 78
        assert result.insulation_health_pct == pytest.approx(78.0)

    def test_critical_fault_reduces_insulation_most(self):
        r = _active_asset(insulation_health_pct=80.0)
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.CRITICAL, days_ago=0))
        # Default CRITICAL stress = 28.0; 80 - 28 = 52
        assert result.insulation_health_pct == pytest.approx(52.0)

    def test_custom_stress_increment_honoured(self):
        r = _active_asset(insulation_health_pct=60.0)
        event = FaultEvent(severity=FaultSeverity.MAJOR, days_ago=0, stress_increment=10.0)
        result = apply_fault(r, event)
        assert result.insulation_health_pct == pytest.approx(50.0)

    def test_insulation_clamped_at_zero(self):
        r = _active_asset(insulation_health_pct=5.0)
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.CRITICAL, days_ago=0,
                                           stress_increment=50.0))
        assert result.insulation_health_pct == pytest.approx(0.0)

    def test_none_insulation_initialised_on_first_fault(self):
        r = _active_asset()
        r.insulation_health_pct = None
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=0))
        # 100 - 14 = 86
        assert result.insulation_health_pct == pytest.approx(86.0)

    def test_repeat_mode_flag_set(self):
        r = _active_asset()
        result = apply_fault(r, _major_fault(repeat=True))
        assert result.repeat_fault_active is True

    def test_repeat_mode_false_by_default(self):
        r = _active_asset()
        result = apply_fault(r, _major_fault(repeat=False))
        assert result.repeat_fault_active is False

    def test_major_fault_counted_in_5yr_window(self):
        r = _active_asset()
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=100))
        assert result.failure_count_last_5yr == 1

    def test_minor_fault_not_counted_in_5yr_window(self):
        r = _active_asset()
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.MINOR, days_ago=10))
        assert result.failure_count_last_5yr == 0

    def test_fault_beyond_5yr_not_counted(self):
        r = _active_asset()
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=2000))
        assert result.failure_count_last_5yr == 0

    def test_weather_fault_counted_separately(self):
        r = _active_asset()
        result = apply_fault(r, FaultEvent(
            severity=FaultSeverity.MAJOR, days_ago=50, weather_related=True
        ))
        assert result.failures_caused_by_weather == 1

    def test_non_weather_fault_not_weather_counted(self):
        r = _active_asset()
        result = apply_fault(r, FaultEvent(
            severity=FaultSeverity.MAJOR, days_ago=50, weather_related=False
        ))
        assert result.failures_caused_by_weather == 0

    def test_last_failure_days_ago_updated(self):
        r = _active_asset()
        result = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=30))
        assert result.last_failure_days_ago == 30

    def test_most_recent_fault_wins_last_failure_days_ago(self):
        r = _active_asset()
        r1 = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=300))
        r2 = apply_fault(r1, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=45))
        assert r2.last_failure_days_ago == 45

    def test_fault_appended_to_history(self):
        r = _active_asset()
        result = apply_fault(r, _major_fault(days_ago=10))
        assert len(result.fault_history) == 1
        assert result.fault_history[0].severity == FaultSeverity.MAJOR

    def test_two_faults_both_in_history(self):
        r = _active_asset()
        r1 = apply_fault(r, _minor_fault())
        r2 = apply_fault(r1, _major_fault())
        assert len(r2.fault_history) == 2


# ===========================================================================
# 3. apply_maintenance
# ===========================================================================

class TestApplyMaintenance:

    def test_active_stays_active(self):
        r = _active_asset()
        result = apply_maintenance(r, _maintenance())
        assert result.state == LifecycleState.ACTIVE

    def test_overdue_days_reduced(self):
        r = _active_asset(maintenance_overdue_days=90)
        result = apply_maintenance(r, MaintenanceEvent(overdue_days_resolved=60))
        assert result.maintenance_overdue_days == 30

    def test_overdue_days_clamped_at_zero(self):
        r = _active_asset(maintenance_overdue_days=20)
        result = apply_maintenance(r, MaintenanceEvent(overdue_days_resolved=100))
        assert result.maintenance_overdue_days == 0

    def test_insulation_improved(self):
        r = _active_asset(insulation_health_pct=70.0)
        result = apply_maintenance(r, MaintenanceEvent(insulation_health_improvement=10.0))
        assert result.insulation_health_pct == pytest.approx(80.0)

    def test_insulation_clamped_at_100(self):
        r = _active_asset(insulation_health_pct=95.0)
        result = apply_maintenance(r, MaintenanceEvent(insulation_health_improvement=20.0))
        assert result.insulation_health_pct == pytest.approx(100.0)

    def test_no_insulation_specified_leaves_unchanged(self):
        r = _active_asset(insulation_health_pct=75.0)
        result = apply_maintenance(r, MaintenanceEvent(insulation_health_improvement=None))
        assert result.insulation_health_pct == pytest.approx(75.0)

    def test_maintenance_appended_to_history(self):
        r = _active_asset()
        result = apply_maintenance(r, _maintenance())
        assert len(result.maintenance_history) == 1

    def test_faulted_asset_raises(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        with pytest.raises(LifecycleError, match="faulted"):
            apply_maintenance(r, _maintenance())

    def test_retired_asset_raises(self):
        r = _active_asset()
        r.state = LifecycleState.RETIRED
        with pytest.raises(LifecycleError, match="retired"):
            apply_maintenance(r, _maintenance())


# ===========================================================================
# 4. apply_repair
# ===========================================================================

class TestApplyRepair:

    def test_faulted_becomes_active(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        result = apply_repair(r, _maintenance())
        assert result.state == LifecycleState.ACTIVE

    def test_active_stays_active(self):
        r = _active_asset()
        result = apply_repair(r, _maintenance())
        assert result.state == LifecycleState.ACTIVE

    def test_retired_raises(self):
        r = _active_asset()
        r.state = LifecycleState.RETIRED
        with pytest.raises(LifecycleError, match="retired"):
            apply_repair(r, _maintenance())

    def test_overdue_reduced_by_repair(self):
        r = _active_asset(maintenance_overdue_days=120)
        r.state = LifecycleState.FAULTED
        result = apply_repair(r, MaintenanceEvent(overdue_days_resolved=90))
        assert result.maintenance_overdue_days == 30

    def test_insulation_improved_by_repair(self):
        r = _active_asset(insulation_health_pct=50.0)
        r.state = LifecycleState.FAULTED
        result = apply_repair(r, MaintenanceEvent(insulation_health_improvement=15.0))
        assert result.insulation_health_pct == pytest.approx(65.0)

    def test_minor_repair_does_not_clear_repeat_flag(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        r.repeat_fault_active = True
        result = apply_repair(r, MaintenanceEvent(is_major_repair=False))
        assert result.repeat_fault_active is True

    def test_major_repair_clears_repeat_flag(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        r.repeat_fault_active = True
        result = apply_repair(r, MaintenanceEvent(is_major_repair=True))
        assert result.repeat_fault_active is False

    def test_repair_appended_to_history(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        result = apply_repair(r, _maintenance())
        assert len(result.maintenance_history) == 1

    def test_cumulative_fault_events_unchanged_by_repair(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        r.cumulative_fault_events = 3
        result = apply_repair(r, _maintenance())
        assert result.cumulative_fault_events == 3


# ===========================================================================
# 5. apply_replacement
# ===========================================================================

class TestApplyReplacement:

    def _replacement_event(self, new_id: str = "TX-NEW") -> ReplacementEvent:
        return ReplacementEvent(
            new_asset_id=new_id,
            new_commissioned_year=2024,
            new_rated_lifespan_years=40.0,
            reason="End of service life",
        )

    def test_returns_replacement_result(self):
        r = _active_asset()
        result = apply_replacement(r, self._replacement_event())
        assert isinstance(result, ReplacementResult)

    def test_successor_is_active(self):
        r = _active_asset()
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.state == LifecycleState.ACTIVE

    def test_retired_is_retired(self):
        r = _active_asset()
        result = apply_replacement(r, self._replacement_event())
        assert result.retired.state == LifecycleState.RETIRED

    def test_successor_age_is_zero(self):
        r = _active_asset(age_years=38.0)
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.age_years == pytest.approx(0.0)

    def test_successor_insulation_is_100(self):
        r = _active_asset(insulation_health_pct=15.0)
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.insulation_health_pct == pytest.approx(100.0)

    def test_successor_has_no_faults(self):
        r = _active_asset()
        r.cumulative_fault_events = 10
        r.failure_count_last_5yr = 3
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.cumulative_fault_events == 0
        assert result.successor.failure_count_last_5yr == 0
        assert result.successor.last_failure_days_ago is None

    def test_successor_repeat_fault_flag_is_false(self):
        r = _active_asset()
        r.repeat_fault_active = True
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.repeat_fault_active is False

    def test_successor_overdue_is_zero(self):
        r = _active_asset(maintenance_overdue_days=200)
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.maintenance_overdue_days == 0

    def test_successor_has_new_asset_id(self):
        r = _active_asset(asset_id="TX-OLD")
        result = apply_replacement(r, self._replacement_event(new_id="TX-NEW"))
        assert result.successor.asset_id == "TX-NEW"

    def test_successor_predecessor_link(self):
        r = _active_asset(asset_id="TX-OLD")
        result = apply_replacement(r, self._replacement_event(new_id="TX-NEW"))
        assert result.successor.predecessor_asset_id == "TX-OLD"

    def test_retired_preserves_full_fault_history(self):
        r = _active_asset()
        r = apply_fault(r, _major_fault(days_ago=200))
        r = apply_repair(r, _maintenance())
        r = apply_fault(r, _major_fault(days_ago=30))
        r = apply_repair(r, _maintenance())
        result = apply_replacement(r, self._replacement_event())
        assert len(result.retired.fault_history) == 2

    def test_retired_preserves_full_maintenance_history(self):
        r = _active_asset()
        r = apply_fault(r, _major_fault())
        r = apply_repair(r, _maintenance())
        r = apply_maintenance(r, _maintenance())
        result = apply_replacement(r, self._replacement_event())
        assert len(result.retired.maintenance_history) == 2

    def test_retired_asset_id_matches_original(self):
        r = _active_asset(asset_id="TX-OLD")
        result = apply_replacement(r, self._replacement_event())
        assert result.retired.asset_id == "TX-OLD"

    def test_retired_successor_link(self):
        r = _active_asset(asset_id="TX-OLD")
        result = apply_replacement(r, self._replacement_event(new_id="TX-NEW"))
        assert result.retired.successor_asset_id == "TX-NEW"

    def test_retired_age_matches_predecessor(self):
        r = _active_asset(age_years=38.0)
        result = apply_replacement(r, self._replacement_event())
        assert result.retired.age_at_retirement_years == pytest.approx(38.0)

    def test_faulted_asset_can_be_replaced(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.state == LifecycleState.ACTIVE

    def test_retired_asset_raises(self):
        r = _active_asset()
        r.state = LifecycleState.RETIRED
        with pytest.raises(LifecycleError, match="retired"):
            apply_replacement(r, self._replacement_event())

    def test_same_id_raises(self):
        r = _active_asset(asset_id="TX-001")
        with pytest.raises(LifecycleError, match="differ"):
            apply_replacement(r, ReplacementEvent(
                new_asset_id="TX-001", new_commissioned_year=2024
            ))

    def test_successor_inherits_rated_kva_by_default(self):
        r = _active_asset()
        r.rated_kva = 50_000.0
        result = apply_replacement(r, self._replacement_event())
        assert result.successor.rated_kva == pytest.approx(50_000.0)

    def test_successor_uses_override_rated_kva(self):
        r = _active_asset()
        r.rated_kva = 50_000.0
        event = ReplacementEvent(
            new_asset_id="TX-NEW", new_commissioned_year=2024, rated_kva=80_000.0
        )
        result = apply_replacement(r, event)
        assert result.successor.rated_kva == pytest.approx(80_000.0)

    def test_retired_history_is_independent_copy(self):
        """Mutating the original's history must not affect the retired copy."""
        r = _active_asset()
        r = apply_fault(r, _major_fault(days_ago=100))
        result = apply_replacement(r, self._replacement_event())
        # Add a post-retirement fault to the *retired* record's history directly
        # (should not be possible via the engine, but test the copy)
        result.retired.fault_history.append(_minor_fault())
        # The successor should have no fault history
        assert len(result.successor.fault_history) == 0


# ===========================================================================
# 6. advance_age
# ===========================================================================

class TestAdvanceAge:

    def test_age_incremented(self):
        r = _active_asset(age_years=10.0)
        result = advance_age(r, 1.0)
        assert result.age_years == pytest.approx(11.0)

    def test_overdue_not_changed_by_age_advance(self):
        # advance_age no longer touches maintenance_overdue_days; overdue is
        # managed exclusively by apply_maintenance / apply_repair events.
        r = _active_asset(maintenance_overdue_days=0)
        result = advance_age(r, 1.0)
        assert result.maintenance_overdue_days == 0

    def test_fractional_year(self):
        r = _active_asset(age_years=10.0)
        result = advance_age(r, 0.5)
        assert result.age_years == pytest.approx(10.5)
        # maintenance_overdue_days is NOT modified by advance_age
        assert result.maintenance_overdue_days == r.maintenance_overdue_days

    def test_existing_overdue_preserved_after_age_advance(self):
        # Pre-existing overdue days are carried over unchanged.
        r = _active_asset(maintenance_overdue_days=30)
        result = advance_age(r, 1.0)
        assert result.maintenance_overdue_days == 30  # unchanged

    def test_faulted_age_advances(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        result = advance_age(r, 1.0)
        assert result.state == LifecycleState.FAULTED
        assert result.age_years == pytest.approx(r.age_years + 1.0)

    def test_retired_raises(self):
        r = _active_asset()
        r.state = LifecycleState.RETIRED
        with pytest.raises(LifecycleError, match="retired"):
            advance_age(r, 1.0)

    def test_zero_years_raises(self):
        r = _active_asset()
        with pytest.raises(LifecycleError, match="years > 0"):
            advance_age(r, 0.0)

    def test_negative_years_raises(self):
        r = _active_asset()
        with pytest.raises(LifecycleError, match="years > 0"):
            advance_age(r, -1.0)

    def test_state_unchanged(self):
        r = _active_asset()
        result = advance_age(r, 2.0)
        assert result.state == LifecycleState.ACTIVE

    def test_fault_history_unchanged(self):
        r = _active_asset()
        r = apply_fault(r, _major_fault())
        result = advance_age(r, 1.0)
        assert len(result.fault_history) == 1


# ===========================================================================
# 7. Immutability — original records are never mutated
# ===========================================================================

class TestImmutability:

    def test_apply_fault_does_not_mutate_original(self):
        r = _active_asset()
        original_state = r.state
        original_faults = len(r.fault_history)
        original_insulation = r.insulation_health_pct
        apply_fault(r, _major_fault())
        assert r.state == original_state
        assert len(r.fault_history) == original_faults
        assert r.insulation_health_pct == original_insulation

    def test_apply_maintenance_does_not_mutate_original(self):
        r = _active_asset(maintenance_overdue_days=90)
        orig_overdue = r.maintenance_overdue_days
        apply_maintenance(r, _maintenance())
        assert r.maintenance_overdue_days == orig_overdue

    def test_apply_repair_does_not_mutate_original(self):
        r = _active_asset()
        r.state = LifecycleState.FAULTED
        apply_repair(r, _maintenance())
        assert r.state == LifecycleState.FAULTED

    def test_apply_replacement_does_not_mutate_original(self):
        r = _active_asset(asset_id="TX-OLD")
        orig_id = r.asset_id
        orig_faults = len(r.fault_history)
        apply_replacement(r, ReplacementEvent(
            new_asset_id="TX-NEW", new_commissioned_year=2024
        ))
        assert r.asset_id == orig_id
        assert len(r.fault_history) == orig_faults
        assert r.state == LifecycleState.ACTIVE

    def test_advance_age_does_not_mutate_original(self):
        r = _active_asset(age_years=10.0)
        advance_age(r, 5.0)
        assert r.age_years == pytest.approx(10.0)


# ===========================================================================
# 8. Multi-event sequences — realistic chains
# ===========================================================================

class TestEventSequences:

    def test_fault_repair_fault_repair_sequence(self):
        r = _active_asset()
        r = apply_fault(r, FaultEvent(severity=FaultSeverity.MODERATE, days_ago=400))
        assert r.state == LifecycleState.FAULTED
        r = apply_repair(r, MaintenanceEvent(insulation_health_improvement=5.0,
                                             overdue_days_resolved=30))
        assert r.state == LifecycleState.ACTIVE
        r = apply_fault(r, FaultEvent(severity=FaultSeverity.MODERATE, days_ago=30,
                                      repeat_mode=True))
        assert r.repeat_fault_active is True
        assert r.failure_count_last_5yr == 2
        assert r.last_failure_days_ago == 30

    def test_age_advance_then_fault_then_replacement(self):
        r = _active_asset(age_years=0.0)
        r = advance_age(r, 35.0)
        assert r.age_years == pytest.approx(35.0)
        r = apply_fault(r, FaultEvent(severity=FaultSeverity.CRITICAL, days_ago=10))
        assert r.insulation_health_pct is not None
        result = apply_replacement(
            r,
            ReplacementEvent(new_asset_id="TX-SUCCESSOR", new_commissioned_year=2024)
        )
        assert result.successor.age_years == 0.0
        assert result.successor.insulation_health_pct == 100.0
        assert result.retired.cumulative_fault_events == 1
        assert result.successor.predecessor_asset_id == r.asset_id

    def test_maintenance_resets_overdue_then_overdue_managed_explicitly(self):
        # advance_age no longer accrues overdue; maintenance interval tracking
        # is the caller's responsibility.  This test verifies that:
        #   1. apply_maintenance correctly reduces the overdue counter.
        #   2. advance_age does NOT re-introduce overdue days.
        r = _active_asset(maintenance_overdue_days=730)
        r = apply_maintenance(r, MaintenanceEvent(overdue_days_resolved=730))
        assert r.maintenance_overdue_days == 0
        r = advance_age(r, 1.0)
        assert r.maintenance_overdue_days == 0  # advance_age does not add overdue

    def test_multiple_faults_5yr_window_accurate(self):
        r = _active_asset()
        # 3 failures: 2 inside window, 1 outside
        r = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=100))
        r = apply_repair(r, _maintenance())
        r = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=200))
        r = apply_repair(r, _maintenance())
        r = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=2000))
        r = apply_repair(r, _maintenance())
        assert r.failure_count_last_5yr == 2   # only 100 and 200 days ago qualify

    def test_major_repair_clears_repeat_flag_in_sequence(self):
        r = _active_asset()
        r = apply_fault(r, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=50,
                                      repeat_mode=True))
        assert r.repeat_fault_active is True
        r = apply_repair(r, MaintenanceEvent(is_major_repair=True,
                                             insulation_health_improvement=10.0))
        assert r.repeat_fault_active is False

    def test_insulation_degradation_across_multiple_faults(self):
        r = _active_asset(insulation_health_pct=100.0)
        for _ in range(3):
            r = apply_fault(r, FaultEvent(severity=FaultSeverity.MODERATE, days_ago=10))
            r = apply_repair(r, _maintenance(improvement=2.0))
        # 3 × (−6 + 2) = −12 net; 100 − 12 = 88
        assert r.insulation_health_pct == pytest.approx(88.0)


# ===========================================================================
# 9. Integration — lifecycle → normalise → score_asset
# ===========================================================================

class TestLifecycleIntegration:

    def _base_record(self) -> AssetLifecycleRecord:
        return AssetLifecycleRecord(
            asset_id="TX-INTEG",
            state=LifecycleState.ACTIVE,
            age_years=20.0,
            rated_lifespan_years=40.0,
            rated_kva=25_000.0,
            insulation_health_pct=80.0,
            cumulative_fault_events=0,
            maintenance_overdue_days=0,
            average_load_factor=0.5,
        )

    def _score_from_lifecycle(self, r: AssetLifecycleRecord) -> float:
        """Full pipeline: lifecycle → raw types → normalise → score_asset."""
        from data.raw_types import (
            RawAssetRecord, AssetMetadata, AssetLocation,
            RawSensorTelemetry, RawWeatherObservation, RawGridTopology,
        )
        from normalisation.normaliser import normalise
        from risk_engine import score_asset

        meta = AssetMetadata(
            asset_id=r.asset_id, asset_type="transformer",
            rated_kva=r.rated_kva, rated_voltage_kv=33.0,
            rated_lifespan_years=r.rated_lifespan_years,
            commissioned_year=2000,
            location=AssetLocation(latitude=51.5, longitude=-0.1),
        )
        record = RawAssetRecord(
            metadata=meta,
            telemetry=RawSensorTelemetry(
                top_oil_temp_c=60.0, winding_hot_spot_c=80.0,
                vibration_mm_s=1.0, oil_dielectric_kv=65.0,
                partial_discharge_pc=150.0,
            ),
            weather=RawWeatherObservation(
                max_temp_c=20.0, min_temp_c=10.0,
                precipitation_mm=0.0, wind_speed_max_kmh=0.0,
                storm_warning_level=0,
            ),
            incidents=r.to_raw_incidents(),
            degradation=r.to_raw_degradation(),
            topology=RawGridTopology(customers_served=5000, peak_load_mw=5.0),
        )
        return score_asset(normalise(record)).overall_risk

    def test_fresh_asset_scores_lower_than_degraded(self):
        fresh = self._base_record()
        degraded = self._base_record()
        # Degrade by applying several faults without repair
        degraded = apply_fault(degraded, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=50))
        degraded = apply_fault(degraded, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=200,
                                                    weather_related=True))
        degraded.state = LifecycleState.FAULTED
        degraded = apply_repair(degraded, _maintenance(improvement=0.0))
        degraded = advance_age(degraded, 15.0)

        fresh_score = self._score_from_lifecycle(fresh)
        degraded_score = self._score_from_lifecycle(degraded)
        assert degraded_score > fresh_score, (
            f"Degraded asset ({degraded_score}) should score higher than fresh ({fresh_score})"
        )

    def test_replacement_successor_scores_lower_than_predecessor(self):
        """After replacement the successor should have a much lower overall risk."""
        old = self._base_record()
        old = advance_age(old, 30.0)
        old = apply_fault(old, FaultEvent(severity=FaultSeverity.MAJOR, days_ago=60))
        old = apply_repair(old, _maintenance(improvement=5.0))

        result = apply_replacement(
            old,
            ReplacementEvent(new_asset_id="TX-SUCCESSOR", new_commissioned_year=2024)
        )
        successor = result.successor

        old_score = self._score_from_lifecycle(old)
        successor_score = self._score_from_lifecycle(successor)
        assert successor_score < old_score, (
            f"Successor ({successor_score}) should score below predecessor ({old_score})"
        )

    def test_repair_reduces_risk_relative_to_unrepaired(self):
        faulted = self._base_record()
        faulted = apply_fault(faulted, FaultEvent(
            severity=FaultSeverity.MAJOR, days_ago=30, weather_related=True
        ))

        repaired = apply_repair(
            faulted,
            MaintenanceEvent(
                is_major_repair=True,
                insulation_health_improvement=20.0,
                overdue_days_resolved=100,
            )
        )

        faulted_score = self._score_from_lifecycle(faulted)
        repaired_score = self._score_from_lifecycle(repaired)
        assert repaired_score < faulted_score


# ===========================================================================
# 10. Determinism
# ===========================================================================

class TestDeterminism:

    def test_apply_fault_is_deterministic(self):
        r = _active_asset()
        event = _major_fault(days_ago=90)
        r1 = apply_fault(r, event)
        r2 = apply_fault(r, event)
        assert r1.insulation_health_pct == r2.insulation_health_pct
        assert r1.failure_count_last_5yr == r2.failure_count_last_5yr
        assert r1.state == r2.state

    def test_replacement_is_deterministic(self):
        r = _active_asset()
        event = ReplacementEvent(new_asset_id="TX-NEW", new_commissioned_year=2024)
        res1 = apply_replacement(r, event)
        res2 = apply_replacement(r, event)
        assert res1.successor.asset_id == res2.successor.asset_id
        assert res1.successor.age_years == res2.successor.age_years
        assert res1.retired.asset_id == res2.retired.asset_id

    def test_advance_age_is_deterministic(self):
        r = _active_asset(age_years=10.0)
        r1 = advance_age(r, 5.0)
        r2 = advance_age(r, 5.0)
        assert r1.age_years == r2.age_years
        assert r1.maintenance_overdue_days == r2.maintenance_overdue_days
