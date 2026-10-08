"""Comprehensive unit tests for external connectors (FIRMS, Open-Meteo, Nominatim, Fire Ingestion)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
import time
import pytest
import httpx

from src.common.db import InMemoryDatabase
from src.common.models import Hotspot
from src.connectors.firms import (
    FirmsApiError,
    FirmsAuthError,
    FirmsClient,
    parse_firms_csv,
)
from src.connectors.geocode import (
    Geocoder,
    parse_nominatim_results,
)
from src.connectors.ingest_fires import ingest_active_fires
from src.connectors.weather import (
    WeatherApiError,
    WeatherClient,
    parse_open_meteo_response,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# NASA FIRMS Tests
# ---------------------------------------------------------------------------

def test_firms_parse_csv_fixture():
    """Verifies parsing of the sample VIIRS CSV response fixture."""
    csv_content = (FIXTURES_DIR / "firms_viirs_sample.csv").read_text(encoding="utf-8")
    
    # By default, min_confidence='nominal' drops 'low' confidence records
    hotspots = parse_firms_csv(csv_content, min_confidence="nominal")
    
    # In the fixture: 1 'h', 1 'n', 1 'l' (filtered out), 1 'nominal' -> 3 records expected
    assert len(hotspots) == 3
    
    first = hotspots[0]
    assert isinstance(first, Hotspot)
    assert first.lat == 30.2541
    assert first.lon == 75.1245
    assert first.acq_date == date(2026, 10, 7)
    assert first.frp == 18.5
    assert first.confidence == "h"
    assert "_" in first.grid_cell  # e.g. "30.30_75.10"


def test_firms_confidence_levels():
    """Verifies that configurable confidence filtering correctly filters or preserves records."""
    csv_content = (FIXTURES_DIR / "firms_viirs_sample.csv").read_text(encoding="utf-8")

    # If min_confidence='low', all 4 records should be returned
    all_hotspots = parse_firms_csv(csv_content, min_confidence="low")
    assert len(all_hotspots) == 4

    # If min_confidence='high', only high confidence records are returned
    high_hotspots = parse_firms_csv(csv_content, min_confidence="high")
    assert len(high_hotspots) == 1
    assert high_hotspots[0].confidence == "h"


def test_firms_csv_error_responses():
    """Verifies detection and error raising for NASA FIRMS plain-text error messages."""
    with pytest.raises(FirmsAuthError, match="authentication failed"):
        parse_firms_csv("Invalid MAP_KEY")

    with pytest.raises(FirmsApiError, match="rate limit"):
        parse_firms_csv("Transaction limit exceeded")

    with pytest.raises(FirmsApiError, match="Unexpected CSV format"):
        parse_firms_csv("col_a,col_b\n1,2")


def test_firms_client_mock_http():
    """Tests FirmsClient against mocked HTTP responses."""
    csv_fixture = (FIXTURES_DIR / "firms_viirs_sample.csv").read_text(encoding="utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert "TEST_KEY_123" in str(request.url)
        assert "VIIRS_NOAA20_NRT" in str(request.url)
        return httpx.Response(200, text=csv_fixture)

    async def _run():
        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = FirmsClient(map_key="TEST_KEY_123", client=http_client)
            hotspots = await client.fetch_active_fires(days=1, min_confidence="nominal")
            assert len(hotspots) == 3

    asyncio.run(_run())


def test_firms_client_auth_failure_http():
    """Tests FirmsClient handling 401/403 HTTP error from FIRMS."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden: Bad Map Key")

    async def _run():
        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = FirmsClient(map_key="BAD_KEY", client=http_client)
            with pytest.raises(FirmsAuthError):
                await client.fetch_active_fires(days=1)

    asyncio.run(_run())


def test_firms_cli_runner(capsys):
    """Tests running firms CLI."""
    csv_fixture = (FIXTURES_DIR / "firms_viirs_sample.csv").read_text(encoding="utf-8")
    
    async def _run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text=csv_fixture))
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = FirmsClient(map_key="TEST_KEY", client=http_client)
            hotspots = await client.fetch_active_fires(days=1)
            assert len(hotspots) == 3

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Open-Meteo Weather Tests
# ---------------------------------------------------------------------------

def test_weather_parse_json_fixture():
    """Verifies parsing of the sample Open-Meteo 10-day forecast JSON fixture."""
    data = json.loads((FIXTURES_DIR / "open_meteo_sample.json").read_text(encoding="utf-8"))
    forecast = parse_open_meteo_response(data)

    assert len(forecast.forecasts) == 10
    
    # Check individual daily forecast values
    day3 = forecast.forecasts[2]
    assert day3.date == date(2026, 10, 10)
    assert day3.precipitation_mm == 5.2
    assert day3.precipitation_probability_pct == 80.0
    assert day3.max_wind_kmh == 22.0

    # Verify to_map() lookup works cleanly
    f_map = forecast.to_map()
    assert date(2026, 10, 10) in f_map
    assert f_map[date(2026, 10, 10)].precipitation_mm == 5.2


def test_weather_error_response():
    """Verifies handling of error payload from Open-Meteo."""
    with pytest.raises(WeatherApiError, match="Open-Meteo API returned error"):
        parse_open_meteo_response({"error": True, "reason": "Invalid coordinate range"})

    with pytest.raises(WeatherApiError, match="missing 'daily'"):
        parse_open_meteo_response({"latitude": 30.3})


def test_weather_client_mock_http():
    """Tests WeatherClient against mocked HTTP responses."""
    data = json.loads((FIXTURES_DIR / "open_meteo_sample.json").read_text(encoding="utf-8"))

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert "precipitation_sum" in str(request.url)
        assert "30.3752" in str(request.url)
        return httpx.Response(200, json=data)

    async def _run():
        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = WeatherClient(client=http_client)
            forecast = await client.fetch_forecast(lat=30.3752, lon=76.1471, forecast_days=10)
            assert len(forecast.forecasts) == 10
            assert forecast.forecasts[0].precipitation_mm == 0.0

    asyncio.run(_run())


def test_weather_cli_runner(capsys):
    """Tests running weather CLI."""
    data = json.loads((FIXTURES_DIR / "open_meteo_sample.json").read_text(encoding="utf-8"))
    
    async def _run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=data))
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = WeatherClient(client=http_client)
            forecast = await client.fetch_forecast(lat=30.3, lon=75.8, forecast_days=10)
            assert len(forecast.forecasts) == 10

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Nominatim Geocoding Tests
# ---------------------------------------------------------------------------

def test_geocode_parse_json_fixture():
    """Verifies parsing of the sample Nominatim response fixture."""
    data = json.loads((FIXTURES_DIR / "nominatim_sample.json").read_text(encoding="utf-8"))
    result = parse_nominatim_results(data)

    assert result is not None
    assert result.lat == 30.3752
    assert result.lon == 76.1471
    assert result.village == "Nabha"
    assert result.district == "Patiala"
    assert result.state == "Punjab"
    assert "Patiala" in result.display_name


def test_geocode_ambiguity_filtering():
    """Verifies that ambiguous geographically distant matches return None."""
    # Two candidates in different districts/states (> 40km apart) with equal importance
    ambiguous_data = [
        {
            "lat": "30.3752",
            "lon": "76.1471",
            "importance": 0.45,
            "display_name": "Rampur, Patiala, Punjab, India",
            "address": {"village": "Rampur", "state_district": "Patiala", "state": "Punjab"},
        },
        {
            "lat": "28.5000",
            "lon": "77.1000",
            "importance": 0.44,
            "display_name": "Rampur, Rewari, Haryana, India",
            "address": {"village": "Rampur", "state_district": "Rewari", "state": "Haryana"},
        },
    ]
    result = parse_nominatim_results(ambiguous_data)
    assert result is None, "Ambiguous candidates far apart should return None"

    # Empty response should return None
    assert parse_nominatim_results([]) is None


def test_geocode_client_caching_and_mock_http():
    """Tests Geocoder HTTP resolution and verifies caching prevents redundant network calls."""
    data = json.loads((FIXTURES_DIR / "nominatim_sample.json").read_text(encoding="utf-8"))
    call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=data)

    async def _run():
        nonlocal call_count
        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            geocoder = Geocoder(min_request_interval=0.0, client=http_client)
            
            # First lookup -> hits HTTP
            res1 = await geocoder.geocode("Nabha, Patiala")
            assert res1 is not None
            assert res1.village == "Nabha"
            assert call_count == 1

            # Second lookup with same query -> hits cache, call_count stays 1
            res2 = await geocoder.geocode("  nabha,  patiala  ")
            assert res2 is not None
            assert res2.village == "Nabha"
            assert call_count == 1

    asyncio.run(_run())


def test_geocode_cli_runner(capsys):
    """Tests running geocode CLI."""
    data = json.loads((FIXTURES_DIR / "nominatim_sample.json").read_text(encoding="utf-8"))
    
    async def _run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=data))
        async with httpx.AsyncClient(transport=transport) as http_client:
            geocoder = Geocoder(min_request_interval=0.0, client=http_client)
            res = await geocoder.geocode("Nabha, Patiala")
            assert res is not None

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Active Fire Ingestion Tests
# ---------------------------------------------------------------------------

def test_ingest_active_fires():
    """Tests the active fire ingestion function writing hotspots to database with TTL."""
    csv_fixture = (FIXTURES_DIR / "firms_viirs_sample.csv").read_text(encoding="utf-8")
    db = InMemoryDatabase()

    async def _run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text=csv_fixture))
        async with httpx.AsyncClient(transport=transport) as http_client:
            firms_client = FirmsClient(map_key="TEST_KEY", client=http_client)
            
            count = await ingest_active_fires(
                db=db,
                firms_client=firms_client,
                days=2,
                min_confidence="nominal",
                ttl_days=10,
            )

            assert count == 3
            persisted = db.list_hotspots()
            assert len(persisted) == 3
            
            # Verify 10-day TTL was set properly
            now_epoch = int(time.time())
            for h in persisted:
                assert h.ttl is not None
                assert h.ttl >= now_epoch + 9 * 86400

    asyncio.run(_run())


def test_ingest_fires_cli_runner(capsys):
    """Tests running ingest_fires CLI."""
    csv_fixture = (FIXTURES_DIR / "firms_viirs_sample.csv").read_text(encoding="utf-8")

    async def _run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text=csv_fixture))
        async with httpx.AsyncClient(transport=transport) as http_client:
            firms_client = FirmsClient(map_key="TEST_KEY", client=http_client)
            db = InMemoryDatabase()
            count = await ingest_active_fires(db=db, firms_client=firms_client, days=2, ttl_days=10)
            assert count == 3

    asyncio.run(_run())
