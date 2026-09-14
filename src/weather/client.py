"""
Thin HTTP client abstraction for the Open-Meteo weather fetcher.

Why a wrapper instead of calling urllib directly?
-------------------------------------------------
Tests need to inject fake responses without monkey-patching global stdlib
state.  Passing an ``HttpClient`` instance lets tests supply a
``StubHttpClient`` that returns pre-canned JSON without making any network
calls.  Production code uses ``UrllibHttpClient`` (the default).

Interface contract
------------------
    client.get(url: str, *, timeout_s: float) -> dict
        - Performs a GET request to ``url``.
        - Raises ``WeatherFetchError`` on network error, timeout, or any
          non-200 HTTP response.
        - Returns the parsed JSON body as a plain dict.
        - ``timeout_s`` is honoured on a best-effort basis (the urllib
          implementation passes it directly to ``urlopen``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any


class HttpClient(ABC):
    """Abstract HTTP client — get(url) -> dict."""

    @abstractmethod
    def get(self, url: str, *, timeout_s: float) -> dict[str, Any]:
        """Perform a GET and return the parsed JSON body."""


class UrllibHttpClient(HttpClient):
    """
    Production HTTP client backed by the standard library's ``urllib``.

    Uses no third-party dependencies.  Raises ``WeatherFetchError``
    (imported lazily to avoid a circular import) on any failure.
    """

    def get(self, url: str, *, timeout_s: float) -> dict[str, Any]:
        # Import here to avoid circular dependency (open_meteo imports this module)
        from weather.open_meteo import WeatherFetchError  # noqa: PLC0415

        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as response:
                if response.status != 200:
                    raise WeatherFetchError(
                        f"Open-Meteo returned HTTP {response.status} for {url}"
                    )
                raw = response.read()
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise WeatherFetchError(
                f"HTTP {exc.code} from Open-Meteo: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise WeatherFetchError(
                f"Network error contacting Open-Meteo: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise WeatherFetchError(
                "Timed out waiting for Open-Meteo response"
            ) from exc
        except json.JSONDecodeError as exc:
            raise WeatherFetchError(
                f"Open-Meteo returned non-JSON body: {exc}"
            ) from exc


# Singleton production client — importable directly
DEFAULT_HTTP_CLIENT = UrllibHttpClient()
