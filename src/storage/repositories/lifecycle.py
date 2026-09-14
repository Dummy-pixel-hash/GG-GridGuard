"""
LifecycleRepository — CRUD for lifecycle_records, fault_events, and
maintenance_events tables.

Stores and retrieves ``AssetLifecycleRecord`` objects.  The scalar fields go
into ``lifecycle_records``; the ``fault_history`` and ``maintenance_history``
lists are normalised into ``fault_events`` and ``maintenance_events`` rows,
respectively, ordered by their list index (``event_order``).

All write operations are atomic within a single transaction: the caller's
connection is used and a full commit is issued after every successful write.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from lifecycle.models import (
    AssetLifecycleRecord,
    FaultEvent,
    FaultSeverity,
    LifecycleState,
    MaintenanceEvent,
)


class LifecycleRepository:
    """
    CRUD operations for ``lifecycle_records``, ``fault_events``, and
    ``maintenance_events``.

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

    def upsert(self, record: AssetLifecycleRecord) -> None:
        """
        Persist the full lifecycle record (scalar state + all event history).

        This is a full replace: existing fault/maintenance event rows for this
        asset are deleted and re-inserted to reflect the current list order.

        Parameters
        ----------
        record:
            The ``AssetLifecycleRecord`` to persist.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO lifecycle_records (
                asset_id, state, age_years, rated_lifespan_years, rated_kva,
                insulation_health_pct, cumulative_fault_events,
                maintenance_overdue_days, average_load_factor,
                failure_count_last_5yr, failures_caused_by_weather,
                last_failure_days_ago, repeat_fault_active, predecessor_asset_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.asset_id,
                record.state.value,
                record.age_years,
                record.rated_lifespan_years,
                record.rated_kva,
                record.insulation_health_pct,
                record.cumulative_fault_events,
                record.maintenance_overdue_days,
                record.average_load_factor,
                record.failure_count_last_5yr,
                record.failures_caused_by_weather,
                record.last_failure_days_ago,
                int(record.repeat_fault_active),
                record.predecessor_asset_id,
            ),
        )
        # Replace event histories
        self._conn.execute(
            "DELETE FROM fault_events WHERE asset_id = ?", (record.asset_id,)
        )
        self._conn.execute(
            "DELETE FROM maintenance_events WHERE asset_id = ?", (record.asset_id,)
        )
        for order, event in enumerate(record.fault_history):
            _insert_fault_event(self._conn, "fault_events", "asset_id",
                                record.asset_id, event, order)
        for order, event in enumerate(record.maintenance_history):
            _insert_maintenance_event(self._conn, "maintenance_events", "asset_id",
                                      record.asset_id, event, order)
        self._conn.commit()

    def delete(self, asset_id: str) -> None:
        """
        Delete all lifecycle data for *asset_id* (scalar + events).

        Fault/maintenance events are deleted automatically via foreign key
        cascade behaviour, but we delete explicitly for portability.
        """
        self._conn.execute(
            "DELETE FROM fault_events WHERE asset_id = ?", (asset_id,)
        )
        self._conn.execute(
            "DELETE FROM maintenance_events WHERE asset_id = ?", (asset_id,)
        )
        self._conn.execute(
            "DELETE FROM lifecycle_records WHERE asset_id = ?", (asset_id,)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, asset_id: str) -> AssetLifecycleRecord | None:
        """
        Return the ``AssetLifecycleRecord`` for *asset_id*, or ``None``.

        Reconstructs ``fault_history`` and ``maintenance_history`` from their
        respective event tables, preserving original list order.
        """
        row = self._conn.execute(
            "SELECT * FROM lifecycle_records WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            return None

        fault_history = _load_fault_events(
            self._conn, "fault_events", "asset_id", asset_id
        )
        maintenance_history = _load_maintenance_events(
            self._conn, "maintenance_events", "asset_id", asset_id
        )
        return _row_to_record(row, fault_history, maintenance_history)

    def list_all(self) -> list[AssetLifecycleRecord]:
        """Return all lifecycle records, ordered by asset_id."""
        rows = self._conn.execute(
            "SELECT * FROM lifecycle_records ORDER BY asset_id"
        ).fetchall()
        result = []
        for row in rows:
            asset_id = row["asset_id"]
            fault_history = _load_fault_events(
                self._conn, "fault_events", "asset_id", asset_id
            )
            maintenance_history = _load_maintenance_events(
                self._conn, "maintenance_events", "asset_id", asset_id
            )
            result.append(_row_to_record(row, fault_history, maintenance_history))
        return result

    def exists(self, asset_id: str) -> bool:
        """Return ``True`` if a lifecycle record exists for *asset_id*."""
        row = self._conn.execute(
            "SELECT 1 FROM lifecycle_records WHERE asset_id = ? LIMIT 1",
            (asset_id,),
        ).fetchone()
        return row is not None

    def count(self) -> int:
        """Return the total number of lifecycle records."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM lifecycle_records"
        ).fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Private helpers — shared by LifecycleRepository and RetiredAssetRepository
# ---------------------------------------------------------------------------

def _insert_fault_event(
    conn: sqlite3.Connection,
    table: str,
    fk_col: str,
    fk_val: str,
    event: FaultEvent,
    order: int,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {table} (
            {fk_col}, severity, days_ago, weather_related,
            repeat_mode, description, stress_increment, event_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fk_val,
            event.severity.value,
            event.days_ago,
            int(event.weather_related),
            int(event.repeat_mode),
            event.description,
            event.stress_increment,
            order,
        ),
    )


def _insert_maintenance_event(
    conn: sqlite3.Connection,
    table: str,
    fk_col: str,
    fk_val: str,
    event: MaintenanceEvent,
    order: int,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {table} (
            {fk_col}, days_ago, overdue_days_resolved,
            insulation_health_improvement, notes, is_major_repair, event_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fk_val,
            event.days_ago,
            event.overdue_days_resolved,
            event.insulation_health_improvement,
            event.notes,
            int(event.is_major_repair),
            order,
        ),
    )


def _load_fault_events(
    conn: sqlite3.Connection,
    table: str,
    fk_col: str,
    fk_val: str,
) -> list[FaultEvent]:
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {fk_col} = ? ORDER BY event_order",
        (fk_val,),
    ).fetchall()
    return [_row_to_fault_event(r) for r in rows]


def _load_maintenance_events(
    conn: sqlite3.Connection,
    table: str,
    fk_col: str,
    fk_val: str,
) -> list[MaintenanceEvent]:
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {fk_col} = ? ORDER BY event_order",
        (fk_val,),
    ).fetchall()
    return [_row_to_maintenance_event(r) for r in rows]


def _row_to_fault_event(row: sqlite3.Row) -> FaultEvent:
    return FaultEvent(
        severity=FaultSeverity(row["severity"]),
        days_ago=row["days_ago"],
        weather_related=bool(row["weather_related"]),
        repeat_mode=bool(row["repeat_mode"]),
        description=row["description"],
        stress_increment=row["stress_increment"],  # None or float
    )


def _row_to_maintenance_event(row: sqlite3.Row) -> MaintenanceEvent:
    return MaintenanceEvent(
        days_ago=row["days_ago"],
        overdue_days_resolved=row["overdue_days_resolved"],
        insulation_health_improvement=row["insulation_health_improvement"],
        notes=row["notes"],
        is_major_repair=bool(row["is_major_repair"]),
    )


def _row_to_record(
    row: sqlite3.Row,
    fault_history: list[FaultEvent],
    maintenance_history: list[MaintenanceEvent],
) -> AssetLifecycleRecord:
    return AssetLifecycleRecord(
        asset_id=row["asset_id"],
        state=LifecycleState(row["state"]),
        age_years=row["age_years"],
        rated_lifespan_years=row["rated_lifespan_years"],
        rated_kva=row["rated_kva"],
        insulation_health_pct=row["insulation_health_pct"],
        cumulative_fault_events=row["cumulative_fault_events"],
        maintenance_overdue_days=row["maintenance_overdue_days"],
        average_load_factor=row["average_load_factor"],
        failure_count_last_5yr=row["failure_count_last_5yr"],
        failures_caused_by_weather=row["failures_caused_by_weather"],
        last_failure_days_ago=row["last_failure_days_ago"],
        repeat_fault_active=bool(row["repeat_fault_active"]),
        predecessor_asset_id=row["predecessor_asset_id"],
        fault_history=fault_history,
        maintenance_history=maintenance_history,
    )
