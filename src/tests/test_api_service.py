"""Tests for the UI serve layer (src/api).

These tests verify that the dashboard serves the REAL risk-engine outputs —
no hardcoded display numbers — and that the briefing router stays grounded.
They use an in-memory database and the offline mock provider, so they need
no network, no credentials, and no running server.
"""

import sys
import os

# Pin the offline provider: GridState loads .env files, but explicit
# environment variables always win — tests must never hit the network.
os.environ["GRIDGUARD_LLM_PROVIDER"] = "mock"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.grid_service import GridState
from data.demo_assets import ALL_ASSETS
from normalisation.normaliser import normalise
from risk_engine.calculator import score_asset


def _state() -> GridState:
    return GridState(db_path=":memory:")


class TestServeLayerReflectsEngine:
    def test_asset_count_matches_demo_dataset(self):
        gs = _state()
        assert len(gs.assets) == len(ALL_ASSETS) == 8

    def test_served_scores_equal_engine_scores(self):
        gs = _state()
        for raw in ALL_ASSETS:
            expected = score_asset(normalise(raw))
            served = gs.get_asset(raw.metadata.asset_id)
            assert served is not None
            assert served["overall_risk"] == expected.overall_risk
            assert served["risk_level"] == expected.risk_level.value
            assert served["dominant_factor"] == expected.dominant_factor
            for comp in (
                "sensor_health",
                "weather_risk",
                "historical_failure",
                "asset_degradation",
                "grid_impact",
            ):
                assert served["components"][comp] == getattr(
                    expected.components, comp
                )

    def test_summary_counts_match_engine_levels(self):
        gs = _state()
        s = gs.summary()
        assert s["total"] == 8
        assert sum(s["counts"].values()) == 8
        # Engine ground truth for the demo set: 2 Normal / 2 Watch / 2 High / 2 Critical
        assert s["counts"] == {
            "Healthy": 2,
            "Monitoring": 2,
            "High": 2,
            "Critical": 2,
        }

    def test_maintenance_plan_is_risk_sorted(self):
        gs = _state()
        plan = gs.priorities()["maintenance_plan"]
        risks = [r["overall_risk"] for r in plan]
        assert risks == sorted(risks, reverse=True)
        assert plan[0]["asset_id"] == "TX-007"  # highest engine score
        assert plan[0]["recommended_action"] == "Inspect today"

    def test_asset_view_carries_raw_evidence(self):
        gs = _state()
        a = gs.get_asset("TX-007")
        assert a["sensors_raw"]["top_oil_temp_c"] == 94.0
        assert a["weather_raw"]["storm_warning_level"] == 3
        assert a["history"]["failure_count_last_5yr"] == 4
        assert a["lifecycle"]["state"] == "active"
        assert a["grid_impact"]["critical_facility_count"] == 3


class TestBriefingRouterGrounded:
    def test_why_question_returns_real_score(self):
        gs = _state()
        r = gs.answer_question("Why is TX-007 critical?")
        assert r["asset_ids"] == ["TX-007"]
        assert r["overall_risks"]["TX-007"] == 94.9
        assert "94.9" in r["text"]
        assert r["grounded"] is True

    def test_fleet_question_lists_ranked_assets(self):
        gs = _state()
        r = gs.answer_question("Which assets should we inspect today?")
        assert "TX-007" in r["text"]
        assert "TX-008" in r["text"]

    def test_unknown_asset_falls_back_to_fleet(self):
        gs = _state()
        r = gs.answer_question("What should we do?")
        assert r["text"]
        assert r["grounded"] is True
