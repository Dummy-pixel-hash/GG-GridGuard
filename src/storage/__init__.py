"""
GridGuard storage layer — SQLite-backed persistence.

Public API
----------
    get_connection(path)                  -> sqlite3.Connection
    AssetRepository(conn)                 -> CRUD for asset registry records
    LifecycleRepository(conn)             -> CRUD for AssetLifecycleRecord + event histories
    RetiredAssetRepository(conn)          -> CRUD for RetiredAssetRecord (lineage)
    RiskResultRepository(conn)            -> CRUD for RiskResult (timestamped score history)
    GridTopologyRepository(conn)          -> CRUD for RawGridTopology per asset
    create_all_tables(conn)               -> idempotent DDL; call on startup
    seed_demo_assets(conn)                -> insert TX-001…TX-008 if not already present

All repositories are thin wrappers over sqlite3 — no third-party ORM.
The schema is normalised: event histories are stored as individual rows
(fault_events, maintenance_events) rather than JSON blobs, making them
queryable.  A single JSON helper in serialisation.py handles the small
number of list fields (e.g. critical_facility_names) that have no useful
per-row query pattern.
"""

from __future__ import annotations

from .connection import get_connection
from .repositories.assets import AssetRepository
from .repositories.grid_topology import GridTopologyRepository
from .repositories.lifecycle import LifecycleRepository
from .repositories.retired import RetiredAssetRepository
from .repositories.risk_results import RiskResultRepository
from .schema import create_all_tables
from .seeder import seed_demo_assets

__all__ = [
    "get_connection",
    "create_all_tables",
    "seed_demo_assets",
    "AssetRepository",
    "LifecycleRepository",
    "RetiredAssetRepository",
    "RiskResultRepository",
    "GridTopologyRepository",
]
