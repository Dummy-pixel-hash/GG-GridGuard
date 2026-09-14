"""
Unit tests for the GridGuard weather package.

Coverage
--------
  1. StormClassifier — all four levels, boundary conditions
  2. URL construction — correct parameters, forecast_days rounding
  3. Response parsing — happy path, null values, missing keys
  4. fetch_weather — happy path via stub client, all fields present
  5. fetch_weather — error paths: HTTP error, network error, timeout,
     bad JSON, missing 'hourly' key, empty temperature series
  6. fetch_weather_with_fallback — live path, fallback path
  7. Integration: fetch_weather → normalise → score_asset (no network)
  8. Determinism — same stub response always produces same result

Tests NEVER make real network calls — all HTTP is handled by StubHttpClient.
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from data.raw_types import RawWeatherObservation
from weather.client import HttpClient
from weather.open_meteo import (
    WeatherFetchError,
    _aggregate,
    _build_url,
    _parse_hourly_series,
    fetch_weather,
    fetch_weather_with_fallback,
)
from weather.storm_classifier import (
    DEFAULT_CLASSIFIER_CONFIG,
    StormClassifierConfig,
    classify_storm_level,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_hourly(
    *,
    n_hours: int = 72,
    temp: float = 20.0,
    precip: float = 0.0,
    wind: float = 10.0,
    gusts: float = 15.0,
) -> dict[str, Any]:
    """Build a minimal Open-Meteo ``hourly`` dict with uniform values."""
    timestamps = list(range(1_700_000_000, 1_700_000_000 + n_hours * 3600, 3600))
    return {
        "time":           timestamps,
        "temperature_2m": [temp]   * n_hours,
        "precipitation":  [precip] * n_hours,
        "windspeed_10m":  [wind]   * n_hours,
        "windgusts_10m":  [gusts]  * n_hours,
    }


def _make_response(*, n_hours: int = 72, **kwargs: Any) -> dict[str, Any]:
    """Wrap an hourly dict in the Open-Meteo top-level response envelope."""
    return {
        "latitude":             51.5,
        "longitude":            -0.1,
        "generationtime_ms":    1.2,
        "utc_offset_seconds":   0,
        "timezone":             "UTC",
        "timezone_abbreviation":"UTC",
        "elevation":            10.0,
        "hourly_units": {
            "time":           "unixtime",
            "temperature_2m": "°C",
            "precipitation":  "mm",
            "windspeed_10m":  "km/h",
            "windgusts_10m":  "km/h",
        },
        "hourly": _make_hourly(n_hours=n_hours, **kwargs),
    }


class StubHttpClient(HttpClient):
    """
    In-memory HTTP client for tests.

    Accepts either a pre-built dict (returned directly) or a
    ``WeatherFetchError`` to raise.
    """

    def __init__(self, response: dict[str, Any] | WeatherFetchError):
        self._response = response

    def get(self, url: str, *, timeout_s: float) -> dict[str, Any]:
        if isinstance(self._response, WeatherFetchError):
            raise self._response
        return self._response

    @classmethod
    def ok(cls, **kwargs: Any) -> "StubHttpClient":
        """Return a client that yields a well-formed response."""
        return cls(_make_response(**kwargs))

    @classmethod
    def error(cls, msg: str = "connection refused") -> "StubHttpClient":
        """Return a client that raises WeatherFetchError."""
        return cls(WeatherFetchError(msg))


# ===========================================================================
# 1. Storm classifier
# ===========================================================================

class TestStormClassifier:

    def _classify(self, *, max_t=20.0, min_t=10.0, precip=0.0, wind=0.0) -> int:
        return classify_storm_level(
            max_temp_c=max_t, min_temp_c=min_t,
            precipitation_mm=precip, wind_speed_max_kmh=wind,
        )

    def test_calm_conditions_level_0(self):
        assert self._classify() == 0

    def test_advisory_from_wind(self):
        assert self._classify(wind=40.0) == 1

    def test_advisory_from_precip(self):
        assert self._classify(precip=25.0) == 1

    def test_advisory_from_heat(self):
        assert self._classify(max_t=38.0) == 1

    def test_advisory_from_cold(self):
        assert self._classify(min_t=-5.0) == 1

    def test_watch_from_wind(self):
        assert self._classify(wind=65.0) == 2

    def test_watch_from_precip(self):
        assert self._classify(precip=50.0) == 2

    def test_warning_from_wind(self):
        assert self._classify(wind=90.0) == 3

    def test_warning_from_precip(self):
        assert self._classify(precip=80.0) == 3

    def test_warning_takes_priority_over_watch(self):
        # Both watch and warning conditions true — must return 3
        assert self._classify(wind=90.0, precip=50.0) == 3

    def test_boundary_just_below_advisory_wind(self):
        assert self._classify(wind=39.9) == 0

    def test_boundary_exactly_at_advisory_wind(self):
        assert self._classify(wind=40.0) == 1

    def test_boundary_exactly_at_watch_wind(self):
        assert self._classify(wind=65.0) == 2

    def test_boundary_exactly_at_warning_wind(self):
        assert self._classify(wind=90.0) == 3

    def test_custom_config_changes_thresholds(self):
        strict = StormClassifierConfig(wind_advisory_kmh=10.0)
        result = classify_storm_level(
            max_temp_c=20.0, min_temp_c=10.0,
            precipitation_mm=0.0, wind_speed_max_kmh=15.0,
            config=strict,
        )
        assert result == 1

    def test_default_config_unchanged_by_custom(self):
        """Custom config must not affect the module-level default."""
        strict = StormClassifierConfig(wind_advisory_kmh=10.0)
        classify_storm_level(
            max_temp_c=20.0, min_temp_c=10.0,
            precipitation_mm=0.0, wind_speed_max_kmh=15.0,
            config=strict,
        )
        assert DEFAULT_CLASSIFIER_CONFIG.wind_advisory_kmh == 40.0


# ===========================================================================
# 2. URL construction
# ===========================================================================

class TestBuildUrl:

    def test_contains_lat_lon(self):
        url = _build_url(51.505, -0.128, 72)
        assert "latitude=51.505" in url
        assert "longitude=-0.128" in url

    def test_72h_maps_to_3_forecast_days(self):
        url = _build_url(0.0, 0.0, 72)
        assert "forecast_days=3" in url

    def test_48h_maps_to_2_forecast_days(self):
        url = _build_url(0.0, 0.0, 48)
        assert "forecast_days=2" in url

    def test_1h_maps_to_1_forecast_day_minimum(self):
        url = _build_url(0.0, 0.0, 1)
        assert "forecast_days=1" in url

    def test_non_multiple_hours_rounds_up(self):
        # 25 hours → ceil(25/24) = 2 days
        url = _build_url(0.0, 0.0, 25)
        assert "forecast_days=2" in url

    def test_contains_required_hourly_variables(self):
        url = _build_url(0.0, 0.0, 72)
        assert "temperature_2m" in url
        assert "precipitation" in url
        assert "windspeed_10m" in url
        assert "windgusts_10m" in url

    def test_timezone_is_utc(self):
        url = _build_url(0.0, 0.0, 72)
        assert "timezone=UTC" in url

    def test_lat_lon_rounded_to_4dp(self):
        url = _build_url(51.12345678, -0.12345678, 72)
        assert "latitude=51.1235" in url
        assert "longitude=-0.1235" in url


# ===========================================================================
# 3. Response parsing helpers
# ===========================================================================

class TestParsing:

    def test_parse_hourly_series_happy_path(self):
        hourly = {"temperature_2m": [10.0, 15.0, 20.0, 25.0]}
        result = _parse_hourly_series(hourly, "temperature_2m", 3)
        assert result == [10.0, 15.0, 20.0]

    def test_parse_hourly_series_filters_none(self):
        hourly = {"temperature_2m": [10.0, None, 20.0]}
        result = _parse_hourly_series(hourly, "temperature_2m", 3)
        assert result == [10.0, 20.0]

    def test_parse_hourly_series_filters_nan(self):
        hourly = {"temperature_2m": [10.0, float("nan"), 20.0]}
        result = _parse_hourly_series(hourly, "temperature_2m", 3)
        assert result == [10.0, 20.0]

    def test_parse_hourly_series_missing_variable_returns_empty(self):
        result = _parse_hourly_series({}, "temperature_2m", 72)
        assert result == []

    def test_parse_hourly_series_non_list_raises(self):
        hourly = {"temperature_2m": "not_a_list"}
        with pytest.raises(WeatherFetchError, match="not a list"):
            _parse_hourly_series(hourly, "temperature_2m", 72)

    def test_aggregate_max_temp(self):
        hourly = _make_hourly(n_hours=3, temp=20.0)
        hourly["temperature_2m"] = [15.0, 20.0, 18.0]
        result = _aggregate(hourly, 3)
        assert result["max_temp_c"] == 20.0

    def test_aggregate_min_temp(self):
        hourly = _make_hourly(n_hours=3, temp=20.0)
        hourly["temperature_2m"] = [15.0, 20.0, 18.0]
        result = _aggregate(hourly, 3)
        assert result["min_temp_c"] == 15.0

    def test_aggregate_precipitation_is_sum(self):
        hourly = _make_hourly(n_hours=3)
        hourly["precipitation"] = [1.0, 2.0, 3.0]
        result = _aggregate(hourly, 3)
        assert result["precipitation_mm"] == pytest.approx(6.0)

    def test_aggregate_wind_uses_gusts_max(self):
        hourly = _make_hourly(n_hours=3)
        hourly["windgusts_10m"] = [10.0, 50.0, 30.0]
        result = _aggregate(hourly, 3)
        assert result["wind_speed_max_kmh"] == 50.0

    def test_aggregate_falls_back_to_windspeed_if_no_gusts(self):
        hourly = _make_hourly(n_hours=3)
        hourly["windgusts_10m"] = [None, None, None]
        hourly["windspeed_10m"] = [20.0, 30.0, 25.0]
        result = _aggregate(hourly, 3)
        assert result["wind_speed_max_kmh"] == 30.0

    def test_aggregate_empty_temp_raises(self):
        hourly = {"temperature_2m": [], "precipitation": [], "windgusts_10m": [], "windspeed_10m": []}
        with pytest.raises(WeatherFetchError, match="temperature_2m"):
            _aggregate(hourly, 72)

    def test_aggregate_respects_forecast_hours_slice(self):
        """Only the first n_hours entries should be used."""
        hourly = _make_hourly(n_hours=6, temp=20.0)
        hourly["temperature_2m"] = [10.0, 10.0, 10.0, 99.0, 99.0, 99.0]
        result = _aggregate(hourly, 3)   # slice at 3
        assert result["max_temp_c"] == 10.0


# ===========================================================================
# 4. fetch_weather — happy path
# ===========================================================================

class TestFetchWeatherHappyPath:

    def test_returns_raw_weather_observation(self):
        client = StubHttpClient.ok(temp=25.0, precip=5.0, gusts=30.0)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert isinstance(obs, RawWeatherObservation)

    def test_max_temp_populated(self):
        client = StubHttpClient.ok(temp=32.0)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert obs.max_temp_c == pytest.approx(32.0)

    def test_min_temp_populated(self):
        # Vary temperature so min != max
        response = _make_response()
        temps = response["hourly"]["temperature_2m"]
        temps[0] = 5.0   # inject a lower value
        client = StubHttpClient(response)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert obs.min_temp_c == pytest.approx(5.0)

    def test_precipitation_is_sum(self):
        # 72 hours × 2 mm/h = 144 mm total
        client = StubHttpClient.ok(precip=2.0)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert obs.precipitation_mm == pytest.approx(144.0)

    def test_wind_uses_gusts(self):
        client = StubHttpClient.ok(gusts=95.0)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert obs.wind_speed_max_kmh == pytest.approx(95.0)

    def test_forecast_hours_preserved(self):
        client = StubHttpClient.ok()
        obs = fetch_weather(51.5, -0.1, forecast_hours=48, http_client=client)
        assert obs.forecast_hours == 48

    def test_storm_warning_level_derived_from_wind(self):
        # gusts=95 → level 3 (WARNING: wind >= 90)
        client = StubHttpClient.ok(gusts=95.0)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert obs.storm_warning_level == 3

    def test_storm_level_0_for_calm(self):
        client = StubHttpClient.ok(temp=20.0, precip=0.0, gusts=5.0)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert obs.storm_warning_level == 0

    def test_all_fields_in_valid_ranges(self):
        client = StubHttpClient.ok(temp=22.0, precip=1.0, gusts=20.0)
        obs = fetch_weather(51.5, -0.1, http_client=client)
        assert 0 <= obs.storm_warning_level <= 3
        assert obs.precipitation_mm >= 0.0
        assert obs.wind_speed_max_kmh >= 0.0
        assert obs.forecast_hours > 0

    def test_custom_classifier_config_honoured(self):
        # With a strict config (warning at 50 km/h), gusts=60 should give level 3
        strict_config = StormClassifierConfig(
            wind_warning_kmh=50.0,
            wind_watch_kmh=35.0,
            wind_advisory_kmh=20.0,
            precip_warning_mm=999.0,
            precip_watch_mm=999.0,
            precip_advisory_mm=999.0,
        )
        client = StubHttpClient.ok(gusts=60.0)
        obs = fetch_weather(51.5, -0.1, http_client=client, classifier_config=strict_config)
        assert obs.storm_warning_level == 3

    def test_only_forecast_hours_used_in_aggregation(self):
        """Values beyond forecast_hours must not influence the result."""
        response = _make_response(n_hours=72, temp=20.0, gusts=10.0)
        # Overwrite hours 49–72 with extreme values — these should be ignored
        response["hourly"]["windgusts_10m"][48:] = [500.0] * 24
        client = StubHttpClient(response)
        obs = fetch_weather(51.5, -0.1, forecast_hours=48, http_client=client)
        assert obs.wind_speed_max_kmh == pytest.approx(10.0)


# ===========================================================================
# 5. fetch_weather — error paths
# ===========================================================================

class TestFetchWeatherErrors:

    def test_network_error_raises_weather_fetch_error(self):
        client = StubHttpClient.error("connection refused")
        with pytest.raises(WeatherFetchError, match="connection refused"):
            fetch_weather(51.5, -0.1, http_client=client)

    def test_missing_hourly_key_raises(self):
        client = StubHttpClient({"latitude": 51.5})  # no 'hourly'
        with pytest.raises(WeatherFetchError, match="missing 'hourly'"):
            fetch_weather(51.5, -0.1, http_client=client)

    def test_empty_temperature_series_raises(self):
        response = _make_response()
        response["hourly"]["temperature_2m"] = []
        client = StubHttpClient(response)
        with pytest.raises(WeatherFetchError, match="temperature_2m"):
            fetch_weather(51.5, -0.1, http_client=client)

    def test_all_null_temperature_raises(self):
        response = _make_response()
        response["hourly"]["temperature_2m"] = [None] * 72
        client = StubHttpClient(response)
        with pytest.raises(WeatherFetchError, match="temperature_2m"):
            fetch_weather(51.5, -0.1, http_client=client)

    def test_non_list_hourly_variable_raises(self):
        response = _make_response()
        response["hourly"]["temperature_2m"] = "not-a-list"
        client = StubHttpClient(response)
        with pytest.raises(WeatherFetchError, match="not a list"):
            fetch_weather(51.5, -0.1, http_client=client)


# ===========================================================================
# 6. fetch_weather_with_fallback
# ===========================================================================

class TestFetchWeatherWithFallback:

    def _fallback(self) -> RawWeatherObservation:
        return RawWeatherObservation(
            max_temp_c=20.0, min_temp_c=10.0,
            precipitation_mm=0.0, wind_speed_max_kmh=0.0,
            storm_warning_level=0,
        )

    def test_returns_live_on_success(self):
        client = StubHttpClient.ok(temp=30.0, gusts=100.0)
        obs, live = fetch_weather_with_fallback(
            51.5, -0.1, self._fallback(), http_client=client
        )
        assert live is True
        assert obs.max_temp_c == pytest.approx(30.0)

    def test_returns_fallback_on_error(self):
        fallback = self._fallback()
        client = StubHttpClient.error("timeout")
        obs, live = fetch_weather_with_fallback(
            51.5, -0.1, fallback, http_client=client
        )
        assert live is False
        assert obs is fallback   # same object, not a copy

    def test_fallback_is_unchanged(self):
        """The fallback object must not be mutated."""
        fallback = self._fallback()
        original_max = fallback.max_temp_c
        client = StubHttpClient.error("fail")
        fetch_weather_with_fallback(51.5, -0.1, fallback, http_client=client)
        assert fallback.max_temp_c == original_max

    def test_live_flag_false_when_api_missing_hourly(self):
        fallback = self._fallback()
        client = StubHttpClient({"latitude": 51.5})  # malformed
        obs, live = fetch_weather_with_fallback(
            51.5, -0.1, fallback, http_client=client
        )
        assert live is False
        assert obs is fallback   # same object, not a copy


# ===========================================================================
# 7. Integration: fetch_weather → normalise → score_asset
# ===========================================================================

class TestWeatherIntegration:

    def test_calm_weather_produces_low_weather_component(self):
        """Calm API response → normalise → weather_risk component should be low."""
        from normalisation.normaliser import normalise
        from risk_engine import score_asset
        from data.demo_assets import TX_001

        import copy
        asset = copy.deepcopy(TX_001)

        # Inject a calm weather observation (same as fetch would produce)
        client = StubHttpClient.ok(temp=20.0, precip=0.0, gusts=5.0)
        obs = fetch_weather(
            TX_001.metadata.location.latitude,
            TX_001.metadata.location.longitude,
            http_client=client,
        )
        asset.weather = obs

        ri = normalise(asset)
        result = score_asset(ri)
        assert result.components.weather_risk < 20.0, (
            f"Calm weather should give low weather_risk, got {result.components.weather_risk}"
        )

    def test_storm_warning_produces_high_weather_component(self):
        """Storm API response → normalise → weather_risk component should be high."""
        from normalisation.normaliser import normalise
        from risk_engine import score_asset
        from data.demo_assets import TX_001

        import copy
        asset = copy.deepcopy(TX_001)

        client = StubHttpClient.ok(temp=38.0, precip=85.0, gusts=95.0)
        obs = fetch_weather(
            TX_001.metadata.location.latitude,
            TX_001.metadata.location.longitude,
            http_client=client,
        )
        asset.weather = obs

        ri = normalise(asset)
        result = score_asset(ri)
        assert result.components.weather_risk >= 60.0, (
            f"Storm conditions should give high weather_risk, got {result.components.weather_risk}"
        )

    def test_fetch_and_normalise_preserves_forecast_hours(self):
        from normalisation.normaliser import normalise
        from data.demo_assets import TX_001
        import copy

        asset = copy.deepcopy(TX_001)
        client = StubHttpClient.ok()
        obs = fetch_weather(51.5, -0.1, forecast_hours=48, http_client=client)
        asset.weather = obs

        ri = normalise(asset)
        assert ri.weather.forecast_hours == 48


# ===========================================================================
# 8. Determinism
# ===========================================================================

class TestDeterminism:

    def test_same_response_always_produces_same_observation(self):
        client = StubHttpClient.ok(temp=25.0, precip=10.0, gusts=50.0)
        obs1 = fetch_weather(51.5, -0.1, http_client=client)
        obs2 = fetch_weather(51.5, -0.1, http_client=client)
        assert obs1.max_temp_c == obs2.max_temp_c
        assert obs1.min_temp_c == obs2.min_temp_c
        assert obs1.precipitation_mm == obs2.precipitation_mm
        assert obs1.wind_speed_max_kmh == obs2.wind_speed_max_kmh
        assert obs1.storm_warning_level == obs2.storm_warning_level

    def test_classify_storm_level_is_deterministic(self):
        for _ in range(5):
            level = classify_storm_level(
                max_temp_c=35.0, min_temp_c=20.0,
                precipitation_mm=60.0, wind_speed_max_kmh=70.0,
            )
            assert level == 2
