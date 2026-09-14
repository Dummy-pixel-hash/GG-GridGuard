"""
Demo asset seeder for GridGuard.

Seeds the 8 synthetic demo assets (TX-001 … TX-008) into an existing
SQLite database.  Idempotent: assets already present are skipped so the
seeder is safe to call on every application startup.

What gets seeded per asset
--------------------------
1. ``assets`` table  — AssetMetadata + AssetLocation from RawAssetRecord.metadata
2. ``grid_topology`` table — RawGridTopology from RawAssetRecord.topology
3. ``lifecycle_records`` + ``fault_events`` + ``maintenance_events`` tables —
   AssetLifecycleRecord constructed from the degradation and incident fields
   in the RawAssetRecord.  Demo assets have empty event-history lists because
   they model current state, not an event log.

The storage layer is the single source of truth once seeded.  Callers can
then use AssetRepository, LifecycleRepository, etc. to read back these records.
"""

from __future__ import annotations

import sqlite3

from data.demo_assets import ALL_ASSETS
from data.raw_types import RawAssetRecord
from lifecycle.models import AssetLifecycleRecord, LifecycleState
from storage.repositories.assets import AssetRepository
from storage.repositories.grid_topology import GridTopologyRepository
from storage.repositories.lifecycle import LifecycleRepository


def seed_demo_assets(conn: sqlite3.Connection) -> int:
    """
    Seed the 8 demo assets into the database if they are not already present.

    Parameters
    ----------
    conn:
        Open SQLite connection with tables already created (call
        ``create_all_tables(conn)`` first).

    Returns
    -------
    int
        The number of assets actually inserted (0 if all were already present).
    """
    asset_repo = AssetRepository(conn)
    topo_repo = GridTopologyRepository(conn)
    lifecycle_repo = LifecycleRepository(conn)

    inserted = 0
    for raw in ALL_ASSETS:
        if asset_repo.exists(raw.metadata.asset_id):
            continue  # idempotent: skip existing assets

        asset_repo.upsert(raw.metadata)
        topo_repo.upsert(raw.metadata.asset_id, raw.topology)
        lifecycle_repo.upsert(_raw_to_lifecycle(raw))
        inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _raw_to_lifecycle(raw: RawAssetRecord) -> AssetLifecycleRecord:
    """
    Build an ``AssetLifecycleRecord`` from a ``RawAssetRecord``.

    Demo assets do not carry a full event log (they represent current state,
    not a replay of history), so fault_history and maintenance_history are
    initialised to empty lists.

    The scalar degradation and incident fields from the raw record are mapped
    directly into the lifecycle record.
    """
    d = raw.degradation
    i = raw.incidents
    return AssetLifecycleRecord(
        asset_id=raw.metadata.asset_id,
        state=LifecycleState.ACTIVE,
        age_years=d.age_years,
        rated_lifespan_years=raw.metadata.rated_lifespan_years,
        rated_kva=raw.metadata.rated_kva,
        insulation_health_pct=d.insulation_health_pct,
        cumulative_fault_events=d.cumulative_fault_events,
        maintenance_overdue_days=d.maintenance_overdue_days,
        average_load_factor=d.average_load_factor,
        failure_count_last_5yr=i.failure_count_last_5yr,
        failures_caused_by_weather=i.failures_caused_by_weather,
        last_failure_days_ago=i.last_failure_days_ago,
        repeat_fault_active=i.repeat_mode_flag,
        fault_history=[],
        maintenance_history=[],
        predecessor_asset_id=None,
    )
