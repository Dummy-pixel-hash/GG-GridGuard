"""
Storm severity classifier.

Derives the ``storm_warning_level`` integer (0–3) from quantitative
Open-Meteo forecast values.  This lives in its own module so the
classification rules are explicit, independently testable, and easy to
tune without touching the HTTP layer.

Classification rules (evaluated in priority order — highest level wins)
------------------------------------------------------------------------
Level 3 — WARNING  (severe storm imminent)
    wind_speed_max_kmh  >= 90   (strong gale / storm-force winds)
    OR precipitation_mm >= 80   (extreme rainfall / flash-flood risk)

Level 2 — WATCH    (conditions are dangerous, monitoring closely)
    wind_speed_max_kmh  >= 65   (near-gale force winds)
    OR precipitation_mm >= 50

Level 1 — ADVISORY (conditions are notable, elevated awareness)
    wind_speed_max_kmh  >= 40   (fresh to strong breeze)
    OR precipitation_mm >= 25
    OR max_temp_c       >= 38   (extreme heat advisory)
    OR min_temp_c       <= -5   (hard-freeze advisory)

Level 0 — NONE     (normal / benign conditions)

These thresholds are representative of national weather service advisory
scales; they are tunable by replacing the ``StormClassifierConfig`` defaults.

SYNTHETIC / DEMO — not calibrated to any specific meteorological standard.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StormClassifierConfig:
    """
    Thresholds used by ``classify_storm_level``.

    All values are in the same physical units as ``RawWeatherObservation``:
    temperatures in °C, wind in km/h, precipitation in mm / forecast window.
    """
    # Level-3 (WARNING) thresholds
    wind_warning_kmh: float = 90.0
    precip_warning_mm: float = 80.0

    # Level-2 (WATCH) thresholds
    wind_watch_kmh: float = 65.0
    precip_watch_mm: float = 50.0

    # Level-1 (ADVISORY) thresholds
    wind_advisory_kmh: float = 40.0
    precip_advisory_mm: float = 25.0
    temp_heat_advisory_c: float = 38.0   # max_temp_c
    temp_cold_advisory_c: float = -5.0   # min_temp_c


DEFAULT_CLASSIFIER_CONFIG = StormClassifierConfig()


def classify_storm_level(
    *,
    max_temp_c: float,
    min_temp_c: float,
    precipitation_mm: float,
    wind_speed_max_kmh: float,
    config: StormClassifierConfig = DEFAULT_CLASSIFIER_CONFIG,
) -> int:
    """
    Return an integer storm warning level 0–3.

    Args:
        max_temp_c:          Maximum forecast air temperature in °C.
        min_temp_c:          Minimum forecast air temperature in °C.
        precipitation_mm:    Total forecast precipitation in mm.
        wind_speed_max_kmh:  Maximum forecast wind speed in km/h.
        config:              Threshold configuration.  Defaults to
                             ``DEFAULT_CLASSIFIER_CONFIG``.

    Returns:
        0 — normal / no advisory
        1 — advisory
        2 — watch
        3 — warning
    """
    # Level 3 — WARNING
    if (
        wind_speed_max_kmh >= config.wind_warning_kmh
        or precipitation_mm >= config.precip_warning_mm
    ):
        return 3

    # Level 2 — WATCH
    if (
        wind_speed_max_kmh >= config.wind_watch_kmh
        or precipitation_mm >= config.precip_watch_mm
    ):
        return 2

    # Level 1 — ADVISORY
    if (
        wind_speed_max_kmh >= config.wind_advisory_kmh
        or precipitation_mm >= config.precip_advisory_mm
        or max_temp_c >= config.temp_heat_advisory_c
        or min_temp_c <= config.temp_cold_advisory_c
    ):
        return 1

    return 0
