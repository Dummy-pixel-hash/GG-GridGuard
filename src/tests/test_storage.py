"""
Unit tests for the GridGuard storage layer.

Coverage
--------
  1.  Schema — create_all_tables is idempotent (safe to call twice)
  2.  AssetRepository — upsert, get, list_all, exists, count, delete
  3.  GridTopologyRepository — upsert, get, list_all, critical_facility_names
        round-trip (JSON list → DB → list[str])
  4.  LifecycleRepository — upsert, get, list_all, exists, count, delete;
        scalar field round-trip; fault/maintenance event list preservation;
        event ordering; None-able fields (insulation_health_pct, last_failure_days_ago,
        predecessor_asset_id, stress_increment, insulation_health_improvement)
  5.  RetiredAssetRepository — upsert, get, get_by_successor, list_all,
        exists, count, delete; event histories preserved; lineage tracing
        (get_by_successor chains predecessor → successor correctly)
  6.  RiskResultRepository — insert, get_latest, list_for_asset,
        list_latest_all, count, count_for_asset, delete_for_asset;
        multiple results per asset; latest selection by timestamp;
        RiskLevel and ComponentScores round-trip
  7.  Seeder — seed_demo_assets inserts all 8 demo assets; re-seeding is
        idempotent (0 inserted on second call); all 8 assets retrievable;
        seeded lifecycle records carry correct scalar fields
  8.  Integration — full round-trip: raw demo asset → seed → retrieve lifecycle
        record → to_raw_degradation()/to_raw_incidents() → normalise() →
        score_asset() produces expected RiskLevel bands
  9.  Lineage — apply_replacement → store retired + successor → retrieve both
        → confirm bidirectional link (successor.predecessor_asset_id and
        retired.successor_asset_id)
  10. Isolation — each test uses a fresh in-memory database; no shared state
        between tests

All data is synthetic / invented for test purposes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from data.demo_assets import ALL_ASSETS, TX_001, TX_007
from lifecycle.engine import apply_fault, apply_replacement
from lifecycle.models import (
    AssetLifecycleRecord,
    FaultEvent,
    FaultSeverity,
    LifecycleState,
    MaintenanceEvent,
    ReplacementEvent,
    RetiredAssetRecord,
)
from normalisation import normalise
from risk_engine import RiskLevel, score_asset
from risk_engine.models import ComponentScores, RiskResult
from storage import (
    AssetRepository,
    GridTopologyRepository,
    LifecycleRepository,
    RetiredAssetRepository,
    RiskResultRepository,
    create_all_tables,
    get_connection,
    seed_demo_assets,
)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _fresh_db() -> sqlite3.Connection:
    """Return a fresh in-memory DB with all tables created."""
    conn = get_connection(":memory:")
    create_all_tables(conn)
    return conn


def _sample_asset_record() -> AssetLifecycleRecord:
    """A minimal lifecycle record for CRUD tests."""
    return AssetLifecycleRecord(
        asset_id="TX-TEST",
        state=LifecycleState.ACTIVE,
        age_years=15.0,
        rated_lifespan_years=40.0,
        rated_kva=25_000.0,
        insulation_health_pct=80.0,
        cumulative_fault_events=2,
        maintenance_overdue_days=30,
        average_load_factor=0.6,
        failure_count_last_5yr=1,
        failures_caused_by_weather=0,
        last_failure_days_ago=200,
        repeat_fault_active=False,
        predecessor_asset_id=None,
        fault_history=[],
        maintenance_history=[],
    )


def _sample_risk_result(asset_id: str = "TX-TEST") -> RiskResult:
    """A minimal RiskResult for CRUD tests."""
    return RiskResult(
        asset_id=asset_id,
        overall_risk=55.0,
        risk_level=RiskLevel.WATCH,
        components=ComponentScores(
            sensor_health=50.0,
            weather_risk=60.0,
            historical_failure=40.0,
            asset_degradation=65.0,
            grid_impact=55.0,
        ),
        dominant_factor="weather_risk",
    )


# ===========================================================================
# 1. Schema
# ===========================================================================

class TestSchema:

    def test_create_tables_is_idempotent(self):
        """Calling create_all_tables twice must not raise."""
        conn = get_connection(":memory:")
        create_all_tables(conn)
        create_all_tables(conn)  # second call — must succeed silently

    def test_all_expected_tables_exist(self):
        conn = _fresh_db()
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "assets", "grid_topology", "lifecycle_records",
            "fault_events", "maintenance_events",
            "retired_assets", "retired_fault_events",
            "retired_maintenance_events", "risk_results",
        }
        assert expected.issubset(tables)

    def test_foreign_keys_enabled(self):
        conn = _fresh_db()
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1


# ===========================================================================
# 2. AssetRepository
# ===========================================================================

class TestAssetRepository:

    def test_upsert_and_get_roundtrip(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        meta = TX_001.metadata
        repo.upsert(meta)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert fetched.asset_id == "TX-001"
        assert fetched.asset_type == "transformer"
        assert fetched.rated_kva == 40_000.0
        assert fetched.rated_voltage_kv == 66.0
        assert fetched.rated_lifespan_years == 40.0
        assert fetched.commissioned_year == 2015
        assert fetched.location.latitude == pytest.approx(51.505)
        assert fetched.location.longitude == pytest.approx(-0.128)
        assert fetched.location.substation_name == "Riverside Main"
        assert fetched.location.region == "Central"

    def test_get_returns_none_for_missing(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        assert repo.get("TX-NOTEXIST") is None

    def test_exists_true_and_false(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        assert not repo.exists("TX-001")
        repo.upsert(TX_001.metadata)
        assert repo.exists("TX-001")

    def test_count(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        assert repo.count() == 0
        repo.upsert(TX_001.metadata)
        assert repo.count() == 1
        repo.upsert(TX_007.metadata)
        assert repo.count() == 2

    def test_upsert_is_idempotent(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        repo.upsert(TX_001.metadata)
        repo.upsert(TX_001.metadata)
        assert repo.count() == 1

    def test_upsert_updates_existing(self):
        """Second upsert with changed notes should overwrite."""
        from data.raw_types import AssetLocation, AssetMetadata
        conn = _fresh_db()
        repo = AssetRepository(conn)
        repo.upsert(TX_001.metadata)

        import copy
        updated = copy.copy(TX_001.metadata)
        updated.notes = "Updated notes"
        repo.upsert(updated)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert fetched.notes == "Updated notes"
        assert repo.count() == 1

    def test_list_all_returns_all_ordered(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        # Insert in reverse alphabetical order
        repo.upsert(TX_007.metadata)
        repo.upsert(TX_001.metadata)

        results = repo.list_all()
        ids = [r.asset_id for r in results]
        assert ids == sorted(ids)

    def test_delete(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        repo.upsert(TX_001.metadata)
        assert repo.exists("TX-001")
        repo.delete("TX-001")
        assert not repo.exists("TX-001")
        assert repo.count() == 0

    def test_delete_nonexistent_is_silent(self):
        conn = _fresh_db()
        repo = AssetRepository(conn)
        repo.delete("TX-NOTEXIST")  # must not raise


# ===========================================================================
# 3. GridTopologyRepository
# ===========================================================================

class TestGridTopologyRepository:

    def test_upsert_and_get_roundtrip(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_007.metadata)

        topo_repo = GridTopologyRepository(conn)
        topo_repo.upsert("TX-007", TX_007.topology)

        fetched = topo_repo.get("TX-007")
        assert fetched is not None
        assert fetched.customers_served == 46_000
        assert fetched.critical_facility_count == 3
        assert fetched.peak_load_mw == pytest.approx(44.0)
        assert fetched.downstream_asset_count == 9
        assert fetched.has_n1_redundancy is False

    def test_critical_facility_names_roundtrip(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_007.metadata)

        topo_repo = GridTopologyRepository(conn)
        topo_repo.upsert("TX-007", TX_007.topology)

        fetched = topo_repo.get("TX-007")
        assert fetched is not None
        expected = [
            "City General Hospital",
            "Waterfront Water Treatment",
            "Fire Station HQ",
        ]
        assert fetched.critical_facility_names == expected

    def test_empty_critical_facility_names(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        topo_repo = GridTopologyRepository(conn)
        topo_repo.upsert("TX-001", TX_001.topology)

        fetched = topo_repo.get("TX-001")
        assert fetched is not None
        assert fetched.critical_facility_names == []

    def test_has_n1_redundancy_true(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        topo_repo = GridTopologyRepository(conn)
        topo_repo.upsert("TX-001", TX_001.topology)

        fetched = topo_repo.get("TX-001")
        assert fetched is not None
        assert fetched.has_n1_redundancy is True

    def test_get_returns_none_for_missing(self):
        conn = _fresh_db()
        topo_repo = GridTopologyRepository(conn)
        assert topo_repo.get("TX-NOTEXIST") is None

    def test_list_all(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        topo_repo = GridTopologyRepository(conn)
        for raw in [TX_001, TX_007]:
            asset_repo.upsert(raw.metadata)
            topo_repo.upsert(raw.metadata.asset_id, raw.topology)

        pairs = topo_repo.list_all()
        assert len(pairs) == 2
        ids = [p[0] for p in pairs]
        assert "TX-001" in ids
        assert "TX-007" in ids

    def test_upsert_updates_existing(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        topo_repo = GridTopologyRepository(conn)
        topo_repo.upsert("TX-001", TX_001.topology)

        from data.raw_types import RawGridTopology
        updated = RawGridTopology(
            customers_served=99_999,
            critical_facility_count=5,
            critical_facility_names=["Hospital A", "Hospital B"],
            peak_load_mw=100.0,
            downstream_asset_count=20,
            has_n1_redundancy=False,
        )
        topo_repo.upsert("TX-001", updated)

        fetched = topo_repo.get("TX-001")
        assert fetched is not None
        assert fetched.customers_served == 99_999
        assert fetched.critical_facility_names == ["Hospital A", "Hospital B"]


# ===========================================================================
# 4. LifecycleRepository
# ===========================================================================

class TestLifecycleRepository:

    def test_upsert_and_get_scalar_roundtrip(self):
        conn = _fresh_db()
        # lifecycle_records has a FK to assets
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        repo = LifecycleRepository(conn)
        record = AssetLifecycleRecord(
            asset_id="TX-001",
            state=LifecycleState.ACTIVE,
            age_years=10.0,
            rated_lifespan_years=40.0,
            rated_kva=40_000.0,
            insulation_health_pct=96.0,
            cumulative_fault_events=0,
            maintenance_overdue_days=0,
            average_load_factor=0.42,
            failure_count_last_5yr=0,
            failures_caused_by_weather=0,
            last_failure_days_ago=None,
            repeat_fault_active=False,
            predecessor_asset_id=None,
            fault_history=[],
            maintenance_history=[],
        )
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert fetched.asset_id == "TX-001"
        assert fetched.state == LifecycleState.ACTIVE
        assert fetched.age_years == pytest.approx(10.0)
        assert fetched.rated_lifespan_years == pytest.approx(40.0)
        assert fetched.insulation_health_pct == pytest.approx(96.0)
        assert fetched.cumulative_fault_events == 0
        assert fetched.maintenance_overdue_days == 0
        assert fetched.average_load_factor == pytest.approx(0.42)
        assert fetched.failure_count_last_5yr == 0
        assert fetched.last_failure_days_ago is None
        assert fetched.repeat_fault_active is False
        assert fetched.predecessor_asset_id is None

    def test_nullable_insulation_health_preserved(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        repo = LifecycleRepository(conn)
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.insulation_health_pct = None
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert fetched.insulation_health_pct is None

    def test_faulted_state_roundtrip(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        repo = LifecycleRepository(conn)
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.state = LifecycleState.FAULTED
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert fetched.state == LifecycleState.FAULTED

    def test_fault_history_roundtrip(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        fault_events = [
            FaultEvent(
                severity=FaultSeverity.MINOR,
                days_ago=365,
                weather_related=True,
                repeat_mode=False,
                description="Minor overheating",
                stress_increment=None,
            ),
            FaultEvent(
                severity=FaultSeverity.MAJOR,
                days_ago=30,
                weather_related=False,
                repeat_mode=True,
                description="Winding fault",
                stress_increment=18.5,
            ),
        ]
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.fault_history = fault_events

        repo = LifecycleRepository(conn)
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert len(fetched.fault_history) == 2

        e0 = fetched.fault_history[0]
        assert e0.severity == FaultSeverity.MINOR
        assert e0.days_ago == 365
        assert e0.weather_related is True
        assert e0.repeat_mode is False
        assert e0.description == "Minor overheating"
        assert e0.stress_increment is None

        e1 = fetched.fault_history[1]
        assert e1.severity == FaultSeverity.MAJOR
        assert e1.days_ago == 30
        assert e1.weather_related is False
        assert e1.repeat_mode is True
        assert e1.stress_increment == pytest.approx(18.5)

    def test_fault_history_ordering_preserved(self):
        """Events must come back in the same list order they were stored."""
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        events = [
            FaultEvent(severity=FaultSeverity.MINOR, days_ago=i * 10)
            for i in range(5)
        ]
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.fault_history = events

        repo = LifecycleRepository(conn)
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        recovered_days = [e.days_ago for e in fetched.fault_history]
        assert recovered_days == [e.days_ago for e in events]

    def test_maintenance_history_roundtrip(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        maintenance_events = [
            MaintenanceEvent(
                days_ago=180,
                overdue_days_resolved=30,
                insulation_health_improvement=5.0,
                notes="Scheduled inspection",
                is_major_repair=False,
            ),
            MaintenanceEvent(
                days_ago=10,
                overdue_days_resolved=0,
                insulation_health_improvement=None,
                notes="Oil sample only",
                is_major_repair=False,
            ),
        ]
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.maintenance_history = maintenance_events

        repo = LifecycleRepository(conn)
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert len(fetched.maintenance_history) == 2

        m0 = fetched.maintenance_history[0]
        assert m0.days_ago == 180
        assert m0.overdue_days_resolved == 30
        assert m0.insulation_health_improvement == pytest.approx(5.0)
        assert m0.notes == "Scheduled inspection"
        assert m0.is_major_repair is False

        m1 = fetched.maintenance_history[1]
        assert m1.insulation_health_improvement is None

    def test_upsert_replaces_event_history(self):
        """Second upsert must replace event rows, not accumulate them."""
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        repo = LifecycleRepository(conn)
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.fault_history = [FaultEvent(severity=FaultSeverity.MINOR)]
        repo.upsert(record)

        record.fault_history = [
            FaultEvent(severity=FaultSeverity.MAJOR),
            FaultEvent(severity=FaultSeverity.MINOR),
        ]
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert len(fetched.fault_history) == 2
        assert fetched.fault_history[0].severity == FaultSeverity.MAJOR

    def test_predecessor_asset_id_roundtrip(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        repo = LifecycleRepository(conn)
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.predecessor_asset_id = "TX-OLD-001"
        repo.upsert(record)

        fetched = repo.get("TX-001")
        assert fetched is not None
        assert fetched.predecessor_asset_id == "TX-OLD-001"

    def test_get_returns_none_for_missing(self):
        conn = _fresh_db()
        repo = LifecycleRepository(conn)
        assert repo.get("TX-NOTEXIST") is None

    def test_exists_and_count(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        repo = LifecycleRepository(conn)
        assert not repo.exists("TX-001")
        assert repo.count() == 0

        record = _sample_asset_record()
        record.asset_id = "TX-001"
        repo.upsert(record)

        assert repo.exists("TX-001")
        assert repo.count() == 1

    def test_delete_removes_record_and_events(self):
        conn = _fresh_db()
        asset_repo = AssetRepository(conn)
        asset_repo.upsert(TX_001.metadata)

        repo = LifecycleRepository(conn)
        record = _sample_asset_record()
        record.asset_id = "TX-001"
        record.fault_history = [FaultEvent(severity=FaultSeverity.MINOR)]
        repo.upsert(record)

        repo.delete("TX-001")
        assert not repo.exists("TX-001")
        assert repo.count() == 0

        # Event rows must also be gone
        fault_rows = conn.execute(
            "SELECT COUNT(*) FROM fault_events WHERE asset_id = 'TX-001'"
        ).fetchone()[0]
        assert fault_rows == 0

    def test_list_all(self):
        conn = _fresh_db()
        for raw in [TX_001, TX_007]:
            asset_repo = AssetRepository(conn)
            asset_repo.upsert(raw.metadata)
            repo = LifecycleRepository(conn)
            record = _sample_asset_record()
            record.asset_id = raw.metadata.asset_id
            repo.upsert(record)

        repo = LifecycleRepository(conn)
        records = repo.list_all()
        ids = {r.asset_id for r in records}
        assert "TX-001" in ids
        assert "TX-007" in ids


# ===========================================================================
# 5. RetiredAssetRepository
# ===========================================================================

class TestRetiredAssetRepository:

    def _make_retired(
        self,
        asset_id: str = "TX-OLD",
        successor_id: str | None = "TX-NEW",
    ) -> RetiredAssetRecord:
        return RetiredAssetRecord(
            asset_id=asset_id,
            state=LifecycleState.RETIRED,
            age_at_retirement_years=38.0,
            rated_lifespan_years=40.0,
            rated_kva=25_000.0,
            insulation_health_pct_at_retirement=22.0,
            cumulative_fault_events=8,
            total_failure_count=3,
            failures_caused_by_weather=2,
            fault_history=[
                FaultEvent(
                    severity=FaultSeverity.CRITICAL,
                    days_ago=5,
                    weather_related=True,
                    description="Final catastrophic fault",
                ),
            ],
            maintenance_history=[
                MaintenanceEvent(
                    days_ago=90,
                    notes="Last scheduled service",
                    is_major_repair=False,
                ),
            ],
            retirement_reason="End of life — replaced",
            successor_asset_id=successor_id,
        )

    def test_upsert_and_get_roundtrip(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        retired = self._make_retired()
        repo.upsert(retired)

        fetched = repo.get("TX-OLD")
        assert fetched is not None
        assert fetched.asset_id == "TX-OLD"
        assert fetched.state == LifecycleState.RETIRED
        assert fetched.age_at_retirement_years == pytest.approx(38.0)
        assert fetched.insulation_health_pct_at_retirement == pytest.approx(22.0)
        assert fetched.cumulative_fault_events == 8
        assert fetched.total_failure_count == 3
        assert fetched.failures_caused_by_weather == 2
        assert fetched.retirement_reason == "End of life — replaced"
        assert fetched.successor_asset_id == "TX-NEW"

    def test_fault_history_preserved(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        repo.upsert(self._make_retired())

        fetched = repo.get("TX-OLD")
        assert fetched is not None
        assert len(fetched.fault_history) == 1
        event = fetched.fault_history[0]
        assert event.severity == FaultSeverity.CRITICAL
        assert event.weather_related is True
        assert event.description == "Final catastrophic fault"

    def test_maintenance_history_preserved(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        repo.upsert(self._make_retired())

        fetched = repo.get("TX-OLD")
        assert fetched is not None
        assert len(fetched.maintenance_history) == 1
        m = fetched.maintenance_history[0]
        assert m.days_ago == 90
        assert m.notes == "Last scheduled service"

    def test_nullable_insulation_health(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        retired = self._make_retired()
        retired.insulation_health_pct_at_retirement = None
        repo.upsert(retired)

        fetched = repo.get("TX-OLD")
        assert fetched is not None
        assert fetched.insulation_health_pct_at_retirement is None

    def test_get_by_successor(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        repo.upsert(self._make_retired(asset_id="TX-OLD", successor_id="TX-NEW"))

        fetched = repo.get_by_successor("TX-NEW")
        assert fetched is not None
        assert fetched.asset_id == "TX-OLD"

    def test_get_by_successor_returns_none_when_no_predecessor(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        assert repo.get_by_successor("TX-NEW") is None

    def test_exists_count_delete(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)

        assert not repo.exists("TX-OLD")
        assert repo.count() == 0

        repo.upsert(self._make_retired())
        assert repo.exists("TX-OLD")
        assert repo.count() == 1

        repo.delete("TX-OLD")
        assert not repo.exists("TX-OLD")
        assert repo.count() == 0

    def test_delete_removes_event_rows(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        repo.upsert(self._make_retired())
        repo.delete("TX-OLD")

        fault_rows = conn.execute(
            "SELECT COUNT(*) FROM retired_fault_events WHERE retired_asset_id = 'TX-OLD'"
        ).fetchone()[0]
        assert fault_rows == 0

    def test_list_all(self):
        conn = _fresh_db()
        repo = RetiredAssetRepository(conn)
        repo.upsert(self._make_retired(asset_id="TX-OLD-A", successor_id="TX-A"))
        repo.upsert(self._make_retired(asset_id="TX-OLD-B", successor_id="TX-B"))

        all_retired = repo.list_all()
        ids = {r.asset_id for r in all_retired}
        assert "TX-OLD-A" in ids
        assert "TX-OLD-B" in ids


# ===========================================================================
# 6. RiskResultRepository
# ===========================================================================

class TestRiskResultRepository:

    def test_insert_and_get_latest(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)

        result = _sample_risk_result("TX-TEST")
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        repo.insert(result, scored_at=ts)

        fetched = repo.get_latest("TX-TEST")
        assert fetched is not None
        assert fetched.asset_id == "TX-TEST"
        assert fetched.overall_risk == pytest.approx(55.0)
        assert fetched.risk_level == RiskLevel.WATCH
        assert fetched.dominant_factor == "weather_risk"

    def test_component_scores_roundtrip(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)
        result = _sample_risk_result()
        repo.insert(result)

        fetched = repo.get_latest("TX-TEST")
        assert fetched is not None
        assert fetched.components.sensor_health == pytest.approx(50.0)
        assert fetched.components.weather_risk == pytest.approx(60.0)
        assert fetched.components.historical_failure == pytest.approx(40.0)
        assert fetched.components.asset_degradation == pytest.approx(65.0)
        assert fetched.components.grid_impact == pytest.approx(55.0)

    def test_get_latest_returns_most_recent(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)
        t1 = datetime(2025, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 20, 0, 0, 0, tzinfo=timezone.utc)

        older = RiskResult(
            asset_id="TX-TEST",
            overall_risk=40.0,
            risk_level=RiskLevel.WATCH,
            components=ComponentScores(40.0, 40.0, 40.0, 40.0, 40.0),
            dominant_factor="sensor_health",
        )
        newer = RiskResult(
            asset_id="TX-TEST",
            overall_risk=85.0,
            risk_level=RiskLevel.CRITICAL,
            components=ComponentScores(90.0, 85.0, 80.0, 85.0, 80.0),
            dominant_factor="sensor_health",
        )
        repo.insert(older, scored_at=t1)
        repo.insert(newer, scored_at=t2)

        latest = repo.get_latest("TX-TEST")
        assert latest is not None
        assert latest.overall_risk == pytest.approx(85.0)
        assert latest.risk_level == RiskLevel.CRITICAL

    def test_get_latest_returns_none_for_missing(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)
        assert repo.get_latest("TX-NOTEXIST") is None

    def test_list_for_asset_ordered_oldest_first(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)
        t1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 2, tzinfo=timezone.utc)
        t3 = datetime(2025, 1, 3, tzinfo=timezone.utc)

        for t, score in [(t2, 55.0), (t1, 30.0), (t3, 75.0)]:
            r = RiskResult(
                asset_id="TX-TEST",
                overall_risk=score,
                risk_level=RiskLevel.WATCH,
                components=ComponentScores(score, score, score, score, score),
                dominant_factor="sensor_health",
            )
            repo.insert(r, scored_at=t)

        results = repo.list_for_asset("TX-TEST")
        scores = [r.overall_risk for r in results]
        assert scores == [30.0, 55.0, 75.0]

    def test_list_latest_all_highest_risk_first(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)

        for asset_id, score in [("TX-A", 30.0), ("TX-B", 90.0), ("TX-C", 60.0)]:
            r = RiskResult(
                asset_id=asset_id,
                overall_risk=score,
                risk_level=RiskLevel.WATCH,
                components=ComponentScores(score, score, score, score, score),
                dominant_factor="sensor_health",
            )
            repo.insert(r)

        results = repo.list_latest_all()
        scores = [r.overall_risk for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_count_and_count_for_asset(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)
        assert repo.count() == 0

        for _ in range(3):
            repo.insert(_sample_risk_result("TX-TEST"))
        repo.insert(_sample_risk_result("TX-OTHER"))

        assert repo.count() == 4
        assert repo.count_for_asset("TX-TEST") == 3
        assert repo.count_for_asset("TX-OTHER") == 1

    def test_delete_for_asset(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)

        for _ in range(3):
            repo.insert(_sample_risk_result("TX-TEST"))
        repo.insert(_sample_risk_result("TX-OTHER"))

        deleted = repo.delete_for_asset("TX-TEST")
        assert deleted == 3
        assert repo.count_for_asset("TX-TEST") == 0
        assert repo.count_for_asset("TX-OTHER") == 1

    def test_all_risk_levels_roundtrip(self):
        conn = _fresh_db()
        repo = RiskResultRepository(conn)
        for level, score in [
            (RiskLevel.NORMAL, 20.0),
            (RiskLevel.WATCH, 50.0),
            (RiskLevel.HIGH, 75.0),
            (RiskLevel.CRITICAL, 90.0),
        ]:
            r = RiskResult(
                asset_id=f"TX-{level.value}",
                overall_risk=score,
                risk_level=level,
                components=ComponentScores(score, score, score, score, score),
                dominant_factor="sensor_health",
            )
            repo.insert(r)
            fetched = repo.get_latest(f"TX-{level.value}")
            assert fetched is not None
            assert fetched.risk_level == level


# ===========================================================================
# 7. Seeder
# ===========================================================================

class TestSeeder:

    def test_seeds_all_eight_demo_assets(self):
        conn = _fresh_db()
        inserted = seed_demo_assets(conn)
        assert inserted == 8

    def test_seeder_is_idempotent(self):
        conn = _fresh_db()
        seed_demo_assets(conn)
        second = seed_demo_assets(conn)
        assert second == 0

    def test_all_assets_retrievable_after_seed(self):
        conn = _fresh_db()
        seed_demo_assets(conn)
        asset_repo = AssetRepository(conn)
        for raw in ALL_ASSETS:
            assert asset_repo.exists(raw.metadata.asset_id), (
                f"Asset {raw.metadata.asset_id} not found after seeding"
            )

    def test_seeded_lifecycle_scalar_fields(self):
        conn = _fresh_db()
        seed_demo_assets(conn)

        repo = LifecycleRepository(conn)
        lc = repo.get("TX-001")
        assert lc is not None
        assert lc.state == LifecycleState.ACTIVE
        assert lc.age_years == pytest.approx(TX_001.degradation.age_years)
        assert lc.insulation_health_pct == pytest.approx(
            TX_001.degradation.insulation_health_pct
        )
        assert lc.failure_count_last_5yr == TX_001.incidents.failure_count_last_5yr

    def test_seeded_topology_retrievable(self):
        conn = _fresh_db()
        seed_demo_assets(conn)
        topo_repo = GridTopologyRepository(conn)
        for raw in ALL_ASSETS:
            topo = topo_repo.get(raw.metadata.asset_id)
            assert topo is not None
            assert topo.customers_served == raw.topology.customers_served

    def test_seed_total_counts(self):
        conn = _fresh_db()
        seed_demo_assets(conn)
        assert AssetRepository(conn).count() == 8
        assert LifecycleRepository(conn).count() == 8


# ===========================================================================
# 8. Integration — lifecycle bridge to risk scoring
# ===========================================================================

class TestIntegrationLifecycleBridge:
    """
    Verify that records round-tripped through the DB can be fed back into
    the normaliser and risk engine with the correct result bands.
    """

    @pytest.mark.parametrize("raw", ALL_ASSETS)
    def test_seeded_asset_lifecycle_bridges_to_correct_band(self, raw):
        conn = _fresh_db()
        seed_demo_assets(conn)

        repo = LifecycleRepository(conn)
        lc = repo.get(raw.metadata.asset_id)
        assert lc is not None

        # Build a minimal RawAssetRecord from stored fields + original telemetry/weather
        from data.raw_types import RawAssetRecord
        topo_repo = GridTopologyRepository(conn)
        topo = topo_repo.get(raw.metadata.asset_id)
        assert topo is not None

        reconstituted = RawAssetRecord(
            metadata=raw.metadata,
            telemetry=raw.telemetry,
            weather=raw.weather,
            incidents=lc.to_raw_incidents(),
            degradation=lc.to_raw_degradation(),
            topology=topo,
        )

        risk_inputs = normalise(reconstituted)
        result = score_asset(risk_inputs)
        # Risk level must match the documented demo band
        expected_bands = {
            "TX-001": RiskLevel.NORMAL,
            "TX-002": RiskLevel.NORMAL,
            "TX-003": RiskLevel.WATCH,
            "TX-004": RiskLevel.WATCH,
            "TX-005": RiskLevel.HIGH,
            "TX-006": RiskLevel.HIGH,
            "TX-007": RiskLevel.CRITICAL,
            "TX-008": RiskLevel.CRITICAL,
        }
        assert result.risk_level == expected_bands[raw.metadata.asset_id], (
            f"{raw.metadata.asset_id}: expected {expected_bands[raw.metadata.asset_id]}, "
            f"got {result.risk_level} (score={result.overall_risk})"
        )


# ===========================================================================
# 9. Lineage — apply_replacement → persist → retrieve chain
# ===========================================================================

class TestLineagePersistence:

    def test_replacement_lineage_survives_persistence(self):
        """
        apply_replacement produces a RetiredAssetRecord + successor.
        Both can be stored and retrieved; the bidirectional link is intact.
        """
        conn = _fresh_db()

        # Store the original asset in the registry so FK constraints pass
        from data.raw_types import AssetLocation, AssetMetadata
        asset_repo = AssetRepository(conn)
        original_meta = AssetMetadata(
            asset_id="TX-ORIG",
            asset_type="transformer",
            rated_kva=25_000.0,
            rated_voltage_kv=33.0,
            location=AssetLocation(51.5, -0.1, "Test Sub", "Test Region"),
        )
        successor_meta = AssetMetadata(
            asset_id="TX-SUCC",
            asset_type="transformer",
            rated_kva=25_000.0,
            rated_voltage_kv=33.0,
            location=AssetLocation(51.5, -0.1, "Test Sub", "Test Region"),
        )
        asset_repo.upsert(original_meta)
        asset_repo.upsert(successor_meta)

        # Build original record with some history
        original = AssetLifecycleRecord(
            asset_id="TX-ORIG",
            state=LifecycleState.ACTIVE,
            age_years=38.0,
            rated_lifespan_years=40.0,
            rated_kva=25_000.0,
            insulation_health_pct=20.0,
            cumulative_fault_events=8,
            maintenance_overdue_days=90,
            average_load_factor=0.75,
            failure_count_last_5yr=3,
            failures_caused_by_weather=1,
            last_failure_days_ago=15,
            repeat_fault_active=True,
            fault_history=[
                FaultEvent(
                    severity=FaultSeverity.MAJOR,
                    days_ago=15,
                    description="Winding insulation breakdown",
                ),
            ],
            maintenance_history=[
                MaintenanceEvent(days_ago=90, notes="Pre-replacement inspection"),
            ],
        )

        # Replace the asset
        event = ReplacementEvent(
            new_asset_id="TX-SUCC",
            new_commissioned_year=2025,
            reason="End of rated lifespan",
        )
        replacement_result = apply_replacement(original, event)

        # Persist both records
        lifecycle_repo = LifecycleRepository(conn)
        retired_repo = RetiredAssetRepository(conn)

        lifecycle_repo.upsert(replacement_result.successor)
        retired_repo.upsert(replacement_result.retired)

        # Retrieve and verify successor
        successor = lifecycle_repo.get("TX-SUCC")
        assert successor is not None
        assert successor.predecessor_asset_id == "TX-ORIG"
        assert successor.state == LifecycleState.ACTIVE
        assert successor.age_years == pytest.approx(0.0)      # clean state
        assert successor.cumulative_fault_events == 0          # clean state

        # Retrieve and verify retired record
        retired = retired_repo.get("TX-ORIG")
        assert retired is not None
        assert retired.successor_asset_id == "TX-SUCC"
        assert retired.age_at_retirement_years == pytest.approx(38.0)
        assert len(retired.fault_history) == 1
        assert retired.fault_history[0].description == "Winding insulation breakdown"
        assert len(retired.maintenance_history) == 1

        # Walk the lineage chain via get_by_successor
        predecessor = retired_repo.get_by_successor("TX-SUCC")
        assert predecessor is not None
        assert predecessor.asset_id == "TX-ORIG"

    def test_no_predecessor_for_original_asset(self):
        conn = _fresh_db()
        seed_demo_assets(conn)

        repo = LifecycleRepository(conn)
        lc = repo.get("TX-001")
        assert lc is not None
        assert lc.predecessor_asset_id is None

        retired_repo = RetiredAssetRepository(conn)
        assert retired_repo.get_by_successor("TX-001") is None


# ===========================================================================
# 10. Isolation
# ===========================================================================

class TestIsolation:

    def test_each_test_uses_separate_db(self):
        """Verify that fresh DBs really are independent (no shared state)."""
        conn_a = _fresh_db()
        conn_b = _fresh_db()

        AssetRepository(conn_a).upsert(TX_001.metadata)

        # conn_b must see nothing written to conn_a
        assert not AssetRepository(conn_b).exists("TX-001")
        assert AssetRepository(conn_a).exists("TX-001")

    def test_in_memory_db_is_empty_on_creation(self):
        conn = _fresh_db()
        assert AssetRepository(conn).count() == 0
        assert LifecycleRepository(conn).count() == 0
        assert RetiredAssetRepository(conn).count() == 0
        assert RiskResultRepository(conn).count() == 0
