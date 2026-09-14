"""
JSON serialisation helpers for GridGuard storage.

Only the fields that genuinely need JSON encoding are handled here:
- ``critical_facility_names`` (list[str]) in grid_topology
- ``FaultEvent`` list  → rows in fault_events / retired_fault_events
- ``MaintenanceEvent`` list → rows in maintenance_events / retired_maintenance_events

FaultEvent and MaintenanceEvent lists are stored as individual table rows
(not JSON blobs) for queryability.  This module provides only the simple
list[str] JSON helpers used for critical_facility_names.
"""

from __future__ import annotations

import json
from typing import Any


def encode_str_list(values: list[str]) -> str:
    """Serialise a ``list[str]`` to a JSON string for SQLite TEXT storage."""
    return json.dumps(values)


def decode_str_list(raw: str | None) -> list[str]:
    """Deserialise a JSON string back to ``list[str]``.  Returns ``[]`` on None."""
    if raw is None:
        return []
    decoded: Any = json.loads(raw)
    if not isinstance(decoded, list):
        return []
    return [str(v) for v in decoded]
