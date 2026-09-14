"""
Open-Meteo weather fetcher.

Fetches a 72-hour (or configurable) hourly forecast from the free Open-Meteo
API for a given latitude/longitude, aggregates the raw hourly values into the
summary fields ``RawWeatherObservation`` expects, and returns it ready for the
normalisation layer.

Open-Meteo API reference: https://open-meteo.com/en/docs
No API key required for non-commercial use.

Architecture contract
---------------------
- This module knows about Open-Meteo's URL schema and JSON structure.
- It does NOT know about the normalisation layer or the risk engine.
- It produces a ``RawWeatherObservation`` (from ``data.raw_types``), which
  is the same type the normaliser already consumes.
- The caller (e.g. a pipeline that refreshes all asset weather records) calls
  ``fetch_weather`` and stores the result in ``RawAssetRecord.weather``.

Fallback behaviour
------------------
When ``fetch_weather`` raises ``WeatherFetchError``, callers that need a
graceful degradation should catch it and keep the existing (static / last-
known) ``RawWeatherObservation`` on the asset record rather than aborting.
A helper ``fetch_weather_with_fallback`` is provided for this pattern.

Open-Meteo variables requested
--------------------------------
We request hourly variables over the forecast window:

    temperature_2m          °C  — ambient air temperature at 2 m
    precipitation           mm  — hourly precipitation amount
    windspeed_10m           km/h — wind speed at 10 m
    windgusts_10m           km/h — wind gust speed at 10 m (used for max)

Aggregations over the forecast window:
    max_temp_c              = max(temperature_2m)
    min_temp_c              = min(temperature_2m)
    precipitation_mm        = sum(precipitation)       (total over window)
    wind_speed_max_kmh      = max(windgusts_10m)       (peak gust)
    storm_warning_level     = classify_storm_level(...)
"""

from __future__ import annotations

import math
from typing import Any, Optional
from urllib.parse import urlencode

from data.raw_types import RawWeatherObservation
from weather.client import DEFAULT_HTTP_CLIENT, HttpClient
from weather.storm_classifier import (
    DEFAULT_CLASSIFIER_CONFIG,
    StormClassifierConfig,
    classify_storm_level,
)


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class WeatherFetchError(RuntimeError):
    """
    Raised when the Open-Meteo API cannot be reached, returns an error
    response, or returns data that cannot be parsed into a
    ``RawWeatherObservation``.

    Callers that want graceful degradation should catch this and fall back to
    the asset's existing static weather data.
    """


# ---------------------------------------------------------------------------
# Open-Meteo API configuration
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Hourly variables we request — see module docstring for rationale
_HOURLY_VARIABLES = [
    "temperature_2m",
    "precipitation",
    "windspeed_10m",
    "windgusts_10m",
]

# Default request timeout in seconds
_DEFAULT_TIMEOUT_S = 10.0


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _require_key(data: dict[str, Any], key: str, context: str) -> Any:
    """Extract a required key or raise ``WeatherFetchError``."""
    if key not in data:
        raise WeatherFetchError(f"Open-Meteo response missing '{key}' in {context}")
    return data[key]


def _parse_hourly_series(
    hourly: dict[str, Any],
    variable: str,
    n_hours: int,
) -> list[float]:
    """
    Extract the first ``n_hours`` values of a named hourly variable.

    Filters out None/null values (Open-Meteo uses null for unavailable hours).
    Returns an empty list if the variable is absent or entirely null.
    """
    values = hourly.get(variable, [])
    if not isinstance(values, list):
        raise WeatherFetchError(
            f"Open-Meteo hourly.{variable} is not a list (got {type(values).__name__})"
        )
    # Take only the first n_hours entries; filter NaN/None
    sliced = values[:n_hours]
    return [v for v in sliced if v is not None and not (isinstance(v, float) and math.isnan(v))]


def _aggregate(
    hourly: dict[str, Any],
    forecast_hours: int,
) -> dict[str, float]:
    """
    Aggregate hourly Open-Meteo values into the scalar summary fields
    ``RawWeatherObservation`` needs.

    Returns a dict with keys:
        max_temp_c, min_temp_c, precipitation_mm, wind_speed_max_kmh
    """
    temp    = _parse_hourly_series(hourly, "temperature_2m",  forecast_hours)
    precip  = _parse_hourly_series(hourly, "precipitation",   forecast_hours)
    # Use gusts as the wind-speed maximum — more relevant for structural risk
    gusts   = _parse_hourly_series(hourly, "windgusts_10m",   forecast_hours)
    wind    = _parse_hourly_series(hourly, "windspeed_10m",   forecast_hours)

    if not temp:
        raise WeatherFetchError(
            "Open-Meteo returned no usable temperature_2m values"
        )

    max_temp  = max(temp)
    min_temp  = min(temp)
    total_precip = sum(precip) if precip else 0.0
    # Prefer gusts for peak wind; fall back to sustained windspeed
    peak_wind = max(gusts) if gusts else (max(wind) if wind else 0.0)

    return {
        "max_temp_c":         max_temp,
        "min_temp_c":         min_temp,
        "precipitation_mm":   total_precip,
        "wind_speed_max_kmh": peak_wind,
    }


def _build_url(lat: float, lon: float, forecast_hours: int) -> str:
    """Build the Open-Meteo request URL for the given location and window."""
    # Open-Meteo uses `forecast_days`; we convert hours → days (ceiling)
    forecast_days = math.ceil(forecast_hours / 24)
    # Minimum 1 day, maximum 16 days (API limit)
    forecast_days = max(1, min(16, forecast_days))

    params = {
        "latitude":      round(lat, 4),
        "longitude":     round(lon, 4),
        "hourly":        ",".join(_HOURLY_VARIABLES),
        "forecast_days": forecast_days,
        "timezone":      "UTC",
        "timeformat":    "unixtime",
    }
    return f"{_BASE_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def fetch_weather(
    lat: float,
    lon: float,
    *,
    forecast_hours: int = 72,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    http_client: Optional[HttpClient] = None,
    classifier_config: Optional[StormClassifierConfig] = None,
) -> RawWeatherObservation:
    """
    Fetch a weather forecast from Open-Meteo and return a
    ``RawWeatherObservation`` ready for the normalisation layer.

    Args:
        lat:               Latitude in decimal degrees.
        lon:               Longitude in decimal degrees.
        forecast_hours:    Number of hours to aggregate over (default 72).
                           Rounded up to the nearest whole day for the API
                           request; only the first ``forecast_hours`` hourly
                           values are used in aggregation.
        timeout_s:         HTTP request timeout in seconds (default 10).
        http_client:       Injectable HTTP client (default: production urllib
                           client).  Pass a stub in tests.
        classifier_config: Storm classification thresholds (default:
                           ``DEFAULT_CLASSIFIER_CONFIG``).

    Returns:
        ``RawWeatherObservation`` populated from the API response.

    Raises:
        ``WeatherFetchError`` on any network, HTTP, or parsing failure.
    """
    client = http_client or DEFAULT_HTTP_CLIENT
    config = classifier_config or DEFAULT_CLASSIFIER_CONFIG

    url = _build_url(lat, lon, forecast_hours)

    # --- Fetch ---
    data = client.get(url, timeout_s=timeout_s)

    # --- Parse ---
    hourly = _require_key(data, "hourly", "root")
    agg = _aggregate(hourly, forecast_hours)

    storm_level = classify_storm_level(
        max_temp_c=agg["max_temp_c"],
        min_temp_c=agg["min_temp_c"],
        precipitation_mm=agg["precipitation_mm"],
        wind_speed_max_kmh=agg["wind_speed_max_kmh"],
        config=config,
    )

    return RawWeatherObservation(
        max_temp_c=round(agg["max_temp_c"], 1),
        min_temp_c=round(agg["min_temp_c"], 1),
        precipitation_mm=round(agg["precipitation_mm"], 1),
        wind_speed_max_kmh=round(agg["wind_speed_max_kmh"], 1),
        storm_warning_level=storm_level,
        forecast_hours=forecast_hours,
    )


def fetch_weather_with_fallback(
    lat: float,
    lon: float,
    fallback: RawWeatherObservation,
    *,
    forecast_hours: int = 72,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    http_client: Optional[HttpClient] = None,
    classifier_config: Optional[StormClassifierConfig] = None,
) -> tuple[RawWeatherObservation, bool]:
    """
    Attempt to fetch live weather; return the fallback on any failure.

    Args:
        lat, lon:   Asset location.
        fallback:   ``RawWeatherObservation`` to use if the fetch fails
                    (typically the asset's last-known static weather data).
        ...         Same kwargs as ``fetch_weather``.

    Returns:
        ``(observation, live)`` where ``live`` is True if the observation
        came from the API, False if the fallback was used.
    """
    try:
        obs = fetch_weather(
            lat, lon,
            forecast_hours=forecast_hours,
            timeout_s=timeout_s,
            http_client=http_client,
            classifier_config=classifier_config,
        )
        return obs, True
    except WeatherFetchError:
        return fallback, False
