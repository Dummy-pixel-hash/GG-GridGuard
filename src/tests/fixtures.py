"""
Synthetic test fixtures for the GridGuard risk engine test suite.

All values here are clearly invented for testing purposes — they do not
represent a real utility's assets or real measurement data.

Fixture naming convention:
    <asset_id> describes the scenario being exercised, e.g.
    "TX-NORMAL-001" → a transformer that should score in the Normal band.
"""

from risk_engine.models import (
    SensorReadings,
    WeatherConditions,
    HistoricalFailureRecord,
    AssetDegradationState,
    GridImpactFactors,
    RiskInputs,
)


# ---------------------------------------------------------------------------
# NORMAL scenario — TX-NORMAL-001
# A 10-year-old transformer in good condition, calm weather, no history,
# light load, no critical facilities downstream.
# Expected overall: well below 40 → RiskLevel.NORMAL
# ---------------------------------------------------------------------------
NORMAL_FIXTURE = RiskInputs(
    asset_id="TX-NORMAL-001",
    sensors=SensorReadings(
        temperature_score=10.0,
        vibration_score=5.0,
        oil_quality_score=8.0,
        partial_discharge_score=3.0,
        missing_sensor_ratio=0.0,
    ),
    weather=WeatherConditions(
        temperature_stress_score=10.0,
        precipitation_score=5.0,
        wind_storm_score=5.0,
    ),
    history=HistoricalFailureRecord(
        failure_count_last_5yr=0,
        failures_caused_by_weather=0,
        mean_time_between_failures_days=None,
        last_failure_days_ago=None,
        repeat_failure_flag=False,
    ),
    degradation=AssetDegradationState(
        age_years=10.0,
        rated_lifespan_years=40.0,
        cumulative_fault_events=0,
        maintenance_overdue_days=0,
        insulation_health_score=None,
        load_factor_avg=0.45,
    ),
    grid_impact=GridImpactFactors(
        customers_served=800,
        critical_facility_count=0,
        peak_load_mw=2.0,
        downstream_asset_count=1,
        has_redundant_path=True,
    ),
)


# ---------------------------------------------------------------------------
# WATCH scenario — TX-WATCH-002
# A 25-year-old transformer with moderate sensor readings, one past failure
# ~6 months ago, approaching moderate storm, moderate customer load.
# Sensor health ≈ 55, weather ≈ 52, history ≈ 21, degradation ≈ 57, grid ≈ 18
# overall ≈ 55*0.30 + 52*0.20 + 21*0.15 + 57*0.15 + 18*0.20
#         = 16.5 + 10.4 + 3.2 + 8.6 + 3.6 = 42.3 → Watch
# Expected overall: 40–69 → RiskLevel.WATCH
# ---------------------------------------------------------------------------
WATCH_FIXTURE = RiskInputs(
    asset_id="TX-WATCH-002",
    sensors=SensorReadings(
        temperature_score=60.0,
        vibration_score=40.0,
        oil_quality_score=50.0,
        partial_discharge_score=50.0,
        missing_sensor_ratio=0.0,
    ),
    weather=WeatherConditions(
        temperature_stress_score=55.0,
        precipitation_score=45.0,
        wind_storm_score=52.0,
    ),
    history=HistoricalFailureRecord(
        failure_count_last_5yr=1,
        failures_caused_by_weather=0,
        mean_time_between_failures_days=None,
        last_failure_days_ago=180,
        repeat_failure_flag=False,
    ),
    degradation=AssetDegradationState(
        age_years=25.0,
        rated_lifespan_years=40.0,
        cumulative_fault_events=3,
        maintenance_overdue_days=45,
        insulation_health_score=None,
        load_factor_avg=0.65,
    ),
    grid_impact=GridImpactFactors(
        customers_served=12_000,
        critical_facility_count=0,
        peak_load_mw=12.0,
        downstream_asset_count=3,
        has_redundant_path=True,
    ),
)


# ---------------------------------------------------------------------------
# HIGH scenario — TX-HIGH-003
# A 35-year-old transformer, elevated sensor readings, two failures in the
# last 6 months (one very recent), severe approaching storm, no redundancy,
# significant customer exposure.
# Sensor ≈ 78, weather ≈ 79, history ≈ 60, degradation ≈ 83, grid ≈ 60
# overall ≈ 78*0.30 + 79*0.20 + 60*0.15 + 83*0.15 + 60*0.20
#         = 23.4 + 15.8 + 9.0 + 12.5 + 12.0 = 72.7 → High
# Expected overall: 70–84 → RiskLevel.HIGH
# ---------------------------------------------------------------------------
HIGH_FIXTURE = RiskInputs(
    asset_id="TX-HIGH-003",
    sensors=SensorReadings(
        temperature_score=82.0,
        vibration_score=65.0,
        oil_quality_score=72.0,
        partial_discharge_score=80.0,
        missing_sensor_ratio=0.25,  # one of four sensors offline
    ),
    weather=WeatherConditions(
        temperature_stress_score=72.0,
        precipitation_score=68.0,
        wind_storm_score=85.0,
    ),
    history=HistoricalFailureRecord(
        failure_count_last_5yr=2,
        failures_caused_by_weather=2,
        mean_time_between_failures_days=365.0,
        last_failure_days_ago=60,
        repeat_failure_flag=False,
    ),
    degradation=AssetDegradationState(
        age_years=35.0,
        rated_lifespan_years=40.0,
        cumulative_fault_events=7,
        maintenance_overdue_days=100,
        insulation_health_score=None,
        load_factor_avg=0.85,
    ),
    grid_impact=GridImpactFactors(
        customers_served=30_000,
        critical_facility_count=1,
        peak_load_mw=25.0,
        downstream_asset_count=6,
        has_redundant_path=False,
    ),
)


# ---------------------------------------------------------------------------
# CRITICAL scenario — TX-CRITICAL-004
# An end-of-life transformer with alarming sensor readings, recent repeat
# failure, severe incoming storm, hospital downstream, no redundancy.
# Expected overall: 85–100 → RiskLevel.CRITICAL
# ---------------------------------------------------------------------------
CRITICAL_FIXTURE = RiskInputs(
    asset_id="TX-CRITICAL-004",
    sensors=SensorReadings(
        temperature_score=95.0,
        vibration_score=80.0,
        oil_quality_score=90.0,
        partial_discharge_score=98.0,
        missing_sensor_ratio=0.0,
    ),
    weather=WeatherConditions(
        temperature_stress_score=90.0,
        precipitation_score=85.0,
        wind_storm_score=95.0,
    ),
    history=HistoricalFailureRecord(
        failure_count_last_5yr=4,
        failures_caused_by_weather=3,
        mean_time_between_failures_days=365.0,
        last_failure_days_ago=25,
        repeat_failure_flag=True,
    ),
    degradation=AssetDegradationState(
        age_years=42.0,
        rated_lifespan_years=40.0,
        cumulative_fault_events=12,
        maintenance_overdue_days=200,
        insulation_health_score=88.0,
        load_factor_avg=0.95,
    ),
    grid_impact=GridImpactFactors(
        customers_served=48_000,
        critical_facility_count=3,  # hospital + water plant + emergency services
        peak_load_mw=45.0,
        downstream_asset_count=9,
        has_redundant_path=False,
    ),
)
