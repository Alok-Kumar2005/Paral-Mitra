"""NASA FIRMS (Fire Information for Resource Management System) active fire connector.

Fetches NRT active fire satellite detections (VIIRS / MODIS) as CSV for a specified
bounding box covering Punjab and Haryana, parses the records, filters by confidence,
and assigns spatial grid cells.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import os
from datetime import date
import logging
from typing import Sequence

import httpx
from dotenv import load_dotenv

load_dotenv()

from src.common.models import Hotspot
from src.engine.geo import get_grid_cell_id

logger = logging.getLogger(__name__)

# Default bounding box covering Punjab, Haryana, and contiguous agricultural zones
# Format: (west_lon, south_lat, east_lon, north_lat)
DEFAULT_PUNJAB_HARYANA_BBOX: tuple[float, float, float, float] = (73.5, 27.5, 77.8, 32.6)

DEFAULT_VIIRS_SOURCE: str = "VIIRS_NOAA20_NRT"

CONFIDENCE_RANK = {
    "l": 1,
    "low": 1,
    "n": 2,
    "nominal": 2,
    "h": 3,
    "high": 3,
}


class FirmsError(Exception):
    """Base exception for NASA FIRMS connector errors."""


class FirmsAuthError(FirmsError):
    """Authentication or invalid MAP_KEY error."""


class FirmsApiError(FirmsError):
    """General FIRMS API response or network error."""


def _is_confidence_acceptable(conf_raw: str, min_confidence: str = "nominal") -> bool:
    """Checks if detection confidence meets or exceeds min_confidence threshold."""
    min_rank = CONFIDENCE_RANK.get(min_confidence.strip().lower(), 2)
    val = conf_raw.strip().lower()

    if val in CONFIDENCE_RANK:
        return CONFIDENCE_RANK[val] >= min_rank

    # Handle numerical confidence percentages (e.g. MODIS 0-100)
    try:
        num = float(val.rstrip("%"))
        if min_rank <= 1:
            return True
        elif min_rank == 2:
            return num >= 30.0
        else:
            return num >= 80.0
    except ValueError:
        # Default to accepting if unknown string format, unless low
        return "low" not in val and val != "l"


def parse_firms_csv(csv_text: str, min_confidence: str = "nominal") -> list[Hotspot]:
    """Parses raw CSV response from NASA FIRMS API into a list of Hotspot domain models.
    
    Args:
        csv_text: Raw CSV string from FIRMS API.
        min_confidence: Minimum confidence string ("low", "nominal", "high").
        
    Returns:
        List of Hotspot domain objects with assigned 0.1-degree grid cells.
        
    Raises:
        FirmsAuthError: If the response indicates an invalid or missing MAP_KEY.
        FirmsApiError: If the response indicates an API rate limit or error string.
    """
    stripped = csv_text.strip()
    if not stripped:
        return []

    # Check for known plain-text error responses from FIRMS API
    lower_first_line = stripped.splitlines()[0].lower()
    if "invalid map_key" in lower_first_line or "invalid key" in lower_first_line or "bad map key" in lower_first_line:
        raise FirmsAuthError(f"NASA FIRMS authentication failed: {stripped}")
    if "transaction limit" in lower_first_line or "rate limit" in lower_first_line:
        raise FirmsApiError(f"NASA FIRMS rate limit exceeded: {stripped}")
    if "error" in lower_first_line and not ("," in lower_first_line or "latitude" in lower_first_line):
        raise FirmsApiError(f"NASA FIRMS API error: {stripped}")

    reader = csv.DictReader(io.StringIO(stripped))
    if not reader.fieldnames:
        return []

    required_cols = {"latitude", "longitude", "acq_date"}
    actual_cols = {col.lower() for col in reader.fieldnames if col}
    if not required_cols.issubset(actual_cols):
        # If response doesn't look like CSV with required columns
        raise FirmsApiError(f"Unexpected CSV format from NASA FIRMS. Columns found: {reader.fieldnames}")

    hotspots: list[Hotspot] = []

    for row in reader:
        # Case-insensitive column lookup
        normalized_row = {k.lower(): v for k, v in row.items() if k}
        lat_str = normalized_row.get("latitude")
        lon_str = normalized_row.get("longitude")
        acq_date_str = normalized_row.get("acq_date")
        frp_str = normalized_row.get("frp", "0.0")
        conf_str = normalized_row.get("confidence", "nominal")

        if not (lat_str and lon_str and acq_date_str):
            continue

        if not _is_confidence_acceptable(conf_str, min_confidence=min_confidence):
            continue

        try:
            lat = float(lat_str)
            lon = float(lon_str)
            acq_dt = date.fromisoformat(acq_date_str)
            frp = float(frp_str) if frp_str else 0.0
            grid_cell = get_grid_cell_id(lat, lon, grid_size=0.1)

            hotspots.append(
                Hotspot(
                    grid_cell=grid_cell,
                    lat=lat,
                    lon=lon,
                    acq_date=acq_dt,
                    frp=max(0.0, frp),
                    confidence=conf_str,
                )
            )
        except (ValueError, TypeError) as exc:
            logger.warning("Skipping invalid FIRMS row %s: %s", row, exc)
            continue

    return hotspots


class FirmsClient:
    """HTTP client for NASA FIRMS REST API with retry resilience."""

    def __init__(
        self,
        map_key: str | None = None,
        base_url: str = "https://firms.modaps.eosdis.nasa.gov",
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.map_key = map_key or os.getenv("FIRMS_MAP_KEY", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self._external_client = client

    async def fetch_active_fires(
        self,
        days: int = 1,
        source: str = DEFAULT_VIIRS_SOURCE,
        area_bbox: tuple[float, float, float, float] = DEFAULT_PUNJAB_HARYANA_BBOX,
        min_confidence: str = "nominal",
    ) -> list[Hotspot]:
        """Fetches active fire detections for a bounding box over the last N days.
        
        Args:
            days: Day range between 1 and 10.
            source: Satellite sensor product (default VIIRS_NOAA20_NRT).
            area_bbox: Bounding box tuple (west, south, east, north).
            min_confidence: Minimum confidence threshold ("low", "nominal", "high").
            
        Returns:
            List of parsed Hotspot objects.
            
        Raises:
            FirmsAuthError: If map_key is missing or rejected.
            FirmsApiError: If request fails after retries or API errors out.
        """
        if not self.map_key:
            raise FirmsAuthError("NASA FIRMS MAP_KEY is not configured. Set FIRMS_MAP_KEY environment variable.")

        if not (1 <= days <= 10):
            raise ValueError(f"FIRMS API day range must be between 1 and 10, got: {days}")

        west, south, east, north = area_bbox
        area_str = f"{west},{south},{east},{north}"
        endpoint = f"{self.base_url}/api/area/csv/{self.map_key}/{source}/{area_str}/{days}"

        headers = {
            "User-Agent": "ParaliMitra/1.0 (Stubble Burning Management System; contact: info@paralimitra.in)",
            "Accept": "text/csv, text/plain",
        }

        async def _execute_request(http_client: httpx.AsyncClient) -> httpx.Response:
            last_error: Exception | None = None
            for attempt in range(1, self.max_retries + 1):
                try:
                    resp = await http_client.get(endpoint, headers=headers, timeout=self.timeout)
                    if resp.status_code == 401 or resp.status_code == 403:
                        raise FirmsAuthError(f"FIRMS authentication failed with HTTP {resp.status_code}: {resp.text}")
                    if resp.status_code == 429 or resp.status_code >= 500:
                        if attempt < self.max_retries:
                            await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                            continue
                        raise FirmsApiError(f"FIRMS API failed with status {resp.status_code}: {resp.text}")
                    resp.raise_for_status()
                    return resp
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_error = exc
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                        continue
                    raise FirmsApiError(f"FIRMS network error after {self.max_retries} attempts: {exc}") from exc

            raise FirmsApiError(f"FIRMS request failed: {last_error}")

        if self._external_client:
            response = await _execute_request(self._external_client)
        else:
            async with httpx.AsyncClient() as client:
                response = await _execute_request(client)

        return parse_firms_csv(response.text, min_confidence=min_confidence)


async def main(args: Sequence[str] | None = None) -> None:
    """CLI runner for testing NASA FIRMS fire detection fetcher."""
    parser = argparse.ArgumentParser(description="Fetch NASA FIRMS active fire hotspots for Punjab/Haryana.")
    parser.add_argument("--days", type=int, default=1, help="Day range (1-10)")
    parser.add_argument("--source", type=str, default=DEFAULT_VIIRS_SOURCE, help="VIIRS sensor source")
    parser.add_argument("--min-confidence", type=str, default="nominal", choices=["low", "nominal", "high"])
    parser.add_argument("--key", type=str, default=None, help="FIRMS MAP_KEY (defaults to FIRMS_MAP_KEY env)")
    parsed = parser.parse_args(args)

    client = FirmsClient(map_key=parsed.key)
    try:
        hotspots = await client.fetch_active_fires(
            days=parsed.days,
            source=parsed.source,
            min_confidence=parsed.min_confidence,
        )
        print(f"Successfully fetched {len(hotspots)} active fire hotspots.")
        for i, h in enumerate(hotspots[:5], start=1):
            print(f"  {i}. Cell: {h.grid_cell} | Lat/Lon: ({h.lat:.4f}, {h.lon:.4f}) | FRP: {h.frp:.1f} MW | Conf: {h.confidence} | Date: {h.acq_date}")
        if len(hotspots) > 5:
            print(f"  ... and {len(hotspots) - 5} more.")
    except Exception as exc:
        print(f"Error fetching FIRMS hotspots: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
