"""
GridGuard weather package.

Fetches Open-Meteo forecast data and converts it to a
``RawWeatherObservation`` that the normalisation layer already understands.

Public API
----------
    fetch_weather(lat, lon, *, forecast_hours=72, http_client=None) -> RawWeatherObservation
    WeatherFetchError   — raised when the API cannot be reached or returns bad data
    DEFAULT_HTTP_CLIENT — the production urllib-based client (passable to normalise callers)
"""

from .open_meteo import fetch_weather, WeatherFetchError, DEFAULT_HTTP_CLIENT

__all__ = ["fetch_weather", "WeatherFetchError", "DEFAULT_HTTP_CLIENT"]
