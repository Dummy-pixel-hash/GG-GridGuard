"""
DDL for every GridGuard table.

All tables use explicit ``CREATE TABLE IF NOT EXISTS`` so this module can be
called on every startup without error.

Schema overview
---------------
assets              — asset registry (AssetMetadata + AssetLocation)
grid_topology       — consequence-of-failure data (RawGridTopology) per asset
lifecycle_records   — scalar lifecycle state (AssetLifecycleRecord scalars)
fault_events        — one row per FaultEvent in an asset's history
maintenance_events  — one row per MaintenanceEvent in an asset's history
retired_assets      — RetiredAssetRecord (lineage snapshots)
retired_fault_events       — FaultEvent rows belonging to a retired asset
retired_maintenance_events — MaintenanceEvent rows for a retired asset
risk_results        — timestamped RiskResult snapshots (ComponentScores inline)

Foreign key relationships
-------------------------
grid_topology.asset_id  → assets.asset_id
lifecycle_records.asset_id → assets.asset_id
fault_events.asset_id  → lifecycle_records.asset_id
maintenance_events.asset_id → lifecycle_records.asset_id
retired_fault_events.retired_asset_id → retired_assets.asset_id
retired_maintenance_events.retired_asset_id → retired_assets.asset_id
risk_results.asset_id  → assets.asset_id  (advisory; asset may be retired)
"""

from __future__ import annotations

import sqlite3


_DDL = """
-- ─────────────────────────────────────────────────────────────
-- Asset registry
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assets (
    asset_id                TEXT PRIMARY KEY,
    asset_type              TEXT NOT NULL,
    rated_kva               REAL NOT NULL,
    rated_voltage_kv        REAL NOT NULL,
    rated_lifespan_years    REAL NOT NULL DEFAULT 40.0,
    commissioned_year       INTEGER NOT NULL,
    latitude                REAL NOT NULL DEFAULT 0.0,
    longitude               REAL NOT NULL DEFAULT 0.0,
    substation_name         TEXT NOT NULL DEFAULT '',
    region                  TEXT NOT NULL DEFAULT '',
    notes                   TEXT NOT NULL DEFAULT ''
);

-- ─────────────────────────────────────────────────────────────
-- Grid topology / consequence-of-failure data
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_topology (
    asset_id                    TEXT PRIMARY KEY,
    customers_served            INTEGER NOT NULL DEFAULT 0,
    critical_facility_count     INTEGER NOT NULL DEFAULT 0,
    critical_facility_names_json TEXT NOT NULL DEFAULT '[]',
    peak_load_mw                REAL NOT NULL DEFAULT 0.0,
    downstream_asset_count      INTEGER NOT NULL DEFAULT 0,
    has_n1_redundancy           INTEGER NOT NULL DEFAULT 1,   -- boolean: 0/1
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

-- ─────────────────────────────────────────────────────────────
-- Lifecycle state (scalar fields only; events are separate rows)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lifecycle_records (
    asset_id                    TEXT PRIMARY KEY,
    state                       TEXT NOT NULL DEFAULT 'active',
    age_years                   REAL NOT NULL DEFAULT 0.0,
    rated_lifespan_years        REAL NOT NULL DEFAULT 40.0,
    rated_kva                   REAL NOT NULL DEFAULT 0.0,
    insulation_health_pct       REAL,                           -- NULL allowed
    cumulative_fault_events     INTEGER NOT NULL DEFAULT 0,
    maintenance_overdue_days    INTEGER NOT NULL DEFAULT 0,
    average_load_factor         REAL NOT NULL DEFAULT 0.5,
    failure_count_last_5yr      INTEGER NOT NULL DEFAULT 0,
    failures_caused_by_weather  INTEGER NOT NULL DEFAULT 0,
    last_failure_days_ago       INTEGER,                        -- NULL allowed
    repeat_fault_active         INTEGER NOT NULL DEFAULT 0,     -- boolean
    predecessor_asset_id        TEXT,                           -- NULL if original
    FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
);

-- ─────────────────────────────────────────────────────────────
-- Fault events (active asset history)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fault_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id            TEXT NOT NULL,
    severity            TEXT NOT NULL,
    days_ago            INTEGER NOT NULL DEFAULT 0,
    weather_related     INTEGER NOT NULL DEFAULT 0,    -- boolean
    repeat_mode         INTEGER NOT NULL DEFAULT 0,    -- boolean
    description         TEXT NOT NULL DEFAULT '',
    stress_increment    REAL,                          -- NULL = used default
    event_order         INTEGER NOT NULL DEFAULT 0,    -- position in list
    FOREIGN KEY (asset_id) REFERENCES lifecycle_records(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_fault_events_asset
    ON fault_events(asset_id, event_order);

-- ─────────────────────────────────────────────────────────────
-- Maintenance events (active asset history)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS maintenance_events (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id                        TEXT NOT NULL,
    days_ago                        INTEGER NOT NULL DEFAULT 0,
    overdue_days_resolved           INTEGER NOT NULL DEFAULT 0,
    insulation_health_improvement   REAL,              -- NULL = not measured
    notes                           TEXT NOT NULL DEFAULT '',
    is_major_repair                 INTEGER NOT NULL DEFAULT 0,  -- boolean
    event_order                     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (asset_id) REFERENCES lifecycle_records(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_maintenance_events_asset
    ON maintenance_events(asset_id, event_order);

-- ─────────────────────────────────────────────────────────────
-- Retired asset records (lineage snapshots)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS retired_assets (
    asset_id                            TEXT PRIMARY KEY,
    state                               TEXT NOT NULL DEFAULT 'retired',
    age_at_retirement_years             REAL NOT NULL DEFAULT 0.0,
    rated_lifespan_years                REAL NOT NULL DEFAULT 40.0,
    rated_kva                           REAL NOT NULL DEFAULT 0.0,
    insulation_health_pct_at_retirement REAL,
    cumulative_fault_events             INTEGER NOT NULL DEFAULT 0,
    total_failure_count                 INTEGER NOT NULL DEFAULT 0,
    failures_caused_by_weather          INTEGER NOT NULL DEFAULT 0,
    retirement_reason                   TEXT NOT NULL DEFAULT '',
    successor_asset_id                  TEXT
);

-- ─────────────────────────────────────────────────────────────
-- Fault events belonging to a retired asset
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS retired_fault_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    retired_asset_id    TEXT NOT NULL,
    severity            TEXT NOT NULL,
    days_ago            INTEGER NOT NULL DEFAULT 0,
    weather_related     INTEGER NOT NULL DEFAULT 0,
    repeat_mode         INTEGER NOT NULL DEFAULT 0,
    description         TEXT NOT NULL DEFAULT '',
    stress_increment    REAL,
    event_order         INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (retired_asset_id) REFERENCES retired_assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_retired_fault_events_asset
    ON retired_fault_events(retired_asset_id, event_order);

-- ─────────────────────────────────────────────────────────────
-- Maintenance events belonging to a retired asset
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS retired_maintenance_events (
    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
    retired_asset_id                TEXT NOT NULL,
    days_ago                        INTEGER NOT NULL DEFAULT 0,
    overdue_days_resolved           INTEGER NOT NULL DEFAULT 0,
    insulation_health_improvement   REAL,
    notes                           TEXT NOT NULL DEFAULT '',
    is_major_repair                 INTEGER NOT NULL DEFAULT 0,
    event_order                     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (retired_asset_id) REFERENCES retired_assets(asset_id)
);

CREATE INDEX IF NOT EXISTS idx_retired_maintenance_events_asset
    ON retired_maintenance_events(retired_asset_id, event_order);

-- ─────────────────────────────────────────────────────────────
-- Risk results (timestamped; one row per scoring run per asset)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id            TEXT NOT NULL,
    scored_at           TEXT NOT NULL,              -- ISO-8601 timestamp
    overall_risk        REAL NOT NULL,
    risk_level          TEXT NOT NULL,
    component_sensor    REAL NOT NULL,
    component_weather   REAL NOT NULL,
    component_history   REAL NOT NULL,
    component_degradation REAL NOT NULL,
    component_grid_impact REAL NOT NULL,
    dominant_factor     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_risk_results_asset_time
    ON risk_results(asset_id, scored_at);
"""


def create_all_tables(conn: sqlite3.Connection) -> None:
    """
    Execute the DDL to create every GridGuard table.

    Idempotent — safe to call on every application startup.
    All statements use ``CREATE TABLE IF NOT EXISTS``.

    Parameters
    ----------
    conn:
        An open SQLite connection (from ``get_connection()``).
    """
    conn.executescript(_DDL)
    conn.commit()
