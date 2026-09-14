"""GridGuard lifecycle engine package.

Tracks per-asset lifecycle state through fault events, maintenance, repairs,
and full replacements.  Produces updated ``RawDegradationRecord`` and
``RawIncidentRecord`` values that the existing normalisation layer consumes
without modification.

Public API
----------
    apply_fault(record, event)         -> AssetLifecycleRecord
    apply_maintenance(record, event)   -> AssetLifecycleRecord
    apply_repair(record, event)        -> AssetLifecycleRecord
    apply_replacement(record, event)   -> ReplacementResult

    AssetLifecycleRecord  — active asset with full mutable lifecycle state
    RetiredAssetRecord    — immutable snapshot of a replaced asset
    ReplacementResult     — (successor, retired) pair from apply_replacement()
    LifecycleState        — enum of valid asset states
    FaultEvent            — input to apply_fault()
    MaintenanceEvent      — input to apply_maintenance() and apply_repair()
    ReplacementEvent      — input to apply_replacement()
    LifecycleError        — raised on invalid transitions
"""

from .models import (
    LifecycleState,
    FaultSeverity,
    FaultEvent,
    MaintenanceEvent,
    ReplacementEvent,
    AssetLifecycleRecord,
    RetiredAssetRecord,
    ReplacementResult,
)
from .engine import (
    apply_fault,
    apply_maintenance,
    apply_repair,
    apply_replacement,
    advance_age,
    LifecycleError,
)

__all__ = [
    "LifecycleState",
    "FaultSeverity",
    "FaultEvent",
    "MaintenanceEvent",
    "ReplacementEvent",
    "AssetLifecycleRecord",
    "RetiredAssetRecord",
    "ReplacementResult",
    "apply_fault",
    "apply_maintenance",
    "apply_repair",
    "apply_replacement",
    "advance_age",
    "LifecycleError",
]
