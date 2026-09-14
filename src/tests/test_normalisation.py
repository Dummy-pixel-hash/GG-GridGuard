"""
Unit tests for the GridGuard normalisation layer.

Coverage
--------
  1. _linear_score helper — boundaries, inverted mode
  2. Sensor normalisation — per-channel, missing sensors, all-missing
  3. Weather normalisation — each dimension, storm boost, compound, cold stress
  4. Degradation normalisation — insulation inversion, clamping, overdue
  5. Validation — all invalid-input paths raise NormalisationError
  6. End-to-end normalise() — all 8 demo assets produce valid RiskInputs
  7. Demo assets route through the risk engine and land in expected bands
  8. Determinism — same record always produces the same RiskInputs

SYNTHETIC / DEMO DATA ONLY — no real utility data.
"""

from __future__ import annotations

import math
import copy

import pytest

from data.demo_assets import ALL_ASSETS, TX_001, TX_002, TX_003, TX_004, TX_005, TX_006, TX_007, TX_008
from data.raw_types import (
    AssetLocation,
    AssetMetadata,
    RawAssetRecord,
    RawDegradationRecord,
    RawGridTopology,
    RawIncidentRecord,
    RawSensorTelemetry,
    RawWeatherObservation,
)
from normalisation.normaliser import NormalisationError, _linear_score, normalise
from normalisation.thresholds import DEFAULT_SENSOR_THRESHOLDS, DEFAULT_WEATHER_THRESHOLDS, SensorThresholds
from risk_engine import RiskLevel, score_asset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_meta(asset_id: str = "TX-TEST") -> AssetMetadata:
    return AssetMetadata(
        asset_id=asset_id,
        asset_type="transformer",
        rated_kva=10_000,
        rated_voltage_kv=33.0,
        rated_lifespan_years=40.0,
        commissioned_year=2010,
        location=AssetLocation(latitude=51.5, longitude=-0.1),
    )


def _minimal_record(asset_id: str = "TX-TEST") -> RawAssetRecord:
    """Fully valid minimal record with all sensor values present."""
    return RawAssetRecord(
        metadata=_minimal_meta(asset_id),
        telemetry=RawSensorTelemetry(
            top_oil_temp_c=55.0,
            winding_hot_spot_c=78.0,
            vibration_mm_s=1.0,
            oil_dielectric_kv=70.0,
            partial_discharge_pc=100.0,
            load_factor_current=0.5,
        ),
        weather=RawWeatherObservation(
            max_temp_c=25.0, min_temp_c=10.0,
            precipitation_mm=0.0, wind_speed_max_kmh=0.0,
            storm_warning_level=0,
        ),
        incidents=RawIncidentRecord(),
        degradation=RawDegradationRecord(
            age_years=10.0, average_load_factor=0.5,
        ),
        topology=RawGridTopology(customers_served=1000, peak_load_mw=1.0),
    )


# ===========================================================================
# 1. _linear_score helper
# ===========================================================================

class TestLinearScore:

    def test_at_healthy_value_returns_zero(self):
        assert _linear_score(55.0, 55.0, 98.0) == pytest.approx(0.0)

    def test_at_alarm_value_returns_100(self):
        assert _linear_score(98.0, 55.0, 98.0) == pytest.approx(100.0)

    def test_midpoint_returns_50(self):
        assert _linear_score(76.5, 55.0, 98.0) == pytest.approx(50.0, rel=1e-3)

    def test_below_healthy_clamped_to_zero(self):
        assert _linear_score(30.0, 55.0, 98.0) == 0.0

    def test_above_alarm_clamped_to_100(self):
        assert _linear_score(200.0, 55.0, 98.0) == 100.0

    def test_inverted_at_healthy_returns_zero(self):
        # oil kV: 70 kV = healthy → 0
        assert _linear_score(70.0, 70.0, 30.0, inverted=True) == pytest.approx(0.0)

    def test_inverted_at_alarm_returns_100(self):
        # 30 kV = alarm → 100
        assert _linear_score(30.0, 70.0, 30.0, inverted=True) == pytest.approx(100.0)

    def test_inverted_above_healthy_clamped_to_zero(self):
        # Very high kV (very healthy oil) → 0
        assert _linear_score(90.0, 70.0, 30.0, inverted=True) == 0.0

    def test_inverted_below_alarm_clamped_to_100(self):
        # Severely degraded oil → 100
        assert _linear_score(10.0, 70.0, 30.0, inverted=True) == 100.0

    def test_degenerate_thresholds_equal_healthy_alarm(self):
        # When span == 0: raw <= healthy → 0
        assert _linear_score(5.0, 5.0, 5.0) == 0.0

    def test_degenerate_thresholds_above_healthy(self):
        assert _linear_score(6.0, 5.0, 5.0) == 100.0


# ===========================================================================
# 2. Sensor normalisation
# ===========================================================================

class TestSensorNormalisation:

    def test_all_nominal_sensors_score_near_zero(self):
        r = _minimal_record()
        # All sensors at their healthy thresholds → score near 0
        ri = normalise(r)
        assert ri.sensors.temperature_score == pytest.approx(0.0)
        assert ri.sensors.vibration_score == pytest.approx(0.0)
        assert ri.sensors.oil_quality_score == pytest.approx(0.0)
        assert ri.sensors.partial_discharge_score == pytest.approx(0.0)
        assert ri.sensors.missing_sensor_ratio == 0.0

    def test_all_alarm_sensors_score_100(self):
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry(
            top_oil_temp_c=98.0,
            winding_hot_spot_c=128.0,
            vibration_mm_s=4.5,
            oil_dielectric_kv=30.0,
            partial_discharge_pc=1_000.0,
        )
        ri = normalise(r)
        assert ri.sensors.temperature_score == pytest.approx(100.0)
        assert ri.sensors.vibration_score == pytest.approx(100.0)
        assert ri.sensors.oil_quality_score == pytest.approx(100.0)
        assert ri.sensors.partial_discharge_score == pytest.approx(100.0)
        assert ri.sensors.missing_sensor_ratio == 0.0

    def test_temperature_uses_worst_of_two_sources(self):
        """Hot-spot at alarm but top-oil nominal → temperature_score = 100."""
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry(
            top_oil_temp_c=55.0,    # nominal → 0
            winding_hot_spot_c=128.0,  # alarm → 100
            vibration_mm_s=1.0,
            oil_dielectric_kv=70.0,
            partial_discharge_pc=100.0,
        )
        ri = normalise(r)
        assert ri.sensors.temperature_score == pytest.approx(100.0)

    def test_missing_top_oil_falls_back_to_hot_spot(self):
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry(
            top_oil_temp_c=None,   # missing
            winding_hot_spot_c=78.0,  # healthy
            vibration_mm_s=1.0,
            oil_dielectric_kv=70.0,
            partial_discharge_pc=100.0,
        )
        ri = normalise(r)
        assert ri.sensors.temperature_score == pytest.approx(0.0)
        assert ri.sensors.missing_sensor_ratio == 0.0  # hot-spot covers temperature

    def test_both_temperature_sensors_missing_increments_ratio(self):
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry(
            top_oil_temp_c=None,
            winding_hot_spot_c=None,
            vibration_mm_s=1.0,
            oil_dielectric_kv=70.0,
            partial_discharge_pc=100.0,
        )
        ri = normalise(r)
        assert ri.sensors.missing_sensor_ratio == pytest.approx(1 / 4)
        assert ri.sensors.temperature_score == 0.0  # defaulted to 0

    def test_all_sensors_missing(self):
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry()  # all None
        ri = normalise(r)
        assert ri.sensors.missing_sensor_ratio == 1.0
        assert ri.sensors.temperature_score == 0.0
        assert ri.sensors.vibration_score == 0.0
        assert ri.sensors.oil_quality_score == 0.0
        assert ri.sensors.partial_discharge_score == 0.0

    def test_three_sensors_missing_ratio_is_0_75(self):
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry(
            top_oil_temp_c=55.0,   # present
            winding_hot_spot_c=None,
            vibration_mm_s=None,
            oil_dielectric_kv=None,
            partial_discharge_pc=None,
        )
        ri = normalise(r)
        assert ri.sensors.missing_sensor_ratio == pytest.approx(3 / 4)

    def test_sensor_scores_clamped_at_100(self):
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry(
            top_oil_temp_c=200.0,     # way above alarm
            winding_hot_spot_c=300.0,
            vibration_mm_s=100.0,
            oil_dielectric_kv=0.0,
            partial_discharge_pc=50_000.0,
        )
        ri = normalise(r)
        assert ri.sensors.temperature_score <= 100.0
        assert ri.sensors.vibration_score <= 100.0
        assert ri.sensors.oil_quality_score <= 100.0
        assert ri.sensors.partial_discharge_score <= 100.0

    def test_sensor_scores_clamped_at_zero(self):
        r = _minimal_record()
        r.telemetry = RawSensorTelemetry(
            top_oil_temp_c=10.0,      # well below healthy
            winding_hot_spot_c=20.0,
            vibration_mm_s=0.0,
            oil_dielectric_kv=200.0,  # extremely good oil
            partial_discharge_pc=0.0,
        )
        ri = normalise(r)
        assert ri.sensors.temperature_score >= 0.0
        assert ri.sensors.vibration_score == 0.0
        assert ri.sensors.oil_quality_score == 0.0
        assert ri.sensors.partial_discharge_score == 0.0

    def test_custom_sensor_thresholds_applied(self):
        """Tighter alarm threshold should produce a higher score for the same raw value."""
        r = _minimal_record()
        r.telemetry.top_oil_temp_c = 70.0  # midpoint of default range

        default_ri = normalise(r)

        tight = SensorThresholds(top_oil_temp_alarm_c=70.0)  # alarm at 70 °C
        tight_ri = normalise(r, sensor_thresholds=tight)

        assert tight_ri.sensors.temperature_score > default_ri.sensors.temperature_score


# ===========================================================================
# 3. Weather normalisation
# ===========================================================================

class TestWeatherNormalisation:

    def test_calm_conditions_score_zero(self):
        r = _minimal_record()
        # min_temp must be AT or above the neutral threshold (25 °C) to avoid
        # cold-stress; max_temp AT the neutral threshold to avoid heat stress.
        r.weather = RawWeatherObservation(
            max_temp_c=25.0, min_temp_c=25.0,
            precipitation_mm=0.0, wind_speed_max_kmh=0.0,
            storm_warning_level=0,
        )
        ri = normalise(r)
        assert ri.weather.temperature_stress_score == 0.0
        assert ri.weather.precipitation_score == 0.0
        assert ri.weather.wind_storm_score == 0.0

    def test_extreme_heat_scores_100(self):
        r = _minimal_record()
        r.weather.max_temp_c = 45.0  # alarm threshold
        ri = normalise(r)
        assert ri.weather.temperature_stress_score == pytest.approx(100.0)

    def test_extreme_heat_above_alarm_clamped(self):
        r = _minimal_record()
        r.weather.max_temp_c = 60.0  # above alarm
        ri = normalise(r)
        assert ri.weather.temperature_stress_score <= 100.0

    def test_cold_stress_below_alarm(self):
        r = _minimal_record()
        r.weather.min_temp_c = -15.0  # cold alarm threshold
        ri = normalise(r)
        assert ri.weather.temperature_stress_score == pytest.approx(100.0)

    def test_precipitation_at_alarm_is_100(self):
        r = _minimal_record()
        r.weather.precipitation_mm = 100.0
        ri = normalise(r)
        assert ri.weather.precipitation_score == pytest.approx(100.0)

    def test_wind_at_alarm_is_100_without_storm_boost(self):
        r = _minimal_record()
        r.weather.wind_speed_max_kmh = 120.0
        r.weather.storm_warning_level = 0
        ri = normalise(r)
        assert ri.weather.wind_storm_score == pytest.approx(100.0)

    def test_storm_level_3_boosts_wind_score(self):
        r = _minimal_record()
        r.weather.wind_speed_max_kmh = 50.0   # moderate wind
        r.weather.storm_warning_level = 0
        ri_no_storm = normalise(r)

        r.weather.storm_warning_level = 3
        ri_storm = normalise(r)

        assert ri_storm.weather.wind_storm_score > ri_no_storm.weather.wind_storm_score

    def test_storm_level_3_caps_at_100(self):
        r = _minimal_record()
        r.weather.wind_speed_max_kmh = 120.0
        r.weather.storm_warning_level = 3
        ri = normalise(r)
        assert ri.weather.wind_storm_score <= 100.0

    def test_forecast_hours_preserved(self):
        r = _minimal_record()
        r.weather.forecast_hours = 48
        ri = normalise(r)
        assert ri.weather.forecast_hours == 48

    def test_all_weather_scores_in_range(self):
        for asset in ALL_ASSETS:
            ri = normalise(asset)
            assert 0.0 <= ri.weather.temperature_stress_score <= 100.0
            assert 0.0 <= ri.weather.precipitation_score <= 100.0
            assert 0.0 <= ri.weather.wind_storm_score <= 100.0


# ===========================================================================
# 4. Degradation normalisation
# ===========================================================================

class TestDegradationNormalisation:

    def test_insulation_100pct_healthy_maps_to_score_0(self):
        r = _minimal_record()
        r.degradation.insulation_health_pct = 100.0
        ri = normalise(r)
        assert ri.degradation.insulation_health_score == pytest.approx(0.0)

    def test_insulation_0pct_healthy_maps_to_score_100(self):
        r = _minimal_record()
        r.degradation.insulation_health_pct = 0.0
        ri = normalise(r)
        assert ri.degradation.insulation_health_score == pytest.approx(100.0)

    def test_insulation_50pct_maps_to_score_50(self):
        r = _minimal_record()
        r.degradation.insulation_health_pct = 50.0
        ri = normalise(r)
        assert ri.degradation.insulation_health_score == pytest.approx(50.0)

    def test_insulation_none_passes_through_as_none(self):
        r = _minimal_record()
        r.degradation.insulation_health_pct = None
        ri = normalise(r)
        assert ri.degradation.insulation_health_score is None

    def test_age_years_passed_through(self):
        r = _minimal_record()
        r.degradation.age_years = 25.0
        ri = normalise(r)
        assert ri.degradation.age_years == 25.0

    def test_rated_lifespan_from_metadata(self):
        r = _minimal_record()
        r.metadata.rated_lifespan_years = 35.0
        ri = normalise(r)
        assert ri.degradation.rated_lifespan_years == 35.0

    def test_negative_maintenance_overdue_clamped_to_zero(self):
        r = _minimal_record()
        r.degradation.maintenance_overdue_days = -30  # performed early
        ri = normalise(r)
        assert ri.degradation.maintenance_overdue_days == 0

    def test_load_factor_out_of_range_raises(self):
        """average_load_factor > 1.0 is structurally invalid — validation rejects it."""
        r = _minimal_record()
        r.degradation.average_load_factor = 1.5
        with pytest.raises(NormalisationError, match="average_load_factor"):
            normalise(r)

    def test_load_factor_exactly_1_is_valid(self):
        r = _minimal_record()
        r.degradation.average_load_factor = 1.0
        ri = normalise(r)
        assert ri.degradation.load_factor_avg == pytest.approx(1.0)


# ===========================================================================
# 5. Validation — all invalid-input paths
# ===========================================================================

class TestValidation:

    def test_empty_asset_id_raises(self):
        r = _minimal_record()
        r.metadata.asset_id = ""
        with pytest.raises(NormalisationError, match="asset_id"):
            normalise(r)

    def test_whitespace_asset_id_raises(self):
        r = _minimal_record()
        r.metadata.asset_id = "   "
        with pytest.raises(NormalisationError, match="asset_id"):
            normalise(r)

    def test_zero_lifespan_raises(self):
        r = _minimal_record()
        r.metadata.rated_lifespan_years = 0.0
        with pytest.raises(NormalisationError, match="rated_lifespan_years"):
            normalise(r)

    def test_negative_lifespan_raises(self):
        r = _minimal_record()
        r.metadata.rated_lifespan_years = -5.0
        with pytest.raises(NormalisationError, match="rated_lifespan_years"):
            normalise(r)

    def test_negative_age_raises(self):
        r = _minimal_record()
        r.degradation.age_years = -1.0
        with pytest.raises(NormalisationError, match="age_years"):
            normalise(r)

    def test_insulation_pct_above_100_raises(self):
        r = _minimal_record()
        r.degradation.insulation_health_pct = 101.0
        with pytest.raises(NormalisationError, match="insulation_health_pct"):
            normalise(r)

    def test_insulation_pct_below_0_raises(self):
        r = _minimal_record()
        r.degradation.insulation_health_pct = -1.0
        with pytest.raises(NormalisationError, match="insulation_health_pct"):
            normalise(r)

    def test_average_load_factor_above_1_raises(self):
        r = _minimal_record()
        r.degradation.average_load_factor = 1.1
        with pytest.raises(NormalisationError, match="average_load_factor"):
            normalise(r)

    def test_average_load_factor_below_0_raises(self):
        r = _minimal_record()
        r.degradation.average_load_factor = -0.1
        with pytest.raises(NormalisationError, match="average_load_factor"):
            normalise(r)

    def test_weather_caused_exceeds_total_raises(self):
        r = _minimal_record()
        r.incidents.failure_count_last_5yr = 1
        r.incidents.failures_caused_by_weather = 2
        with pytest.raises(NormalisationError, match="failures_caused_by_weather"):
            normalise(r)

    def test_negative_failure_count_raises(self):
        r = _minimal_record()
        r.incidents.failure_count_last_5yr = -1
        with pytest.raises(NormalisationError, match="failure_count_last_5yr"):
            normalise(r)

    def test_negative_last_failure_days_raises(self):
        r = _minimal_record()
        r.incidents.failure_count_last_5yr = 1
        r.incidents.last_failure_days_ago = -5
        with pytest.raises(NormalisationError, match="last_failure_days_ago"):
            normalise(r)

    def test_negative_customers_served_raises(self):
        r = _minimal_record()
        r.topology.customers_served = -1
        with pytest.raises(NormalisationError, match="customers_served"):
            normalise(r)

    def test_negative_peak_load_raises(self):
        r = _minimal_record()
        r.topology.peak_load_mw = -5.0
        with pytest.raises(NormalisationError, match="peak_load_mw"):
            normalise(r)

    def test_storm_level_above_3_raises(self):
        r = _minimal_record()
        r.weather.storm_warning_level = 4
        with pytest.raises(NormalisationError, match="storm_warning_level"):
            normalise(r)

    def test_storm_level_below_0_raises(self):
        r = _minimal_record()
        r.weather.storm_warning_level = -1
        with pytest.raises(NormalisationError, match="storm_warning_level"):
            normalise(r)

    def test_nan_precipitation_raises(self):
        r = _minimal_record()
        r.weather.precipitation_mm = math.nan
        with pytest.raises(NormalisationError, match="precipitation_mm"):
            normalise(r)

    def test_negative_precipitation_raises(self):
        r = _minimal_record()
        r.weather.precipitation_mm = -1.0
        with pytest.raises(NormalisationError, match="precipitation_mm"):
            normalise(r)

    def test_negative_wind_speed_raises(self):
        r = _minimal_record()
        r.weather.wind_speed_max_kmh = -10.0
        with pytest.raises(NormalisationError, match="wind_speed_max_kmh"):
            normalise(r)

    def test_negative_downstream_count_raises(self):
        r = _minimal_record()
        r.topology.downstream_asset_count = -1
        with pytest.raises(NormalisationError, match="downstream_asset_count"):
            normalise(r)

    def test_negative_critical_facility_count_raises(self):
        r = _minimal_record()
        r.topology.critical_facility_count = -1
        with pytest.raises(NormalisationError, match="critical_facility_count"):
            normalise(r)

    def test_valid_record_does_not_raise(self):
        r = _minimal_record()
        ri = normalise(r)  # must not raise
        assert ri.asset_id == "TX-TEST"


# ===========================================================================
# 6. End-to-end normalise() — all demo assets produce valid RiskInputs
# ===========================================================================

class TestNormaliseAllDemoAssets:

    @pytest.mark.parametrize("asset", ALL_ASSETS, ids=lambda a: a.metadata.asset_id)
    def test_produces_valid_risk_inputs(self, asset):
        ri = normalise(asset)
        assert ri.asset_id == asset.metadata.asset_id
        # All scores in [0, 100]
        assert 0.0 <= ri.sensors.temperature_score <= 100.0
        assert 0.0 <= ri.sensors.vibration_score <= 100.0
        assert 0.0 <= ri.sensors.oil_quality_score <= 100.0
        assert 0.0 <= ri.sensors.partial_discharge_score <= 100.0
        assert 0.0 <= ri.sensors.missing_sensor_ratio <= 1.0
        assert 0.0 <= ri.weather.temperature_stress_score <= 100.0
        assert 0.0 <= ri.weather.precipitation_score <= 100.0
        assert 0.0 <= ri.weather.wind_storm_score <= 100.0

    @pytest.mark.parametrize("asset", ALL_ASSETS, ids=lambda a: a.metadata.asset_id)
    def test_asset_id_preserved(self, asset):
        ri = normalise(asset)
        assert ri.asset_id == asset.metadata.asset_id

    @pytest.mark.parametrize("asset", ALL_ASSETS, ids=lambda a: a.metadata.asset_id)
    def test_grid_impact_fields_preserved(self, asset):
        ri = normalise(asset)
        assert ri.grid_impact.customers_served == asset.topology.customers_served
        assert ri.grid_impact.critical_facility_count == asset.topology.critical_facility_count
        assert ri.grid_impact.has_redundant_path == asset.topology.has_n1_redundancy


# ===========================================================================
# 7. Demo assets → risk engine → expected bands
# ===========================================================================

class TestDemoAssetRiskBands:
    """
    End-to-end: raw demo data → normalise → score_asset → expected risk band.
    These serve as regression tests for the full pipeline.
    """

    def test_tx001_is_normal(self):
        ri = normalise(TX_001)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.NORMAL, (
            f"TX-001 expected Normal, got {result.risk_level} (overall={result.overall_risk})"
        )

    def test_tx002_is_normal(self):
        ri = normalise(TX_002)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.NORMAL, (
            f"TX-002 expected Normal, got {result.risk_level} (overall={result.overall_risk})"
        )

    def test_tx003_is_watch(self):
        ri = normalise(TX_003)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.WATCH, (
            f"TX-003 expected Watch, got {result.risk_level} (overall={result.overall_risk})"
        )

    def test_tx004_is_watch(self):
        ri = normalise(TX_004)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.WATCH, (
            f"TX-004 expected Watch, got {result.risk_level} (overall={result.overall_risk})"
        )

    def test_tx005_is_high(self):
        ri = normalise(TX_005)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.HIGH, (
            f"TX-005 expected High, got {result.risk_level} (overall={result.overall_risk})"
        )

    def test_tx006_is_high(self):
        ri = normalise(TX_006)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.HIGH, (
            f"TX-006 expected High, got {result.risk_level} (overall={result.overall_risk})"
        )

    def test_tx007_is_critical(self):
        ri = normalise(TX_007)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.CRITICAL, (
            f"TX-007 expected Critical, got {result.risk_level} (overall={result.overall_risk})"
        )

    def test_tx008_is_critical(self):
        ri = normalise(TX_008)
        result = score_asset(ri)
        assert result.risk_level == RiskLevel.CRITICAL, (
            f"TX-008 expected Critical, got {result.risk_level} (overall={result.overall_risk})"
        )


# ===========================================================================
# 8. Determinism
# ===========================================================================

class TestDeterminism:

    @pytest.mark.parametrize("asset", ALL_ASSETS, ids=lambda a: a.metadata.asset_id)
    def test_normalise_is_deterministic(self, asset):
        ri1 = normalise(asset)
        ri2 = normalise(asset)
        assert ri1.sensors.temperature_score == ri2.sensors.temperature_score
        assert ri1.sensors.vibration_score == ri2.sensors.vibration_score
        assert ri1.sensors.oil_quality_score == ri2.sensors.oil_quality_score
        assert ri1.sensors.partial_discharge_score == ri2.sensors.partial_discharge_score
        assert ri1.sensors.missing_sensor_ratio == ri2.sensors.missing_sensor_ratio
        assert ri1.weather.temperature_stress_score == ri2.weather.temperature_stress_score
        assert ri1.weather.precipitation_score == ri2.weather.precipitation_score
        assert ri1.weather.wind_storm_score == ri2.weather.wind_storm_score

    @pytest.mark.parametrize("asset", ALL_ASSETS, ids=lambda a: a.metadata.asset_id)
    def test_full_pipeline_is_deterministic(self, asset):
        r1 = score_asset(normalise(asset))
        r2 = score_asset(normalise(asset))
        assert r1.overall_risk == r2.overall_risk
        assert r1.risk_level == r2.risk_level
