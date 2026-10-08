"""Geocoding connector resolving village/district text to geographical coordinates.

Uses OpenStreetMap Nominatim as a fallback when farmer location pin is unavailable.
Strictly respects Nominatim Usage Policy with User-Agent identification, 1 req/sec rate limiting,
result caching, country-code restriction to India, and ambiguity detection.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any, Sequence
from pydantic import BaseModel, ConfigDict, Field

import httpx

from src.engine.geo import haversine_distance

logger = logging.getLogger(__name__)

NOMINATIM_BASE_URL: str = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT: str = "ParaliMitra/1.0 (Residue Management Advisory; contact: info@paralimitra.in)"


class GeocodingError(Exception):
    """Base exception for geocoding connector errors."""


class NominatimApiError(GeocodingError):
    """Nominatim API failure or network error."""


class GeocodeResult(BaseModel):
    """Structured geocoding result."""
    model_config = ConfigDict(extra="ignore")

    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude")
    display_name: str = Field(..., description="Full descriptive address name")
    village: str | None = Field(default=None, description="Village or town name if detected")
    district: str | None = Field(default=None, description="District or county name")
    state: str | None = Field(default=None, description="State name (e.g. Punjab, Haryana)")
    importance: float = Field(default=0.0, description="Nominatim relevance importance score")


class RateLimiter:
    """Thread/asyncio-safe rate limiter enforcing minimum time between requests."""

    def __init__(self, min_interval_seconds: float = 1.0) -> None:
        self.min_interval = min_interval_seconds
        self._last_call_time: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_time
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_call_time = time.monotonic()


def _normalize_query_key(query: str) -> str:
    """Normalizes query text for cache indexing."""
    return " ".join(query.strip().lower().split())


def parse_nominatim_results(
    results: list[dict[str, Any]],
    ambiguity_distance_threshold_km: float = 40.0,
) -> GeocodeResult | None:
    """Parses Nominatim search response items and checks for ambiguity.
    
    Returns None if:
    - No matches are found.
    - Multiple matches exist in completely different locations (> threshold km) with similar importance.
    - The top match has negligible relevance confidence.
    """
    if not results or not isinstance(results, list):
        return None

    valid_candidates: list[dict[str, Any]] = []
    for r in results:
        try:
            lat = float(r["lat"])
            lon = float(r["lon"])
            importance = float(r.get("importance", 0.0))
            valid_candidates.append({**r, "_lat": lat, "_lon": lon, "_importance": importance})
        except (KeyError, ValueError, TypeError):
            continue

    if not valid_candidates:
        return None

    # Sort candidates by importance descending
    valid_candidates.sort(key=lambda x: x["_importance"], reverse=True)

    top = valid_candidates[0]

    # If multiple candidates, check for geographic ambiguity
    if len(valid_candidates) > 1:
        second = valid_candidates[1]
        dist_between_top_two = haversine_distance(top["_lat"], top["_lon"], second["_lat"], second["_lon"])
        importance_diff = top["_importance"] - second["_importance"]

        # If the two top locations are far apart and have very similar importance, it's ambiguous
        if dist_between_top_two > ambiguity_distance_threshold_km and importance_diff < 0.10:
            logger.info(
                "Ambiguous geocoding for candidates: '%s' vs '%s' (dist=%.1f km, diff=%.3f)",
                top.get("display_name"),
                second.get("display_name"),
                dist_between_top_two,
                importance_diff,
            )
            return None

    address = top.get("address", {})
    village = (
        address.get("village")
        or address.get("town")
        or address.get("hamlet")
        or address.get("suburb")
        or address.get("city")
    )
    district = (
        address.get("state_district")
        or address.get("county")
        or address.get("district")
    )
    state = address.get("state")

    return GeocodeResult(
        lat=top["_lat"],
        lon=top["_lon"],
        display_name=top.get("display_name", ""),
        village=village,
        district=district,
        state=state,
        importance=top["_importance"],
    )


class Geocoder:
    """Async Nominatim geocoder with rate-limiting, caching, and ambiguity filtering."""

    def __init__(
        self,
        base_url: str = NOMINATIM_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        min_request_interval: float = 1.0,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.user_agent = user_agent
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.rate_limiter = RateLimiter(min_interval_seconds=min_request_interval)
        self.cache: dict[str, GeocodeResult | None] = {}
        self._external_client = client

    async def geocode(self, query: str) -> GeocodeResult | None:
        """Resolves location query text to coordinates in India.
        
        Args:
            query: Village, town, or district search query (e.g. "Nabha, Patiala").
            
        Returns:
            GeocodeResult if successfully and unambiguously resolved; None if ambiguous or not found.
            
        Raises:
            NominatimApiError: If unrecoverable network or API error occurs.
        """
        normalized_query = _normalize_query_key(query)
        if not normalized_query:
            return None

        # Check in-memory cache first
        if normalized_query in self.cache:
            return self.cache[normalized_query]

        params = {
            "q": query.strip(),
            "format": "jsonv2",
            "countrycodes": "in",
            "limit": "5",
            "addressdetails": "1",
        }

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        async def _execute_request(http_client: httpx.AsyncClient) -> list[dict[str, Any]]:
            last_error: Exception | None = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    # Enforce Nominatim 1 req/sec policy
                    await self.rate_limiter.acquire()

                    resp = await http_client.get(
                        self.base_url,
                        params=params,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if resp.status_code == 429 or resp.status_code >= 500:
                        if attempt < self.max_retries:
                            await asyncio.sleep(1.0 * attempt)
                            continue
                        raise NominatimApiError(f"Nominatim returned HTTP {resp.status_code}: {resp.text}")
                    resp.raise_for_status()
                    return resp.json()
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        await asyncio.sleep(1.0 * attempt)
                        continue
                    raise NominatimApiError(f"Nominatim network error: {exc}") from exc
                except Exception as exc:
                    raise NominatimApiError(f"Nominatim query failed: {exc}") from exc

            raise NominatimApiError(f"Nominatim request failed: {last_error}")

        if self._external_client:
            raw_data = await _execute_request(self._external_client)
        else:
            async with httpx.AsyncClient() as client:
                raw_data = await _execute_request(client)

        result = parse_nominatim_results(raw_data)
        # Store in cache (including None for negative caching)
        self.cache[normalized_query] = result
        return result


async def main(args: Sequence[str] | None = None) -> None:
    """CLI runner for testing Nominatim geocoding."""
    parser = argparse.ArgumentParser(description="Geocode a village or district in India.")
    parser.add_argument("--query", type=str, default="Nabha, Patiala", help="Location text to resolve")
    parsed = parser.parse_args(args)

    geocoder = Geocoder()
    print(f"Resolving query: '{parsed.query}'...")
    try:
        res = await geocoder.geocode(parsed.query)
        if res:
            print("Successfully resolved location:")
            print(f"  Coordinates : ({res.lat:.4f}, {res.lon:.4f})")
            print(f"  Village/Town: {res.village}")
            print(f"  District    : {res.district}")
            print(f"  State       : {res.state}")
            print(f"  Full Address: {res.display_name}")
            print(f"  Importance  : {res.importance:.3f}")
        else:
            print("Location could not be unambiguously resolved (returned None). Please refine query.")
    except Exception as exc:
        print(f"Geocoding error: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
