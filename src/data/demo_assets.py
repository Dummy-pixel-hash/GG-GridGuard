"""
GridGuard synthetic demo dataset — 8 representative grid assets.

SYNTHETIC / DEMO DATA ONLY.  Every value is invented for demonstration
purposes; no real utility asset data or customer information is included.

Asset roster
------------
TX-001  Riverside Main        — NORMAL    (new, healthy, redundant)
TX-002  Northgate Residential — NORMAL    (mid-life, low load, calm weather)
TX-003  Eastside Industrial   — WATCH     (ageing, moderate sensor readings)
TX-004  Central Business      — WATCH     (moderate history, approaching storm)
TX-005  Harbour Substation    — HIGH      (old, degraded, storm inbound)
TX-006  Hillcrest Feeder      — HIGH      (repeat fault, no redundancy)
TX-007  Waterfront Plaza      — CRITICAL  (end-of-life, hospital, severe storm)
TX-008  Airport Grid Node     — CRITICAL  (alarming sensors, repeat failure, storm)
"""

from __future__ import annotations

from .raw_types import (
    AssetLocation,
    AssetMetadata,
    RawAssetRecord,
    RawDegradationRecord,
    RawGridTopology,
    RawIncidentRecord,
    RawSensorTelemetry,
    RawWeatherObservation,
)


# ── Helper: build an AssetMetadata quickly ──────────────────────────────────
def _meta(
    asset_id: str,
    *,
    asset_type: str = "transformer",
    rated_kva: float,
    voltage_kv: float,
    lifespan: float = 40.0,
    year: int,
    lat: float,
    lon: float,
    substation: str,
    region: str,
    notes: str = "",
) -> AssetMetadata:
    return AssetMetadata(
        asset_id=asset_id,
        asset_type=asset_type,
        rated_kva=rated_kva,
        rated_voltage_kv=voltage_kv,
        rated_lifespan_years=lifespan,
        commissioned_year=year,
        location=AssetLocation(
            latitude=lat,
            longitude=lon,
            substation_name=substation,
            region=region,
        ),
        notes=notes,
    )


# ===========================================================================
# TX-001  Riverside Main — NORMAL
# Brand-new 10-year-old 40 MVA transformer.  All sensors nominal.
# Calm weather.  No incident history.  N-1 redundant.
# ===========================================================================
TX_001 = RawAssetRecord(
    metadata=_meta(
        "TX-001",
        rated_kva=40_000, voltage_kv=66.0, year=2015,
        lat=51.505, lon=-0.128, substation="Riverside Main", region="Central",
        notes="New flagship transformer — NORMAL baseline asset.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=52.0,       # well within 98 °C alarm
        winding_hot_spot_c=68.0,   # well within 128 °C alarm
        vibration_mm_s=0.6,        # far below 4.5 mm/s alarm
        oil_dielectric_kv=68.0,    # healthy (≥ 70 kV nominal; just below, minor)
        partial_discharge_pc=80.0, # low background PD
        load_factor_current=0.42,
    ),
    weather=RawWeatherObservation(
        max_temp_c=18.0, min_temp_c=10.0,
        precipitation_mm=2.0, wind_speed_max_kmh=25.0,
        storm_warning_level=0, forecast_hours=72,
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=0, failures_caused_by_weather=0,
        last_failure_days_ago=None, repeat_mode_flag=False,
    ),
    degradation=RawDegradationRecord(
        age_years=10.0, cumulative_fault_events=0,
        maintenance_overdue_days=0, insulation_health_pct=96.0,
        average_load_factor=0.42,
    ),
    topology=RawGridTopology(
        customers_served=3_200, critical_facility_count=0,
        peak_load_mw=3.5, downstream_asset_count=2,
        has_n1_redundancy=True,
    ),
)


# ===========================================================================
# TX-002  Northgate Residential — NORMAL
# 18-year-old 25 MVA transformer, light residential load.  Mild weather.
# One minor fault event 4 years ago, fully repaired, no recurrence.
# ===========================================================================
TX_002 = RawAssetRecord(
    metadata=_meta(
        "TX-002",
        rated_kva=25_000, voltage_kv=33.0, year=2007,
        lat=51.560, lon=-0.105, substation="Northgate", region="North",
        notes="Residential feeder — NORMAL with minor history.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=58.0,
        winding_hot_spot_c=74.0,
        vibration_mm_s=0.9,
        oil_dielectric_kv=62.0,
        partial_discharge_pc=150.0,
        load_factor_current=0.38,
    ),
    weather=RawWeatherObservation(
        max_temp_c=22.0, min_temp_c=12.0,
        precipitation_mm=5.0, wind_speed_max_kmh=30.0,
        storm_warning_level=0, forecast_hours=72,
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=0, failures_caused_by_weather=0,
        last_failure_days_ago=None, repeat_mode_flag=False,
    ),
    degradation=RawDegradationRecord(
        age_years=18.0, cumulative_fault_events=1,
        maintenance_overdue_days=0, insulation_health_pct=88.0,
        average_load_factor=0.40,
    ),
    topology=RawGridTopology(
        customers_served=7_500, critical_facility_count=0,
        peak_load_mw=6.0, downstream_asset_count=3,
        has_n1_redundancy=True,
    ),
)


# ===========================================================================
# TX-003  Eastside Industrial — WATCH
# 28-year-old 60 MVA transformer serving an industrial zone.  Oil quality
# is declining; temperatures elevated from prolonged heavy industrial load.
# One failure 14 months ago, weather-related.  Moderate storm approaching.
# Storm advisory in effect; summer heat wave forecast.
# ===========================================================================
TX_003 = RawAssetRecord(
    metadata=_meta(
        "TX-003",
        rated_kva=60_000, voltage_kv=110.0, year=1997,
        lat=51.487, lon=0.023, substation="Eastside Industrial", region="East",
        notes="Ageing industrial transformer — WATCH due to oil degradation + heat.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=80.0,        # elevated (hot summer)
        winding_hot_spot_c=103.0,   # noticeably above nominal
        vibration_mm_s=2.2,
        oil_dielectric_kv=34.0,     # degraded oil
        partial_discharge_pc=480.0,
        load_factor_current=0.78,
    ),
    weather=RawWeatherObservation(
        max_temp_c=36.0, min_temp_c=24.0,   # summer heat wave
        precipitation_mm=28.0, wind_speed_max_kmh=65.0,
        storm_warning_level=2, forecast_hours=72,  # 65 km/h ≥ watch threshold → level 2
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=1, failures_caused_by_weather=1,
        last_failure_days_ago=425,  # ~14 months ago
        repeat_mode_flag=False,
    ),
    degradation=RawDegradationRecord(
        age_years=28.0, cumulative_fault_events=4,
        maintenance_overdue_days=55, insulation_health_pct=65.0,
        average_load_factor=0.72,
    ),
    topology=RawGridTopology(
        customers_served=18_000, critical_facility_count=0,
        peak_load_mw=22.0, downstream_asset_count=5,
        has_n1_redundancy=True,
    ),
)


# ===========================================================================
# TX-004  Central Business — WATCH
# 22-year-old 50 MVA transformer in a CBD.  Sensor readings moderate but
# rising; oil degrading.  One failure 6 months ago.  Heat wave + storm
# advisory arriving; highest temperatures of the year forecast.
# N-1 redundancy present; significant commercial load.
# ===========================================================================
TX_004 = RawAssetRecord(
    metadata=_meta(
        "TX-004",
        rated_kva=50_000, voltage_kv=66.0, year=2003,
        lat=51.512, lon=-0.132, substation="Central Business", region="Central",
        notes="CBD transformer — WATCH; heat wave + storm advisory; oil degrading.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=78.0,         # elevated in heat wave
        winding_hot_spot_c=100.0,
        vibration_mm_s=1.8,
        oil_dielectric_kv=38.0,      # degraded
        partial_discharge_pc=450.0,
        load_factor_current=0.72,
    ),
    weather=RawWeatherObservation(
        max_temp_c=37.0, min_temp_c=26.0,   # peak summer heat wave
        precipitation_mm=30.0, wind_speed_max_kmh=72.0,
        storm_warning_level=1, forecast_hours=72,
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=1, failures_caused_by_weather=0,
        last_failure_days_ago=185, repeat_mode_flag=False,
    ),
    degradation=RawDegradationRecord(
        age_years=22.0, cumulative_fault_events=4,
        maintenance_overdue_days=60, insulation_health_pct=68.0,
        average_load_factor=0.68,
    ),
    topology=RawGridTopology(
        customers_served=22_000, critical_facility_count=0,
        peak_load_mw=26.0, downstream_asset_count=5,
        has_n1_redundancy=True,
    ),
)


# ===========================================================================
# TX-005  Harbour Substation — HIGH
# 34-year-old 80 MVA substation transformer.  Significantly elevated
# temperature and PD.  Oil failing.  Storm watch in effect.  Two failures
# in 3 years (last one 2 months ago).  No redundant path.
# ===========================================================================
TX_005 = RawAssetRecord(
    metadata=_meta(
        "TX-005",
        asset_type="substation",
        rated_kva=80_000, voltage_kv=110.0, year=1991,
        lat=51.498, lon=-0.072, substation="Harbour Substation", region="South",
        notes="Old harbour substation — HIGH risk, storm approaching, no redundancy.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=86.0,         # approaching alarm
        winding_hot_spot_c=112.0,
        vibration_mm_s=2.9,
        oil_dielectric_kv=28.0,      # below 30 kV — failing dielectric
        partial_discharge_pc=780.0,
        load_factor_current=0.83,
    ),
    weather=RawWeatherObservation(
        max_temp_c=35.0, min_temp_c=24.0,
        precipitation_mm=55.0, wind_speed_max_kmh=88.0,
        storm_warning_level=2, forecast_hours=72,
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=2, failures_caused_by_weather=2,
        last_failure_days_ago=62, repeat_mode_flag=False,
        mean_time_between_failures_days=480.0,
    ),
    degradation=RawDegradationRecord(
        age_years=34.0, cumulative_fault_events=7,
        maintenance_overdue_days=110, insulation_health_pct=41.0,
        average_load_factor=0.79,
    ),
    topology=RawGridTopology(
        customers_served=28_000, critical_facility_count=1,
        critical_facility_names=["Port Authority Control Centre"],
        peak_load_mw=28.0, downstream_asset_count=7,
        has_n1_redundancy=False,
    ),
)


# ===========================================================================
# TX-006  Hillcrest Feeder — HIGH
# 31-year-old 35 MVA transformer.  Repeat fault mode — overheating not
# fully resolved in last repair.  Vibration significantly elevated.  PD
# active.  No redundant path.  Storm watch in effect; significant heat.
# Serves 28 000 customers with no alternative supply.
# ===========================================================================
TX_006 = RawAssetRecord(
    metadata=_meta(
        "TX-006",
        rated_kva=35_000, voltage_kv=33.0, year=1994,
        lat=51.535, lon=-0.156, substation="Hillcrest", region="West",
        notes="Hillcrest feeder — HIGH; unresolved repeat fault; storm watch; no redundancy.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=85.0,         # markedly elevated
        winding_hot_spot_c=112.0,
        vibration_mm_s=3.5,          # well above 1.0 nominal
        oil_dielectric_kv=29.0,      # below 30 kV alarm
        partial_discharge_pc=820.0,
        load_factor_current=0.82,
    ),
    weather=RawWeatherObservation(
        max_temp_c=34.0, min_temp_c=22.0,   # hot + storm warning
        precipitation_mm=55.0, wind_speed_max_kmh=90.0,
        storm_warning_level=3, forecast_hours=72,
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=2, failures_caused_by_weather=1,
        last_failure_days_ago=45, repeat_mode_flag=True,   # ← unresolved fault
        mean_time_between_failures_days=600.0,
    ),
    degradation=RawDegradationRecord(
        age_years=31.0, cumulative_fault_events=8,
        maintenance_overdue_days=120, insulation_health_pct=38.0,
        average_load_factor=0.78,
    ),
    topology=RawGridTopology(
        customers_served=28_000, critical_facility_count=1,
        critical_facility_names=["Hillcrest Fire Station"],
        peak_load_mw=24.0, downstream_asset_count=6,
        has_n1_redundancy=False,
    ),
)


# ===========================================================================
# TX-007  Waterfront Plaza — CRITICAL
# 43-year-old 120 MVA substation transformer (past rated lifespan).
# Alarm-level sensor readings across the board.  Hospital and water treatment
# plant downstream.  Repeat failure 3 weeks ago.  Severe storm warning.
# No N-1 path.
# ===========================================================================
TX_007 = RawAssetRecord(
    metadata=_meta(
        "TX-007",
        asset_type="substation",
        rated_kva=120_000, voltage_kv=132.0, lifespan=40.0, year=1982,
        lat=51.507, lon=-0.060, substation="Waterfront Plaza", region="East",
        notes="End-of-life substation — CRITICAL; hospital downstream; storm inbound.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=94.0,          # near 98 °C alarm
        winding_hot_spot_c=124.0,     # near 128 °C alarm
        vibration_mm_s=4.1,           # near 4.5 mm/s alarm
        oil_dielectric_kv=18.0,       # severely degraded
        partial_discharge_pc=2_200.0, # well above 1000 pC alarm
        load_factor_current=0.91,
    ),
    weather=RawWeatherObservation(
        max_temp_c=38.0, min_temp_c=26.0,
        precipitation_mm=82.0, wind_speed_max_kmh=115.0,
        storm_warning_level=3, forecast_hours=72,
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=4, failures_caused_by_weather=3,
        last_failure_days_ago=22, repeat_mode_flag=True,
        mean_time_between_failures_days=365.0,
    ),
    degradation=RawDegradationRecord(
        age_years=43.0, cumulative_fault_events=13,
        maintenance_overdue_days=210, insulation_health_pct=12.0,
        average_load_factor=0.88,
    ),
    topology=RawGridTopology(
        customers_served=46_000,
        critical_facility_count=3,
        critical_facility_names=["City General Hospital", "Waterfront Water Treatment", "Fire Station HQ"],
        peak_load_mw=44.0, downstream_asset_count=9,
        has_n1_redundancy=False,
    ),
)


# ===========================================================================
# TX-008  Airport Grid Node — CRITICAL
# 38-year-old 100 MVA transformer feeding the regional airport.
# Alarming PD and temperature.  Oil failing.  Recent repeat failure.
# Severe storm warning active.  Airport = 2 critical facilities
# (control tower + fuel pumping station).
# ===========================================================================
TX_008 = RawAssetRecord(
    metadata=_meta(
        "TX-008",
        asset_type="transformer",
        rated_kva=100_000, voltage_kv=132.0, lifespan=40.0, year=1987,
        lat=51.477, lon=-0.461, substation="Airport Grid Node", region="West",
        notes="Airport grid node — CRITICAL; alarming sensors; storm warning.",
    ),
    telemetry=RawSensorTelemetry(
        top_oil_temp_c=91.0,
        winding_hot_spot_c=121.0,
        vibration_mm_s=3.8,
        oil_dielectric_kv=22.0,
        partial_discharge_pc=1_850.0,
        load_factor_current=0.89,
    ),
    weather=RawWeatherObservation(
        max_temp_c=36.0, min_temp_c=24.0,
        precipitation_mm=70.0, wind_speed_max_kmh=105.0,
        storm_warning_level=3, forecast_hours=72,
    ),
    incidents=RawIncidentRecord(
        failure_count_last_5yr=3, failures_caused_by_weather=2,
        last_failure_days_ago=30, repeat_mode_flag=True,
        mean_time_between_failures_days=480.0,
    ),
    degradation=RawDegradationRecord(
        age_years=38.0, cumulative_fault_events=10,
        maintenance_overdue_days=175, insulation_health_pct=20.0,
        average_load_factor=0.85,
    ),
    topology=RawGridTopology(
        customers_served=38_000,
        critical_facility_count=2,
        critical_facility_names=["Airport Control Tower", "Airport Fuel Pumping Station"],
        peak_load_mw=42.0, downstream_asset_count=8,
        has_n1_redundancy=False,
    ),
)


# ---------------------------------------------------------------------------
# Full dataset — ordered by expected risk (low → high) for easy scanning
# ---------------------------------------------------------------------------
ALL_ASSETS: list[RawAssetRecord] = [
    TX_001, TX_002,   # Normal
    TX_003, TX_004,   # Watch
    TX_005, TX_006,   # High
    TX_007, TX_008,   # Critical
]
