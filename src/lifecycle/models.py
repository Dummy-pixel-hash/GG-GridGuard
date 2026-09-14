"""
Lifecycle domain models for GridGuard.

These types represent the *mutable* lifecycle state of a grid asset over its
operating life.  They are deliberately separate from:

  - ``RawAssetRecord`` / ``RawDegradationRecord`` — the snapshot types that
    the normalisation layer consumes.
  - ``AssetDegradationState`` — the normalised 0-100 scores the risk engine
    consumes.

The lifecycle engine operates on ``AssetLifecycleRecord`` objects and
produces updated records.  When scoring is needed, the caller extracts
the ``degradation`` and ``incidents`` fields and passes them to the
normalisation layer, exactly as before.

SYNTHETIC / DEMO DATA — no real utility data.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class LifecycleState(str, Enum):
    """
    Valid states an asset can be in over its operating life.

    Transitions
    -----------
    ACTIVE      ──fault──►  FAULTED
    FAULTED     ──repair──►  ACTIVE          (repair restores operation)
    ACTIVE      ──decommission──►  RETIRED    (end of life / replaced)
    FAULTED     ──decommission──►  RETIRED

    ACTIVE is the normal operating state.  FAULTED means the asset has
    experienced a fault and is awaiting repair or decommission.  RETIRED
    means the physical asset has been removed from service; its record is
    preserved read-only for lineage and incident learning.
    """
    ACTIVE     = "active"
    FAULTED    = "faulted"
    RETIRED    = "retired"


class FaultSeverity(str, Enum):
    """
    Severity of a fault event.

    Severity affects how much the fault contributes to cumulative degradation
    and how it is classified in historical records.

    MINOR     — momentary anomaly; logged but no outage; resolved by SCADA.
    MODERATE  — protective relay operated; brief outage; manual restoration.
    MAJOR     — significant equipment damage; extended outage; on-site repair.
    CRITICAL  — catastrophic failure; asset cannot be restored without
                major component replacement.
    """
    MINOR    = "minor"
    MODERATE = "moderate"
    MAJOR    = "major"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Event types (inputs to the engine functions)
# ---------------------------------------------------------------------------

@dataclass
class FaultEvent:
    """
    Describes a single fault occurrence on an asset.

    Attributes:
        severity:           Fault severity classification.
        days_ago:           How many days ago the fault occurred (≥ 0).
        weather_related:    True if the fault was caused or accelerated by
                            weather conditions.
        repeat_mode:        True if this fault mode is the same as the
                            previous fault (unresolved root cause).
        description:        Free-text description for audit trail / display.
        stress_increment:   Additional wear this fault adds to the asset's
                            insulation health (0–100 scale; 0 = no damage,
                            100 = total destruction).  Defaults are derived
                            from severity if not specified explicitly.
    """
    severity: FaultSeverity
    days_ago: int = 0
    weather_related: bool = False
    repeat_mode: bool = False
    description: str = ""
    stress_increment: Optional[float] = None   # 0–100; None = use default


# Default stress increments per severity level
_DEFAULT_STRESS: dict[FaultSeverity, float] = {
    FaultSeverity.MINOR:    2.0,
    FaultSeverity.MODERATE: 6.0,
    FaultSeverity.MAJOR:    14.0,
    FaultSeverity.CRITICAL: 28.0,
}


def _fault_stress(event: FaultEvent) -> float:
    """Return the stress increment for a fault event (clamped 0–100)."""
    raw = event.stress_increment
    if raw is None:
        raw = _DEFAULT_STRESS[event.severity]
    return max(0.0, min(100.0, raw))


@dataclass
class MaintenanceEvent:
    """
    Describes a maintenance or repair intervention.

    Used both for routine scheduled maintenance (``apply_maintenance``) and
    for targeted repairs after a fault (``apply_repair``).

    Attributes:
        days_ago:               Days ago the work was performed (≥ 0).
        overdue_days_resolved:  How many days of overdue maintenance this
                                work clears (0 = fully on schedule, so the
                                overdue counter resets to 0).
        insulation_health_improvement: Points by which insulation health is
                                improved (0–100 scale).  0 = inspection only.
                                None = leave insulation_health_pct unchanged.
        notes:                  Free-text notes.
        is_major_repair:        True if this is a major component repair
                                (e.g. winding replacement, oil reclamation).
                                Major repairs improve insulation more and
                                reset the repeat-fault flag.
    """
    days_ago: int = 0
    overdue_days_resolved: int = 0
    insulation_health_improvement: Optional[float] = None  # 0–100
    notes: str = ""
    is_major_repair: bool = False


@dataclass
class ReplacementEvent:
    """
    Describes a full physical asset replacement.

    On replacement:
    - The existing ``AssetLifecycleRecord`` is retired (state → RETIRED) and
      moved into a ``RetiredAssetRecord`` with its full history intact.
    - A new ``AssetLifecycleRecord`` is created with a fresh health/degradation
      state but linked to the predecessor via ``predecessor_asset_id``.

    Attributes:
        new_asset_id:           ID for the successor physical asset.
                                Must differ from the current asset_id.
        new_commissioned_year:  Year the replacement unit enters service.
        new_rated_lifespan_years: Rated lifespan of the replacement unit.
        reason:                 Free-text reason for replacement.
        rated_kva:              Rated capacity of the replacement (kVA).
                                None = inherit from predecessor.
        replacement_load_factor_avg: Starting average load factor for the
                                new asset.  Defaults to 0.5.
    """
    new_asset_id: str
    new_commissioned_year: int
    new_rated_lifespan_years: float = 40.0
    reason: str = ""
    rated_kva: Optional[float] = None
    replacement_load_factor_avg: float = 0.5


# ---------------------------------------------------------------------------
# Core lifecycle record
# ---------------------------------------------------------------------------

@dataclass
class AssetLifecycleRecord:
    """
    Full mutable lifecycle record for an active grid asset.

    This is the central type the lifecycle engine operates on.  It extends
    the idea behind ``RawAssetRecord`` with an explicit state machine and
    full event history, while keeping the fields the normalisation layer
    needs (``degradation``, ``incidents``) directly accessible.

    Attributes:
        asset_id:              Unique identifier of this physical asset.
        state:                 Current lifecycle state.
        age_years:             Years since commissioning or last replacement.
        rated_lifespan_years:  Manufacturer rated service life.
        rated_kva:             Rated capacity (kVA).

        insulation_health_pct: Measured insulation health, 0–100 % where
                               100 = new / perfect, 0 = failed.
                               None = not yet measured.
        cumulative_fault_events: Total fault events (not all outage-causing).
        maintenance_overdue_days: Days past the next scheduled maintenance.
        average_load_factor:   Average load fraction over operating life.

        failure_count_last_5yr:      Confirmed outage-causing failures in
                                     the last 5 years.
        failures_caused_by_weather:  Subset of above caused by weather.
        last_failure_days_ago:       Days since most recent outage-causing
                                     failure (None = never).
        repeat_fault_active:         True if the most recent fault repeated
                                     an unresolved mode.

        fault_history:         Ordered list of all fault events (oldest first).
        maintenance_history:   Ordered list of all maintenance/repair events.

        predecessor_asset_id:  If this asset replaced another, the ID of the
                               physical unit it succeeded.  None = original.
    """

    asset_id: str
    state: LifecycleState = LifecycleState.ACTIVE

    # Degradation / ageing
    age_years: float = 0.0
    rated_lifespan_years: float = 40.0
    rated_kva: float = 0.0
    insulation_health_pct: Optional[float] = None   # 0–100 (100 = healthy)
    cumulative_fault_events: int = 0
    maintenance_overdue_days: int = 0
    average_load_factor: float = 0.5

    # Incident summary (mirrors RawIncidentRecord for hand-off to normaliser)
    failure_count_last_5yr: int = 0
    failures_caused_by_weather: int = 0
    last_failure_days_ago: Optional[int] = None
    repeat_fault_active: bool = False

    # Full event histories (preserved through replacements in RetiredAssetRecord)
    fault_history: list[FaultEvent] = field(default_factory=list)
    maintenance_history: list[MaintenanceEvent] = field(default_factory=list)

    # Lineage
    predecessor_asset_id: Optional[str] = None

    # ----------------------------------------------------------------
    # Derived-field accessors (read-only helpers for callers)
    # ----------------------------------------------------------------

    @property
    def is_past_rated_lifespan(self) -> bool:
        """True if the asset has exceeded its manufacturer rated service life."""
        return self.age_years > self.rated_lifespan_years

    @property
    def remaining_life_years(self) -> float:
        """Estimated remaining service life (may be negative for overdue assets)."""
        return self.rated_lifespan_years - self.age_years

    def to_raw_degradation(self):
        """Return a ``RawDegradationRecord`` snapshot for the normaliser."""
        # Import here to avoid circular dependency at module level
        from data.raw_types import RawDegradationRecord  # noqa: PLC0415
        return RawDegradationRecord(
            age_years=self.age_years,
            cumulative_fault_events=self.cumulative_fault_events,
            maintenance_overdue_days=self.maintenance_overdue_days,
            insulation_health_pct=self.insulation_health_pct,
            average_load_factor=self.average_load_factor,
        )

    def to_raw_incidents(self):
        """Return a ``RawIncidentRecord`` snapshot for the normaliser."""
        from data.raw_types import RawIncidentRecord  # noqa: PLC0415
        return RawIncidentRecord(
            failure_count_last_5yr=self.failure_count_last_5yr,
            failures_caused_by_weather=self.failures_caused_by_weather,
            last_failure_days_ago=self.last_failure_days_ago,
            repeat_mode_flag=self.repeat_fault_active,
        )


# ---------------------------------------------------------------------------
# Retired asset record (immutable snapshot)
# ---------------------------------------------------------------------------

@dataclass
class RetiredAssetRecord:
    """
    Read-only snapshot of a replaced asset.  Preserved for incident learning
    and lineage tracing.

    Created by ``apply_replacement()``.  Contains the full fault and
    maintenance history of the physical unit that was removed from service.
    The successor asset links back to this record via its
    ``predecessor_asset_id``.

    Fields mirror ``AssetLifecycleRecord`` but the state is always RETIRED
    and the histories are copies (not shared references).
    """

    asset_id: str
    state: LifecycleState = LifecycleState.RETIRED

    age_at_retirement_years: float = 0.0
    rated_lifespan_years: float = 40.0
    rated_kva: float = 0.0

    insulation_health_pct_at_retirement: Optional[float] = None
    cumulative_fault_events: int = 0
    total_failure_count: int = 0
    failures_caused_by_weather: int = 0

    fault_history: list[FaultEvent] = field(default_factory=list)
    maintenance_history: list[MaintenanceEvent] = field(default_factory=list)

    retirement_reason: str = ""
    successor_asset_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Replacement result
# ---------------------------------------------------------------------------

@dataclass
class ReplacementResult:
    """
    Return value of ``apply_replacement()``.

    Attributes:
        successor:  The new ``AssetLifecycleRecord`` with a clean health state
                    and a link to the retired predecessor.
        retired:    The ``RetiredAssetRecord`` containing the full history of
                    the physical unit that was removed from service.
    """
    successor: AssetLifecycleRecord
    retired: RetiredAssetRecord
