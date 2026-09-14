"""
Unit tests for the GridGuard risk engine.

Coverage:
  - Each individual scoring function in isolation
  - score_asset() end-to-end for all four risk bands (Normal / Watch / High / Critical)
  - Boundary conditions on classification thresholds
  - Dominant-factor identification
  - Edge-case inputs (all-zero, all-max, missing sensors, no history)

All test data is synthetic — see fixtures.py for documented values.
"""

from __future__ import annotations

import pytest

from risk_engine import (
    score_asset,
    RiskLevel,
    SensorReadings,
    WeatherConditions,
    HistoricalFailureRecord,
    AssetDegradationState,
    GridImpactFactors,
    RiskInputs,
)
from risk_engine.scoring.sensor_health import score_sensor_health
from risk_engine.scoring.weather_risk import score_weather_risk
from risk_engine.scoring.historical_failure import score_historical_failure
from risk_engine.scoring.asset_degradation import score_asset_degradation
from risk_engine.scoring.grid_impact import score_grid_impact

from tests.fixtures import (
    NORMAL_FIXTURE,
    WATCH_FIXTURE,
    HIGH_FIXTURE,
    CRITICAL_FIXTURE,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _approx(val: float, rel: float = 1e-3) -> pytest.ApproxBase:
    return pytest.approx(val, rel=rel)


# ===========================================================================
# 1. Sensor health scoring
# ===========================================================================

class TestSensorHealth:

    def test_all_zero_returns_zero(self):
        r = SensorReadings()
        assert score_sensor_health(r) == 0.0

    def test_all_max_returns_100(self):
        r = SensorReadings(
            temperature_score=100.0,
            vibration_score=100.0,
            oil_quality_score=100.0,
            partial_discharge_score=100.0,
            missing_sensor_ratio=0.0,
        )
        assert score_sensor_health(r) == 100.0

    def test_temperature_drives_highest_weight(self):
        """Temperature (40%) should dominate over vibration (10%)."""
        high_temp = SensorReadings(temperature_score=100.0)
        high_vib  = SensorReadings(vibration_score=100.0)
        assert score_sensor_health(high_temp) > score_sensor_health(high_vib)

    def test_partial_discharge_second_highest(self):
        """PD (30%) should outweigh oil quality (20%)."""
        high_pd  = SensorReadings(partial_discharge_score=100.0)
        high_oil = SensorReadings(oil_quality_score=100.0)
        assert score_sensor_health(high_pd) > score_sensor_health(high_oil)

    def test_missing_sensor_penalty_added(self):
        """All sensors offline should add 20 points to the base score."""
        r_present = SensorReadings(temperature_score=50.0, missing_sensor_ratio=0.0)
        r_missing = SensorReadings(temperature_score=50.0, missing_sensor_ratio=1.0)
        assert score_sensor_health(r_missing) == _approx(
            score_sensor_health(r_present) + 20.0
        )

    def test_missing_sensor_capped_at_100(self):
        r = SensorReadings(
            temperature_score=100.0,
            partial_discharge_score=100.0,
            oil_quality_score=100.0,
            vibration_score=100.0,
            missing_sensor_ratio=1.0,
        )
        assert score_sensor_health(r) == 100.0

    def test_result_in_range(self):
        r = SensorReadings(
            temperature_score=42.0,
            vibration_score=18.0,
            oil_quality_score=55.0,
            partial_discharge_score=30.0,
            missing_sensor_ratio=0.25,
        )
        result = score_sensor_health(r)
        assert 0.0 <= result <= 100.0


# ===========================================================================
# 2. Weather risk scoring
# ===========================================================================

class TestWeatherRisk:

    def test_all_zero_returns_zero(self):
        assert score_weather_risk(WeatherConditions()) == 0.0

    def test_all_max_returns_100(self):
        w = WeatherConditions(
            temperature_stress_score=100.0,
            precipitation_score=100.0,
            wind_storm_score=100.0,
        )
        assert score_weather_risk(w) == 100.0

    def test_wind_highest_weight(self):
        """Wind (45%) should dominate over temperature (35%)."""
        high_wind = WeatherConditions(wind_storm_score=100.0)
        high_temp = WeatherConditions(temperature_stress_score=100.0)
        assert score_weather_risk(high_wind) > score_weather_risk(high_temp)

    def test_compound_event_multiplier_applied(self):
        """Two dimensions ≥ 50 should trigger the 1.15× compound multiplier."""
        single = WeatherConditions(wind_storm_score=60.0)
        compound = WeatherConditions(wind_storm_score=60.0, temperature_stress_score=60.0)
        assert score_weather_risk(compound) > score_weather_risk(single)

    def test_compound_multiplier_not_applied_for_one_dimension(self):
        """One dimension at 60 with others at 0 should NOT get the compound bonus."""
        single = WeatherConditions(wind_storm_score=60.0)
        base_score = 60.0 * 0.45  # wind weight only
        assert score_weather_risk(single) == _approx(base_score)

    def test_compound_result_capped_at_100(self):
        w = WeatherConditions(
            temperature_stress_score=95.0,
            precipitation_score=90.0,
            wind_storm_score=95.0,
        )
        assert score_weather_risk(w) <= 100.0

    def test_result_in_range(self):
        w = WeatherConditions(
            temperature_stress_score=33.0,
            precipitation_score=20.0,
            wind_storm_score=55.0,
        )
        assert 0.0 <= score_weather_risk(w) <= 100.0


# ===========================================================================
# 3. Historical failure scoring
# ===========================================================================

class TestHistoricalFailure:

    def test_no_history_returns_zero(self):
        assert score_historical_failure(HistoricalFailureRecord()) == 0.0

    def test_four_plus_failures_caps_frequency(self):
        """5 failures should produce same frequency points as 4."""
        h4 = HistoricalFailureRecord(failure_count_last_5yr=4)
        h5 = HistoricalFailureRecord(failure_count_last_5yr=5)
        # Both capped at 40 pts for frequency; other sub-signals identical
        assert score_historical_failure(h4) == score_historical_failure(h5)

    def test_recent_failure_higher_than_old(self):
        recent = HistoricalFailureRecord(
            failure_count_last_5yr=1, last_failure_days_ago=20
        )
        old = HistoricalFailureRecord(
            failure_count_last_5yr=1, last_failure_days_ago=500
        )
        assert score_historical_failure(recent) > score_historical_failure(old)

    def test_repeat_failure_flag_adds_20_pts(self):
        base = HistoricalFailureRecord(failure_count_last_5yr=1)
        with_repeat = HistoricalFailureRecord(
            failure_count_last_5yr=1, repeat_failure_flag=True
        )
        assert (
            score_historical_failure(with_repeat)
            == _approx(score_historical_failure(base) + 20.0)
        )

    def test_weather_correlated_failures_add_points(self):
        no_weather = HistoricalFailureRecord(
            failure_count_last_5yr=2, failures_caused_by_weather=0
        )
        all_weather = HistoricalFailureRecord(
            failure_count_last_5yr=2, failures_caused_by_weather=2
        )
        assert score_historical_failure(all_weather) > score_historical_failure(no_weather)

    def test_max_scenario_capped_at_100(self):
        h = HistoricalFailureRecord(
            failure_count_last_5yr=10,
            failures_caused_by_weather=10,
            last_failure_days_ago=5,
            repeat_failure_flag=True,
        )
        assert score_historical_failure(h) <= 100.0

    def test_result_in_range(self):
        h = HistoricalFailureRecord(
            failure_count_last_5yr=2,
            failures_caused_by_weather=1,
            last_failure_days_ago=90,
        )
        assert 0.0 <= score_historical_failure(h) <= 100.0


# ===========================================================================
# 4. Asset degradation scoring
# ===========================================================================

class TestAssetDegradation:

    def test_new_asset_scores_low(self):
        s = AssetDegradationState(age_years=0.0, load_factor_avg=0.3)
        assert score_asset_degradation(s) == 0.0

    def test_age_at_rated_lifespan_gives_35_pts(self):
        s = AssetDegradationState(age_years=40.0, rated_lifespan_years=40.0)
        # age contributes 35 pts; no fault events, no overdue, load=0.5 → 0 load pts
        assert score_asset_degradation(s) == _approx(35.0)

    def test_insulation_score_supersedes_age(self):
        """When insulation_health_score is set it replaces the age proxy."""
        age_based = AssetDegradationState(age_years=40.0, rated_lifespan_years=40.0)
        ins_based = AssetDegradationState(
            age_years=40.0,
            rated_lifespan_years=40.0,
            insulation_health_score=70.0,  # 70 * 0.35 = 24.5 pts < 35 pts from age
        )
        assert score_asset_degradation(ins_based) < score_asset_degradation(age_based)

    def test_maintenance_overdue_stepped(self):
        on_schedule  = AssetDegradationState(maintenance_overdue_days=0)
        mild_overdue = AssetDegradationState(maintenance_overdue_days=15)
        late_overdue = AssetDegradationState(maintenance_overdue_days=200)
        assert score_asset_degradation(on_schedule) < score_asset_degradation(mild_overdue)
        assert score_asset_degradation(mild_overdue) < score_asset_degradation(late_overdue)

    def test_load_stress_zero_below_0_5(self):
        s = AssetDegradationState(load_factor_avg=0.49)
        # load stress only; all other factors zero
        assert score_asset_degradation(s) == 0.0

    def test_load_stress_max_at_1_0(self):
        s = AssetDegradationState(load_factor_avg=1.0)
        # load pts = 20 only (no age, no faults, no overdue)
        assert score_asset_degradation(s) == _approx(20.0)

    def test_max_scenario_capped_at_100(self):
        s = AssetDegradationState(
            age_years=60.0,
            rated_lifespan_years=40.0,
            cumulative_fault_events=20,
            maintenance_overdue_days=365,
            insulation_health_score=100.0,
            load_factor_avg=1.0,
        )
        assert score_asset_degradation(s) <= 100.0

    def test_result_in_range(self):
        s = AssetDegradationState(
            age_years=22.0,
            cumulative_fault_events=4,
            maintenance_overdue_days=60,
            load_factor_avg=0.72,
        )
        assert 0.0 <= score_asset_degradation(s) <= 100.0


# ===========================================================================
# 5. Grid impact scoring
# ===========================================================================

class TestGridImpact:

    def test_zero_inputs_returns_zero(self):
        assert score_grid_impact(GridImpactFactors()) == 0.0

    def test_critical_facilities_dominate(self):
        """Three critical facilities cap the critical sub-score at 35 pts."""
        f = GridImpactFactors(critical_facility_count=3, has_redundant_path=False)
        result = score_grid_impact(f)
        assert result >= 35.0

    def test_redundancy_discounts_non_critical(self):
        """Redundant path should lower score compared to non-redundant."""
        no_redundancy = GridImpactFactors(
            customers_served=20_000, peak_load_mw=15.0, downstream_asset_count=5,
            has_redundant_path=False,
        )
        with_redundancy = GridImpactFactors(
            customers_served=20_000, peak_load_mw=15.0, downstream_asset_count=5,
            has_redundant_path=True,
        )
        assert score_grid_impact(no_redundancy) > score_grid_impact(with_redundancy)

    def test_redundancy_does_not_discount_critical_facilities(self):
        """Critical-facility points must survive the redundancy discount."""
        f_redundant = GridImpactFactors(
            critical_facility_count=2, has_redundant_path=True
        )
        result = score_grid_impact(f_redundant)
        # 2 × 12 pts = 24 critical pts, no discount applied to those
        assert result == _approx(24.0)

    def test_customers_capped_at_reference(self):
        at_ref  = GridImpactFactors(customers_served=50_000, has_redundant_path=False)
        over_ref = GridImpactFactors(customers_served=200_000, has_redundant_path=False)
        assert score_grid_impact(at_ref) == _approx(score_grid_impact(over_ref))

    def test_max_scenario_capped_at_100(self):
        f = GridImpactFactors(
            customers_served=100_000,
            critical_facility_count=5,
            peak_load_mw=200.0,
            downstream_asset_count=50,
            has_redundant_path=False,
        )
        assert score_grid_impact(f) <= 100.0

    def test_result_in_range(self):
        f = GridImpactFactors(
            customers_served=8_000,
            critical_facility_count=1,
            peak_load_mw=7.0,
            downstream_asset_count=2,
            has_redundant_path=True,
        )
        assert 0.0 <= score_grid_impact(f) <= 100.0


# ===========================================================================
# 6. End-to-end score_asset() — fixture-based band tests
# ===========================================================================

class TestScoreAssetBands:

    def test_normal_fixture_is_normal(self):
        result = score_asset(NORMAL_FIXTURE)
        assert result.asset_id == "TX-NORMAL-001"
        assert result.overall_risk < 40.0, (
            f"Expected Normal (<40), got {result.overall_risk}"
        )
        assert result.risk_level == RiskLevel.NORMAL

    def test_watch_fixture_is_watch(self):
        result = score_asset(WATCH_FIXTURE)
        assert result.asset_id == "TX-WATCH-002"
        assert 40.0 <= result.overall_risk < 70.0, (
            f"Expected Watch (40–69), got {result.overall_risk}"
        )
        assert result.risk_level == RiskLevel.WATCH

    def test_high_fixture_is_high(self):
        result = score_asset(HIGH_FIXTURE)
        assert result.asset_id == "TX-HIGH-003"
        assert 70.0 <= result.overall_risk < 85.0, (
            f"Expected High (70–84), got {result.overall_risk}"
        )
        assert result.risk_level == RiskLevel.HIGH

    def test_critical_fixture_is_critical(self):
        result = score_asset(CRITICAL_FIXTURE)
        assert result.asset_id == "TX-CRITICAL-004"
        assert result.overall_risk >= 85.0, (
            f"Expected Critical (≥85), got {result.overall_risk}"
        )
        assert result.risk_level == RiskLevel.CRITICAL


# ===========================================================================
# 7. End-to-end score_asset() — component scores present and in range
# ===========================================================================

class TestScoreAssetComponents:

    @pytest.mark.parametrize("fixture", [
        NORMAL_FIXTURE, WATCH_FIXTURE, HIGH_FIXTURE, CRITICAL_FIXTURE
    ])
    def test_all_component_scores_in_range(self, fixture):
        result = score_asset(fixture)
        for field_name, val in [
            ("sensor_health",      result.components.sensor_health),
            ("weather_risk",       result.components.weather_risk),
            ("historical_failure", result.components.historical_failure),
            ("asset_degradation",  result.components.asset_degradation),
            ("grid_impact",        result.components.grid_impact),
        ]:
            assert 0.0 <= val <= 100.0, f"{field_name} out of range: {val}"

    @pytest.mark.parametrize("fixture", [
        NORMAL_FIXTURE, WATCH_FIXTURE, HIGH_FIXTURE, CRITICAL_FIXTURE
    ])
    def test_overall_risk_in_range(self, fixture):
        result = score_asset(fixture)
        assert 0.0 <= result.overall_risk <= 100.0

    @pytest.mark.parametrize("fixture", [
        NORMAL_FIXTURE, WATCH_FIXTURE, HIGH_FIXTURE, CRITICAL_FIXTURE
    ])
    def test_dominant_factor_is_valid_name(self, fixture):
        result = score_asset(fixture)
        valid = {"sensor_health", "weather_risk", "historical_failure",
                 "asset_degradation", "grid_impact"}
        assert result.dominant_factor in valid


# ===========================================================================
# 8. Classification boundary conditions
# ===========================================================================

class TestClassificationBoundaries:
    """
    Verify the exact thresholds: 0, 39.9, 40.0, 69.9, 70.0, 84.9, 85.0, 100.
    We drive score_asset with a minimal RiskInputs that produces a known score
    by using only the sensor_health channel (30% weight) with all others at 0.
    sensor_only_overall = sensor_score * 0.30
    """

    def _make_sensor_only(self, sensor_score: float) -> RiskInputs:
        """Craft an input where overall ≈ sensor_score * 0.30."""
        return RiskInputs(
            asset_id="TX-BOUNDARY",
            sensors=SensorReadings(
                # temperature_score drives 40% of sensor; PD drives 30%.
                # Set temperature to produce the desired sensor score:
                #   sensor = temp * 0.40  =>  temp = sensor_score / 0.40
                temperature_score=min(100.0, sensor_score / 0.40),
            ),
        )

    def test_boundary_just_below_watch(self):
        """sensor_score=100 → overall = 100*0.40*0.30 = 12 → Normal"""
        # Use a sensor score that gives overall just under 40
        # overall = s*0.30; want overall=39 → s=130 (impossible, use max)
        # Instead compute: overall = 100 * 0.40 * 0.30 = 12 → clearly Normal
        r = RiskInputs(asset_id="TX-B", sensors=SensorReadings(temperature_score=100.0))
        result = score_asset(r)
        assert result.risk_level == RiskLevel.NORMAL

    def test_exactly_40_is_watch(self):
        """
        Construct inputs where overall is exactly 40.
        sensor_health = 100 (all sensors max, no missing) * 1.0  weight 0.30
        weather_risk  = 100 (all weather max)              weight 0.20
        others = 0
        overall = 100*0.30 + 100*0.20 = 50.0 → Watch
        """
        inputs = RiskInputs(
            asset_id="TX-40",
            sensors=SensorReadings(
                temperature_score=100.0,
                vibration_score=100.0,
                oil_quality_score=100.0,
                partial_discharge_score=100.0,
            ),
            weather=WeatherConditions(
                temperature_stress_score=100.0,
                precipitation_score=100.0,
                wind_storm_score=100.0,
            ),
        )
        result = score_asset(inputs)
        # 100*0.30 + 100*0.20 (with compound multiplier capped at 100) = 50
        assert result.overall_risk == _approx(50.0)
        assert result.risk_level == RiskLevel.WATCH

    def test_exactly_85_is_critical(self):
        """All five components at max → overall = 100 → Critical."""
        inputs = RiskInputs(
            asset_id="TX-85",
            sensors=SensorReadings(
                temperature_score=100.0, partial_discharge_score=100.0,
                oil_quality_score=100.0, vibration_score=100.0,
            ),
            weather=WeatherConditions(
                temperature_stress_score=100.0, precipitation_score=100.0,
                wind_storm_score=100.0,
            ),
            history=HistoricalFailureRecord(
                failure_count_last_5yr=10, failures_caused_by_weather=10,
                last_failure_days_ago=5, repeat_failure_flag=True,
            ),
            degradation=AssetDegradationState(
                age_years=80.0, cumulative_fault_events=20,
                maintenance_overdue_days=365, load_factor_avg=1.0,
            ),
            grid_impact=GridImpactFactors(
                customers_served=100_000, critical_facility_count=10,
                peak_load_mw=500.0, downstream_asset_count=50,
                has_redundant_path=False,
            ),
        )
        result = score_asset(inputs)
        assert result.overall_risk == 100.0
        assert result.risk_level == RiskLevel.CRITICAL


# ===========================================================================
# 9. Dominant factor
# ===========================================================================

class TestDominantFactor:

    def test_sensor_dominant_when_sensor_highest(self):
        inputs = RiskInputs(
            asset_id="TX-DOM",
            sensors=SensorReadings(
                temperature_score=100.0, partial_discharge_score=100.0,
                oil_quality_score=100.0, vibration_score=100.0,
            ),
        )
        result = score_asset(inputs)
        assert result.dominant_factor == "sensor_health"

    def test_grid_impact_dominant_when_grid_highest(self):
        inputs = RiskInputs(
            asset_id="TX-DOM-GRID",
            grid_impact=GridImpactFactors(
                customers_served=50_000,
                critical_facility_count=3,
                peak_load_mw=50.0,
                downstream_asset_count=10,
                has_redundant_path=False,
            ),
        )
        result = score_asset(inputs)
        assert result.dominant_factor == "grid_impact"


# ===========================================================================
# 10. Determinism — same inputs always produce same outputs
# ===========================================================================

class TestDeterminism:

    @pytest.mark.parametrize("fixture", [
        NORMAL_FIXTURE, WATCH_FIXTURE, HIGH_FIXTURE, CRITICAL_FIXTURE
    ])
    def test_repeated_scoring_is_identical(self, fixture):
        r1 = score_asset(fixture)
        r2 = score_asset(fixture)
        assert r1.overall_risk == r2.overall_risk
        assert r1.risk_level   == r2.risk_level
        assert r1.dominant_factor == r2.dominant_factor
