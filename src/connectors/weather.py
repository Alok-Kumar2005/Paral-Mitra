"""Open-Meteo weather forecast connector for agricultural residue scheduling.

Fetches 10-day daily precipitation, rain probability, and maximum wind speed forecasts
for any given coordinate in Punjab, Haryana, or India without requiring an API key.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import logging
from typing import Any, Sequence

import httpx

from src.engine.models import DailyWeather, WeatherForecast

logger = logging.getLogger(__name__)

OPEN_METEO_BASE_URL: str = "https://api.open-meteo.com/v1/forecast"


class WeatherError(Exception):
    """Base exception for weather connector errors."""


class WeatherApiError(WeatherError):
    """Open-Meteo API response or network error."""


def parse_open_meteo_response(payload: dict[str, Any]) -> WeatherForecast:
    """Parses JSON response payload from Open-Meteo API into WeatherForecast model.
    
    Args:
        payload: Dict containing Open-Meteo daily forecast data.
        
    Returns:
        WeatherForecast domain model with DailyWeather records.
        
    Raises:
        WeatherApiError: If required payload structure is missing or malformed.
    """
    if "error" in payload and payload["error"]:
        reason = payload.get("reason", "Unknown Open-Meteo error")
        raise WeatherApiError(f"Open-Meteo API returned error: {reason}")

    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise WeatherApiError("Open-Meteo response is missing 'daily' forecast data block.")

    times: list[str] = daily.get("time", [])
    precip_sums: list[float | None] = daily.get("precipitation_sum", [])
    precip_probs: list[float | None] = daily.get("precipitation_probability_max", [])
    wind_maxs: list[float | None] = daily.get("wind_speed_10m_max", [])

    if not times:
        return WeatherForecast(forecasts=[])

    forecasts: list[DailyWeather] = []
    for i, time_str in enumerate(times):
        try:
            d = date.fromisoformat(time_str)
            precip = float(precip_sums[i]) if i < len(precip_sums) and precip_sums[i] is not None else 0.0
            prob = float(precip_probs[i]) if i < len(precip_probs) and precip_probs[i] is not None else 0.0
            wind = float(wind_maxs[i]) if i < len(wind_maxs) and wind_maxs[i] is not None else 0.0

            forecasts.append(
                DailyWeather(
                    date=d,
                    precipitation_mm=max(0.0, precip),
                    precipitation_probability_pct=min(100.0, max(0.0, prob)),
                    max_wind_kmh=max(0.0, wind),
                )
            )
        except (ValueError, TypeError, IndexError) as exc:
            logger.warning("Skipping invalid daily weather entry at index %d (%s): %s", i, time_str, exc)
            continue

    return WeatherForecast(forecasts=forecasts)


class WeatherClient:
    """Async client for Open-Meteo weather forecasting with automatic retries."""

    def __init__(
        self,
        base_url: str = OPEN_METEO_BASE_URL,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self._external_client = client

    async def fetch_forecast(
        self,
        lat: float,
        lon: float,
        forecast_days: int = 10,
        timezone: str = "auto",
    ) -> WeatherForecast:
        """Fetches daily forecast for the given latitude and longitude.
        
        Args:
            lat: Latitude (-90 to 90).
            lon: Longitude (-180 to 180).
            forecast_days: Number of forecast days (1 to 16, default 10).
            timezone: Timezone identifier (default 'auto').
            
        Returns:
            WeatherForecast object containing daily weather predictions.
            
        Raises:
            WeatherApiError: If request fails after all retries or response is invalid.
        """
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ValueError(f"Invalid coordinate bounds: lat={lat}, lon={lon}")

        if not (1 <= forecast_days <= 16):
            raise ValueError(f"forecast_days must be between 1 and 16, got: {forecast_days}")

        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "daily": "precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
            "forecast_days": str(forecast_days),
            "timezone": timezone,
        }

        headers = {
            "User-Agent": "ParaliMitra/1.0 (Agricultural Advisory System; contact: info@paralimitra.in)",
            "Accept": "application/json",
        }

        async def _execute_request(http_client: httpx.AsyncClient) -> dict[str, Any]:
            last_error: Exception | None = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    resp = await http_client.get(
                        self.base_url,
                        params=params,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        if attempt < self.max_retries:
                            await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                            continue
                        raise WeatherApiError(f"Open-Meteo returned status {resp.status_code}: {resp.text}")
                    resp.raise_for_status()
                    return resp.json()
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                        continue
                    raise WeatherApiError(f"Open-Meteo network error after {self.max_retries} attempts: {exc}") from exc
                except Exception as exc:
                    raise WeatherApiError(f"Open-Meteo parsing or HTTP failure: {exc}") from exc

            raise WeatherApiError(f"Open-Meteo request failed: {last_error}")

        if self._external_client:
            data = await _execute_request(self._external_client)
        else:
            async with httpx.AsyncClient() as client:
                data = await _execute_request(client)

        return parse_open_meteo_response(data)


async def main(args: Sequence[str] | None = None) -> None:
    """CLI runner for testing Open-Meteo forecast connector."""
    parser = argparse.ArgumentParser(description="Fetch Open-Meteo 10-day weather forecast.")
    parser.add_argument("--lat", type=float, default=30.3752, help="Latitude (e.g. 30.3752 for Nabha)")
    parser.add_argument("--lon", type=float, default=76.1471, help="Longitude (e.g. 76.1471 for Nabha)")
    parser.add_argument("--days", type=int, default=10, help="Forecast days (1-16, default 10)")
    parsed = parser.parse_args(args)

    client = WeatherClient()
    try:
        forecast = await client.fetch_forecast(lat=parsed.lat, lon=parsed.lon, forecast_days=parsed.days)
        print(f"Weather Forecast for ({parsed.lat:.4f}, {parsed.lon:.4f}) - {len(forecast.forecasts)} Days:")
        print("-" * 65)
        print(f"{'Date':<12} | {'Precipitation (mm)':<18} | {'Rain Chance (%)':<16} | {'Max Wind (km/h)':<15}")
        print("-" * 65)
        for f in forecast.forecasts:
            print(f"{f.date.isoformat():<12} | {f.precipitation_mm:<18.1f} | {f.precipitation_probability_pct:<16.0f} | {f.max_wind_kmh:<15.1f}")
    except Exception as exc:
        print(f"Error fetching weather forecast: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
