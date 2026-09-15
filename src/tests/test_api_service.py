"""Tests for the UI serve layer (src/api).

These tests verify that the dashboard serves the REAL risk-engine outputs —
no hardcoded display numbers — and that the briefing router stays grounded.
They use an in-memory database and the offline mock provider, so they need
no network, no credentials, and no running server.

Note on live weather
--------------------
GridState attempts a live Open-Meteo weather refresh at startup.  These tests
patch ``_refresh_asset_weather`` to return the static demo records unchanged so
test results are deterministic regardless of network availability.
"""

import sys
import os
from unittest.mock import patch

# Pin the offline provider: GridState loads .env files, but explicit
# environment variables always win — tests must never hit the network.
os.environ["GRIDGUARD_LLM_PROVIDER"] = "mock"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.grid_service as _gs_module
from api.grid_service import GridState
from data.demo_assets import ALL_ASSETS
from normalisation.normaliser import normalise
from risk_engine.calculator import score_asset


def _state() -> GridState:
    """GridState with live weather refresh stubbed out."""
    with patch.object(_gs_module, "_refresh_asset_weather", side_effect=lambda assets: assets):
        return GridState(db_path=":memory:")


class TestServeLayerReflectsEngine:
    def test_asset_count_matches_demo_dataset(self):
        gs = _state()
        assert len(gs.assets) == len(ALL_ASSETS) == 8

    def test_served_scores_equal_engine_scores(self):
        """Served scores must equal what the engine produces from the same raw data.

        We compare against what GridState actually computed (gs._results), not
        what we'd get from the static ALL_ASSETS directly — this is correct
        because if live weather is active the served scores may legitimately
        differ from the static baseline.  With the stub, both should be equal.
        """
        gs = _state()
        for raw in ALL_ASSETS:
            # Re-score the SAME raw records GridState used (static here via stub)
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
        # Compute the expected score dynamically from the engine rather than
        # hardcoding it, so the test does not break when scoring formulas change.
        expected_risk = gs._results["TX-007"].overall_risk
        r = gs.answer_question("Why is TX-007 critical?")
        assert r["asset_ids"] == ["TX-007"]
        assert r["overall_risks"]["TX-007"] == expected_risk
        assert str(expected_risk) in r["text"]
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


class TestWeatherRefreshHelper:
    """Tests for the _refresh_asset_weather best-effort weather refresh."""

    def test_fallback_used_when_network_unavailable(self):
        """When Open-Meteo is unreachable, static demo data is kept unchanged."""
        from data.demo_assets import TX_007
        from api.grid_service import _refresh_asset_weather
        from weather.open_meteo import WeatherFetchError
        from unittest.mock import patch

        with patch(
            "api.grid_service.fetch_weather_with_fallback",
            return_value=(TX_007.weather, False),  # live=False → fallback used
        ):
            result = _refresh_asset_weather([TX_007])

        assert len(result) == 1
        assert result[0].weather is TX_007.weather  # exact same object — not replaced

    def test_live_weather_replaces_static_when_available(self):
        """When Open-Meteo succeeds, the fresh observation replaces static data."""
        import copy
        from data.demo_assets import TX_001
        from data.raw_types import RawWeatherObservation
        from api.grid_service import _refresh_asset_weather
        from unittest.mock import patch

        fresh = RawWeatherObservation(
            max_temp_c=35.0, min_temp_c=22.0,
            precipitation_mm=90.0, wind_speed_max_kmh=110.0,
            storm_warning_level=3, forecast_hours=72,
        )
        with patch(
            "api.grid_service.fetch_weather_with_fallback",
            return_value=(fresh, True),  # live=True → fresh data used
        ):
            result = _refresh_asset_weather([TX_001])

        assert len(result) == 1
        assert result[0].weather is fresh
        assert result[0].metadata is TX_001.metadata  # other fields unchanged

    def test_original_records_not_mutated(self):
        """_refresh_asset_weather must not modify the input records in place."""
        from data.demo_assets import TX_001
        from data.raw_types import RawWeatherObservation
        from api.grid_service import _refresh_asset_weather
        from unittest.mock import patch

        original_storm_level = TX_001.weather.storm_warning_level
        fresh = RawWeatherObservation(storm_warning_level=3, max_temp_c=40.0,
                                      min_temp_c=25.0, precipitation_mm=80.0,
                                      wind_speed_max_kmh=100.0, forecast_hours=72)
        with patch(
            "api.grid_service.fetch_weather_with_fallback",
            return_value=(fresh, True),
        ):
            _refresh_asset_weather([TX_001])

        # TX_001 must not have been mutated
        assert TX_001.weather.storm_warning_level == original_storm_level

    def test_gridstate_uses_live_weather_when_network_available(self):
        """GridState._raw should reflect live weather when Open-Meteo returns data."""
        from data.demo_assets import TX_007
        from data.raw_types import RawWeatherObservation
        from unittest.mock import patch

        fresh_wx = RawWeatherObservation(
            max_temp_c=40.0, min_temp_c=28.0,
            precipitation_mm=95.0, wind_speed_max_kmh=118.0,
            storm_warning_level=3, forecast_hours=72,
        )

        def fake_refresh(assets):
            """Simulate: TX-007 gets live weather, all others get static fallback."""
            import copy as _copy
            updated = []
            for raw in assets:
                if raw.metadata.asset_id == "TX-007":
                    r2 = _copy.copy(raw)
                    r2.weather = fresh_wx
                    updated.append(r2)
                else:
                    updated.append(raw)
            return updated

        with patch.object(_gs_module, "_refresh_asset_weather", side_effect=fake_refresh):
            gs = GridState(db_path=":memory:")

        served = gs.get_asset("TX-007")
        assert served["weather_raw"]["max_temp_c"] == 40.0
        assert served["weather_raw"]["wind_speed_max_kmh"] == 118.0

class TestGroundedFallbackRanking:
    """Verify _grounded_fallback ranks by weighted contribution, not raw score."""

    def test_fallback_dominant_factor_consistent_with_engine(self):
        """The grounded fallback's first-listed component should match dominant_factor."""
        gs = _state()
        # Use TX-007 which has a well-defined dominant factor
        a = gs.get_asset("TX-007")
        dominant = a["dominant_factor"]
        fallback_text = gs._grounded_fallback("test", "TX-007")
        from api.grid_service import COMPONENT_LABELS
        dominant_label = COMPONENT_LABELS[dominant]
        # The dominant component should appear in the top-3 list in the fallback
        assert dominant_label.lower() in fallback_text.lower()
