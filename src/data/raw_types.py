"""
Raw measurement types for GridGuard demo data.

These dataclasses represent values *before* normalisation — i.e. in physical
units as they would arrive from a sensor SCADA system, weather feed, asset
registry, or incident management system.

SYNTHETIC / DEMO DATA ONLY — no real utility data here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Asset metadata
# ---------------------------------------------------------------------------

@dataclass
class AssetLocation:
    """Geographic position of the asset (used for weather lookup later)."""
    latitude: float   # decimal degrees
    longitude: float  # decimal degrees
    substation_name: str = ""
    region: str = ""


@dataclass
class AssetMetadata:
    """
    Static registry information for one grid asset.

    Attributes:
        asset_id:           Unique identifier, e.g. "TX-001".
        asset_type:         "transformer" | "substation" | "feeder" etc.
        rated_kva:          Rated capacity in kVA.
        rated_voltage_kv:   Primary voltage rating in kV.
        rated_lifespan_years: Manufacturer rated service life.
        commissioned_year:  Year the asset was commissioned (or last replaced).
        location:           Geographic position.
        notes:              Free-text description for demo/display purposes.
    """
    asset_id: str
    asset_type: str                   # "transformer" | "substation" | "feeder"
    rated_kva: float                  # kVA
    rated_voltage_kv: float           # kV
    rated_lifespan_years: float = 40.0
    commissioned_year: int = 2000
    location: AssetLocation = field(default_factory=AssetLocation)
    notes: str = ""


# ---------------------------------------------------------------------------
# Raw sensor telemetry
# ---------------------------------------------------------------------------

@dataclass
class RawSensorTelemetry:
    """
    Physical-unit sensor readings for one asset at one point in time.

    None means the sensor is offline / data unavailable.

    Attributes:
        top_oil_temp_c:         Top-oil temperature in °C.
                                Typical operating range: 40–90 °C.
                                Alarm threshold: 98 °C (IEC 60076-2).
        winding_hot_spot_c:     Hot-spot winding temperature in °C.
                                Alarm threshold: 128 °C (IEC 60076-2).
        vibration_mm_s:         Vibration velocity in mm/s (RMS).
                                Alarm threshold: 4.5 mm/s for power transformers.
        oil_dielectric_kv:      Oil dielectric strength in kV.
                                New oil: ≥ 70 kV; degraded: < 30 kV (IEC 60156).
        partial_discharge_pc:   Partial discharge magnitude in picocoulombs (pC).
                                Background level: < 100 pC; alarm: > 1000 pC.
        load_factor_current:    Current load as a fraction of rated capacity (0–1).
    """
    top_oil_temp_c: Optional[float] = None         # °C
    winding_hot_spot_c: Optional[float] = None     # °C
    vibration_mm_s: Optional[float] = None         # mm/s RMS
    oil_dielectric_kv: Optional[float] = None      # kV
    partial_discharge_pc: Optional[float] = None   # pC
    load_factor_current: Optional[float] = None    # 0.0–1.0


# ---------------------------------------------------------------------------
# Raw weather observations / forecast
# ---------------------------------------------------------------------------

@dataclass
class RawWeatherObservation:
    """
    Weather values for the asset's location.  In production these come from
    Open-Meteo; here they are hard-coded synthetic values.

    Attributes:
        max_temp_c:            Forecast maximum air temperature in °C.
        min_temp_c:            Forecast minimum air temperature in °C.
        precipitation_mm:      Total forecast precipitation in mm.
        wind_speed_max_kmh:    Maximum forecast wind speed in km/h.
        storm_warning_level:   Integer 0–3 (0=none, 1=advisory, 2=watch, 3=warning).
        forecast_hours:        Window over which these values are aggregated.
    """
    max_temp_c: float = 20.0
    min_temp_c: float = 10.0
    precipitation_mm: float = 0.0
    wind_speed_max_kmh: float = 0.0
    storm_warning_level: int = 0      # 0–3
    forecast_hours: int = 72


# ---------------------------------------------------------------------------
# Raw historical incident record
# ---------------------------------------------------------------------------

@dataclass
class RawIncidentRecord:
    """
    Aggregated historical incident data pulled from a fault-management system.

    Attributes:
        failure_count_last_5yr:         Confirmed outage-causing failures.
        failures_caused_by_weather:     Subset caused by weather events.
        last_failure_days_ago:          Days since the last failure (None = never failed).
        repeat_mode_flag:               True if the most recent failure mode
                                        matches the previous (unresolved root cause).
        mean_time_between_failures_days: Average inter-failure interval (None if < 2 failures).
    """
    failure_count_last_5yr: int = 0
    failures_caused_by_weather: int = 0
    last_failure_days_ago: Optional[int] = None
    repeat_mode_flag: bool = False
    mean_time_between_failures_days: Optional[float] = None


# ---------------------------------------------------------------------------
# Raw degradation / maintenance record
# ---------------------------------------------------------------------------

@dataclass
class RawDegradationRecord:
    """
    Long-run wear and lifecycle data from the asset management system.

    Attributes:
        age_years:                  Years since commissioning / last replacement.
        cumulative_fault_events:    Total fault events (not all caused outages).
        maintenance_overdue_days:   Days past scheduled maintenance (0 = on time).
        insulation_health_pct:      Measured insulation health from DGA or
                                    inspection, expressed as 0–100% where
                                    100% = new / perfect and 0% = failed.
                                    None if not measured.
        average_load_factor:        Average load fraction over the asset's life.
    """
    age_years: float = 0.0
    cumulative_fault_events: int = 0
    maintenance_overdue_days: int = 0
    insulation_health_pct: Optional[float] = None   # 0–100 (100 = healthy)
    average_load_factor: float = 0.5


# ---------------------------------------------------------------------------
# Raw grid topology / impact data
# ---------------------------------------------------------------------------

@dataclass
class RawGridTopology:
    """
    Network topology and load data relevant to consequence-of-failure scoring.

    Attributes:
        customers_served:         End customers on this feeder.
        critical_facility_count:  Downstream hospitals / water / emergency.
        critical_facility_names:  Optional list for dashboard display.
        peak_load_mw:             Peak load in MW through this asset.
        downstream_asset_count:   Assets that de-energise if this one fails.
        has_n1_redundancy:        True if N-1 switching path exists.
    """
    customers_served: int = 0
    critical_facility_count: int = 0
    critical_facility_names: list[str] = field(default_factory=list)
    peak_load_mw: float = 0.0
    downstream_asset_count: int = 0
    has_n1_redundancy: bool = True


# ---------------------------------------------------------------------------
# Composite raw asset record (everything about one asset in one place)
# ---------------------------------------------------------------------------

@dataclass
class RawAssetRecord:
    """
    Everything the normalisation layer needs about one asset.

    This is the top-level type passed to ``normalise()`` to produce
    ``RiskInputs`` for the risk engine.
    """
    metadata: AssetMetadata
    telemetry: RawSensorTelemetry = field(default_factory=RawSensorTelemetry)
    weather: RawWeatherObservation = field(default_factory=RawWeatherObservation)
    incidents: RawIncidentRecord = field(default_factory=RawIncidentRecord)
    degradation: RawDegradationRecord = field(default_factory=RawDegradationRecord)
    topology: RawGridTopology = field(default_factory=RawGridTopology)
