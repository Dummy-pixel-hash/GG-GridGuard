"""
RetiredAssetRepository — CRUD for retired_assets, retired_fault_events,
and retired_maintenance_events tables.

Stores and retrieves ``RetiredAssetRecord`` objects including their full
fault and maintenance event histories, preserved for lineage tracing and
incident learning.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from lifecycle.models import (
    FaultSeverity,
    LifecycleState,
    RetiredAssetRecord,
)
from storage.repositories.lifecycle import (
    _insert_fault_event,
    _insert_maintenance_event,
    _load_fault_events,
    _load_maintenance_events,
)


class RetiredAssetRepository:
    """
    CRUD operations for ``retired_assets`` and its associated event tables.

    Parameters
    ----------
    conn:
        Open SQLite connection from ``storage.get_connection()``.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, record: RetiredAssetRecord) -> None:
        """
        Persist a retired asset record (scalar state + full event history).

        Uses ``INSERT OR REPLACE`` so re-inserting an already-retired asset
        updates all fields without raising an error.

        Parameters
        ----------
        record:
            The ``RetiredAssetRecord`` to persist.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO retired_assets (
                asset_id, state, age_at_retirement_years,
                rated_lifespan_years, rated_kva,
                insulation_health_pct_at_retirement,
                cumulative_fault_events, total_failure_count,
                failures_caused_by_weather, retirement_reason, successor_asset_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.asset_id,
                record.state.value,
                record.age_at_retirement_years,
                record.rated_lifespan_years,
                record.rated_kva,
                record.insulation_health_pct_at_retirement,
                record.cumulative_fault_events,
                record.total_failure_count,
                record.failures_caused_by_weather,
                record.retirement_reason,
                record.successor_asset_id,
            ),
        )
        # Replace event histories
        self._conn.execute(
            "DELETE FROM retired_fault_events WHERE retired_asset_id = ?",
            (record.asset_id,),
        )
        self._conn.execute(
            "DELETE FROM retired_maintenance_events WHERE retired_asset_id = ?",
            (record.asset_id,),
        )
        for order, event in enumerate(record.fault_history):
            _insert_fault_event(
                self._conn,
                "retired_fault_events",
                "retired_asset_id",
                record.asset_id,
                event,
                order,
            )
        for order, event in enumerate(record.maintenance_history):
            _insert_maintenance_event(
                self._conn,
                "retired_maintenance_events",
                "retired_asset_id",
                record.asset_id,
                event,
                order,
            )
        self._conn.commit()

    def delete(self, asset_id: str) -> None:
        """Delete a retired asset record and all its event history rows."""
        self._conn.execute(
            "DELETE FROM retired_fault_events WHERE retired_asset_id = ?",
            (asset_id,),
        )
        self._conn.execute(
            "DELETE FROM retired_maintenance_events WHERE retired_asset_id = ?",
            (asset_id,),
        )
        self._conn.execute(
            "DELETE FROM retired_assets WHERE asset_id = ?", (asset_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, asset_id: str) -> RetiredAssetRecord | None:
        """Return the ``RetiredAssetRecord`` for *asset_id*, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM retired_assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_retired(self._conn, row)

    def get_by_successor(self, successor_asset_id: str) -> RetiredAssetRecord | None:
        """
        Return the retired asset record whose successor is *successor_asset_id*.

        Useful for walking the lineage chain: given a live asset's ID, find
        the physical unit it replaced.

        Returns ``None`` if no predecessor exists.
        """
        row = self._conn.execute(
            "SELECT * FROM retired_assets WHERE successor_asset_id = ?",
            (successor_asset_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_retired(self._conn, row)

    def list_all(self) -> list[RetiredAssetRecord]:
        """Return all retired asset records, ordered by asset_id."""
        rows = self._conn.execute(
            "SELECT * FROM retired_assets ORDER BY asset_id"
        ).fetchall()
        return [_row_to_retired(self._conn, r) for r in rows]

    def exists(self, asset_id: str) -> bool:
        """Return ``True`` if a retired record exists for *asset_id*."""
        row = self._conn.execute(
            "SELECT 1 FROM retired_assets WHERE asset_id = ? LIMIT 1",
            (asset_id,),
        ).fetchone()
        return row is not None

    def count(self) -> int:
        """Return the total number of retired asset records."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM retired_assets"
        ).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_retired(conn: sqlite3.Connection, row: sqlite3.Row) -> RetiredAssetRecord:
    asset_id = row["asset_id"]
    fault_history = _load_fault_events(
        conn, "retired_fault_events", "retired_asset_id", asset_id
    )
    maintenance_history = _load_maintenance_events(
        conn, "retired_maintenance_events", "retired_asset_id", asset_id
    )
    return RetiredAssetRecord(
        asset_id=asset_id,
        state=LifecycleState(row["state"]),
        age_at_retirement_years=row["age_at_retirement_years"],
        rated_lifespan_years=row["rated_lifespan_years"],
        rated_kva=row["rated_kva"],
        insulation_health_pct_at_retirement=row["insulation_health_pct_at_retirement"],
        cumulative_fault_events=row["cumulative_fault_events"],
        total_failure_count=row["total_failure_count"],
        failures_caused_by_weather=row["failures_caused_by_weather"],
        fault_history=fault_history,
        maintenance_history=maintenance_history,
        retirement_reason=row["retirement_reason"],
        successor_asset_id=row["successor_asset_id"],
    )
