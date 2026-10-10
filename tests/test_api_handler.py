"""Tests for Officer Dashboard API handler (src/handlers/api.py).

Verifies:
  - Route status, headers, and payload structures.
  - Integration with engine compute_gap() and constants.csv.
  - Zero farmer PII and strict machine privacy (no rates, owner names, or phones).
  - In-memory 5-minute container caching and Cache-Control headers.
  - DASHBOARD_TOKEN authorization with constant-time verification.
  - Empty database and edge-case behavior.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from src.common.db import InMemoryDatabase
from src.common.models import (
    Booking,
    BookingStatus,
    Buyer,
    BuyerType,
    Hotspot,
    Machine,
    MachineType,
    OptionType,
    Provider,
    ProviderStatus,
    ProviderType,
    TransportTerms,
)
from src.handlers.api import (
    clear_cache,
    handle_api_fires,
    handle_api_gaps,
    handle_api_machines,
    handle_api_summary,
    handle_dashboard,
    handler,
)


@pytest.fixture(autouse=True)
def _reset_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure clean container cache and environment for each test."""
    clear_cache()
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)


@pytest.fixture
def populated_db() -> InMemoryDatabase:
    """Provides an in-memory database with realistic test entities."""
    db = InMemoryDatabase()
    today = datetime.now(timezone.utc).date()

    # 1. Providers
    provider_chc = Provider(
        provider_id="PRV_CHC_01",
        provider_type=ProviderType.CHC,
        name="Ludhiana Cooperative CHC",
        contact_phone="9876543210",
        district="Ludhiana",
        state="Punjab",
        lat=30.9010,
        lon=75.8573,
        status=ProviderStatus.VERIFIED,
        is_directory_listing=False,
    )
    provider_dir = Provider(
        provider_id="PRV_DIR_02",
        provider_type=ProviderType.CHC,
        name="Bathinda Public CHC",
        contact_phone="9812345678",
        district="Bathinda",
        state="Punjab",
        lat=30.2110,
        lon=74.9455,
        status=ProviderStatus.VERIFIED,
        is_directory_listing=True,
    )
    db.put_provider(provider_chc)
    db.put_provider(provider_dir)

    # 2. Machines
    m1 = Machine(
        machine_id="MCH_001",
        provider_id="PRV_CHC_01",
        owner_name="Sensitive Operator Name 1",
        owner_phone="9999999999",
        owner_telegram_chat_id=12345678,
        machine_type=MachineType.SUPER_SEEDER,
        village="Jagraon",
        district="Ludhiana",
        lat=30.9010,
        lon=75.8573,
        rate_per_acre=1200.0,
        travel_charge_per_km=15.0,
        service_radius_km=25.0,
        available_from=today,
        status="ACTIVE",
    )
    m2 = Machine(
        machine_id="MCH_002",
        provider_id="PRV_DIR_02",
        owner_name="Sensitive Operator Name 2",
        owner_phone="8888888888",
        owner_telegram_chat_id=87654321,
        machine_type=MachineType.BALER,
        village="Rampura",
        district="Bathinda",
        lat=30.2110,
        lon=74.9455,
        rate_per_acre=1600.0,
        travel_charge_per_km=20.0,
        service_radius_km=30.0,
        available_from=today,
        status="ACTIVE",
        is_synthetic=True,
    )
    db.put_machine(m1)
    db.put_machine(m2)

    # 3. Buyers
    b1 = Buyer(
        buyer_id="BYR_001",
        name="Punjab Bio Energy CBG",
        buyer_type=BuyerType.CBG_PLANT,
        district="Ludhiana",
        lat=30.8500,
        lon=75.8000,
        price_per_tonne=1850.0,
        min_quantity_tonnes=50.0,
        transport_terms=TransportTerms.EX_FARM,
        phone="9876500000",
    )
    db.put_buyer(b1)

    # 4. Hotspots (cluster near Ludhiana within machine radius, and distant cluster in Sangrur = gap)
    hotspots = [
        # Near Ludhiana (~5 km from MCH_001)
        Hotspot(
            grid_cell="30.9_75.8",
            lat=30.9100,
            lon=75.8600,
            acq_date=today,
            frp=24.5,
            confidence="nominal",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ),
        Hotspot(
            grid_cell="30.9_75.8",
            lat=30.9150,
            lon=75.8650,
            acq_date=today - timedelta(days=1),
            frp=48.2,
            confidence="high",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ),
        # Distant cluster in Sangrur (>40 km away from all machines = GAP)
        Hotspot(
            grid_cell="30.2_75.8",
            lat=30.2450,
            lon=75.8420,
            acq_date=today - timedelta(days=2),
            frp=35.0,
            confidence="high",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        ),
    ]
    db.put_hotspots(hotspots)

    # 5. Bookings
    b_conf = Booking(
        booking_id="BK-001",
        farmer_chat_id=111222333,
        option_type=OptionType.IN_SITU,
        target_id="MCH_001",
        acres=10.0,
        requested_date=today,
        status=BookingStatus.CONFIRMED,
    )
    b_done = Booking(
        booking_id="BK-002",
        farmer_chat_id=444555666,
        option_type=OptionType.EX_SITU,
        target_id="MCH_002",
        acres=5.0,
        requested_date=today - timedelta(days=1),
        status=BookingStatus.COMPLETED,
    )
    b_pend = Booking(
        booking_id="BK-003",
        farmer_chat_id=777888999,
        option_type=OptionType.IN_SITU,
        target_id="MCH_001",
        acres=8.0,
        requested_date=today,
        status=BookingStatus.PENDING,
    )
    db.put_booking(b_conf)
    db.put_booking(b_done)
    db.put_booking(b_pend)

    return db


# ── Route & Payload Tests ─────────────────────────────────────────────────────


def test_dashboard_html_response() -> None:
    """GET /dashboard serves valid HTML with correct content type."""
    event = {"routeKey": "GET /dashboard", "rawPath": "/dashboard"}
    res = handler(event)

    assert res["statusCode"] == 200
    assert "text/html" in res["headers"]["Content-Type"]
    assert "public, max-age=300" in res["headers"]["Cache-Control"]
    assert "<title>Parali Mitra — Officer Residue Dashboard</title>" in res["body"]
    assert "MapLibre GL JS" in res["body"]


def test_api_summary_metrics(populated_db: InMemoryDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/summary returns expected summary metrics, sparkline, and estimated residue."""
    monkeypatch.setattr("src.handlers.api.get_db", lambda: populated_db)
    event = {"routeKey": "GET /api/summary", "rawPath": "/api/summary"}
    res = handler(event)

    assert res["statusCode"] == 200
    assert res["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert "public, max-age=300" in res["headers"]["Cache-Control"]

    body = json.loads(res["body"])
    assert body["total_hotspots"] == 3
    assert body["verified_machines"] == 2
    assert body["verified_buyers"] == 1
    assert body["flagged_cells"] >= 1  # Sangrur cluster is >15 km away

    # Sparkline daily series
    assert len(body["daily_counts"]) == 7
    total_in_sparkline = sum(d["count"] for d in body["daily_counts"])
    assert total_in_sparkline == 3

    # Bookings and Tonnes Handled
    # BK-001 (10 acres) + BK-002 (5 acres) = 15 acres * 2.8 t/acre = 42.0 tonnes
    assert body["bookings"]["confirmed"] == 1
    assert body["bookings"]["completed"] == 1
    assert body["bookings"]["total_active_or_done"] == 2
    assert body["estimated_residue_tonnes_handled"] == 42.0
    assert body["residue_tonnes_label"] == "estimated"

    # Top underserved areas
    assert len(body["top_underserved_areas"]) >= 1
    assert "lat" in body["top_underserved_areas"][0]
    assert "lon" in body["top_underserved_areas"][0]
    assert "fire_count" in body["top_underserved_areas"][0]


def test_api_fires_aggregation(populated_db: InMemoryDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/fires aggregates hotspots by 0.1-degree grid cell."""
    monkeypatch.setattr("src.handlers.api.get_db", lambda: populated_db)
    event = {
        "routeKey": "GET /api/fires",
        "rawPath": "/api/fires",
        "queryStringParameters": {"days": "7"},
    }
    res = handler(event)

    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["total_hotspots"] == 3
    assert body["cell_count"] == 2  # 30.9_75.8 (2 fires) and 30.2_75.8 (1 fire)

    # Top cell is the 2-fire cluster
    top_cell = body["cells"][0]
    assert top_cell["fire_count"] == 2
    assert top_cell["max_frp"] == 48.2
    assert top_cell["total_frp"] == 72.7


def test_api_gaps_flagging(populated_db: InMemoryDatabase, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/gaps flags grid cells exceeding the 15km machinery radius."""
    monkeypatch.setattr("src.handlers.api.get_db", lambda: populated_db)
    event = {"routeKey": "GET /api/gaps", "rawPath": "/api/gaps"}
    res = handler(event)

    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["flagged_gaps"] >= 1

    # Check that Sangrur cell is flagged as a gap
    sangrur_gap = next((g for g in body["gaps"] if "30.2" in g["grid_cell"]), None)
    assert sangrur_gap is not None
    assert sangrur_gap["is_gap"] is True
    assert sangrur_gap["nearest_machine_distance_km"] > 15.0


def test_api_machines_zero_pii_and_public_fields_only(
    populated_db: InMemoryDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /api/machines returns public fields ONLY and strictly forbids PII and rates."""
    monkeypatch.setattr("src.handlers.api.get_db", lambda: populated_db)
    event = {"routeKey": "GET /api/machines", "rawPath": "/api/machines"}
    res = handler(event)

    assert res["statusCode"] == 200
    raw_body = res["body"]

    # ── Strict Security Assertions: Zero PII or private operational rates ──────
    forbidden_terms = [
        "Sensitive Operator Name",
        "owner_name",
        "owner_phone",
        "owner_telegram_chat_id",
        "rate_per_acre",
        "travel_charge_per_km",
        "9999999999",
        "8888888888",
        "12345678",
        "87654321",
    ]
    for term in forbidden_terms:
        assert term not in raw_body, f"Security violation: '{term}' leaked in /api/machines response"

    body = json.loads(raw_body)
    assert body["total_machines"] == 2
    for m in body["machines"]:
        # Only allowed keys
        assert set(m.keys()) == {
            "machine_id",
            "machine_type",
            "village",
            "district",
            "lat",
            "lon",
            "is_directory_listing",
            "is_synthetic",
        }


def test_zero_pii_across_all_endpoints(
    populated_db: InMemoryDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that no farmer chat IDs or private names leak in ANY endpoint."""
    monkeypatch.setattr("src.handlers.api.get_db", lambda: populated_db)
    endpoints = ["/api/summary", "/api/fires", "/api/gaps", "/api/machines"]

    farmer_pii_tokens = [
        "111222333",  # Farmer chat IDs
        "444555666",
        "777888999",
        "farmer_chat_id",
        "Sensitive Operator",
    ]

    for ep in endpoints:
        event = {"routeKey": f"GET {ep}", "rawPath": ep}
        res = handler(event)
        for token in farmer_pii_tokens:
            assert token not in res["body"], f"PII token '{token}' found in {ep}"


# ── Container Caching & Token Authorization ───────────────────────────────────


def test_in_memory_container_caching(
    populated_db: InMemoryDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated calls within 300 seconds hit the in-memory container cache."""
    monkeypatch.setattr("src.handlers.api.get_db", lambda: populated_db)
    event = {"routeKey": "GET /api/summary", "rawPath": "/api/summary"}

    # 1. First call: miss
    res1 = handler(event)
    assert res1["statusCode"] == 200
    assert "X-Cache" not in res1["headers"]

    # 2. Second call: hit
    res2 = handler(event)
    assert res2["statusCode"] == 200
    assert res2["headers"].get("X-Cache") == "HIT"
    assert res1["body"] == res2["body"]

    # 3. Cache clear: miss again
    clear_cache()
    res3 = handler(event)
    assert res3["statusCode"] == 200
    assert "X-Cache" not in res3["headers"]


def test_token_protection(
    populated_db: InMemoryDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DASHBOARD_TOKEN is set, unauthorized requests return 401."""
    monkeypatch.setattr("src.handlers.api.get_db", lambda: populated_db)
    monkeypatch.setenv("DASHBOARD_TOKEN", "secure-officer-token-xyz")

    # 1. Missing token -> 401
    event_no_token = {"routeKey": "GET /api/summary", "rawPath": "/api/summary"}
    res_no_token = handler(event_no_token)
    assert res_no_token["statusCode"] == 401
    assert "Unauthorized" in res_no_token["body"]

    # 2. Invalid token -> 401
    event_bad_token = {
        "routeKey": "GET /api/summary",
        "rawPath": "/api/summary",
        "queryStringParameters": {"token": "wrong-token"},
    }
    res_bad_token = handler(event_bad_token)
    assert res_bad_token["statusCode"] == 401

    # 3. Correct token -> 200 OK
    event_good_token = {
        "routeKey": "GET /api/summary",
        "rawPath": "/api/summary",
        "queryStringParameters": {"token": "secure-officer-token-xyz"},
    }
    res_good_token = handler(event_good_token)
    assert res_good_token["statusCode"] == 200


# ── Empty Database Graceful Handling ──────────────────────────────────────────


def test_empty_database_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty database returns clean empty collections and 0 counts without raising."""
    empty_db = InMemoryDatabase()
    monkeypatch.setattr("src.handlers.api.get_db", lambda: empty_db)

    # 1. Summary
    res = handler({"routeKey": "GET /api/summary", "rawPath": "/api/summary"})
    assert res["statusCode"] == 200
    body = json.loads(res["body"])
    assert body["total_hotspots"] == 0
    assert body["flagged_cells"] == 0
    assert body["verified_machines"] == 0
    assert body["estimated_residue_tonnes_handled"] == 0.0
    assert body["top_underserved_areas"] == []

    # 2. Fires
    res_fires = handler({"routeKey": "GET /api/fires", "rawPath": "/api/fires"})
    assert res_fires["statusCode"] == 200
    assert json.loads(res_fires["body"])["cells"] == []

    # 3. Gaps
    res_gaps = handler({"routeKey": "GET /api/gaps", "rawPath": "/api/gaps"})
    assert res_gaps["statusCode"] == 200
    assert json.loads(res_gaps["body"])["gaps"] == []

    # 4. Machines
    res_machines = handler({"routeKey": "GET /api/machines", "rawPath": "/api/machines"})
    assert res_machines["statusCode"] == 200
    assert json.loads(res_machines["body"])["machines"] == []
