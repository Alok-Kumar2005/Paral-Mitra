"""Storage contract test suite for Parali Mitra.

Parametrized over both backends:
  - "local"    -> InMemoryDatabase (always runs, fully offline)
  - "postgres" -> PostgresClient   (runs only when TEST_DATABASE_URL is set; marker: pg)

Each postgres run creates an isolated schema (test_<uuid4_hex>) that is dropped
on teardown, ensuring tests never pollute each other or the main schema.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from src.common.db import DatabaseClient, InMemoryDatabase
from src.common.models import (
    Booking,
    BookingStatus,
    Buyer,
    ChatMessage,
    ChatState,
    FarmerSession,
    Hotspot,
    Machine,
    MachineType,
    OptionType,
    Provider,
    ProviderStatus,
    ProviderType,
    TransportTerms,
)


# ── Backend parametrization ───────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture(params=["local", pytest.param("postgres", marks=pytest.mark.pg)])
def db(request: pytest.FixtureRequest) -> DatabaseClient:  # type: ignore[return]
    """Parametrized database fixture. Returns a fresh backend for each test."""
    backend = request.param

    if backend == "local":
        client = InMemoryDatabase()
        client.clear_all()
        yield client
        return

    # ── Postgres backend: isolated schema per test run ────────────────────────
    test_url = os.getenv("TEST_DATABASE_URL", "").strip()
    if not test_url:
        pytest.skip("TEST_DATABASE_URL not set — skipping postgres contract tests")

    try:
        import psycopg
    except ImportError:
        pytest.skip("psycopg[binary] not installed")

    schema = f"test_{uuid.uuid4().hex[:12]}"
    migrations_dir = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "db" / "migrations"
    )

    # Create isolated schema and set search_path
    admin_conn = psycopg.connect(test_url, sslmode="require", autocommit=True)
    admin_conn.execute(f"CREATE SCHEMA {schema}")  # noqa: S608
    admin_conn.close()

    # Apply migrations inside the test schema
    schema_conn = psycopg.connect(
        test_url,
        sslmode="require",
        options=f"-c search_path={schema}",
        autocommit=True,
    )
    for mf in sorted(migrations_dir.glob("*.sql")):
        schema_conn.execute(mf.read_text(encoding="utf-8"))
    schema_conn.close()

    # Patch DATABASE_URL to include the test schema search_path
    original_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = (
        test_url
        if "options=" in test_url
        else test_url + f"&options=-c search_path%3D{schema}"
    )

    from src.common.db import PostgresClient

    client = PostgresClient()
    yield client

    # Teardown: drop the test schema
    try:
        client._conn and client._conn.close()
    except Exception:
        pass

    if original_url is not None:
        os.environ["DATABASE_URL"] = original_url
    else:
        os.environ.pop("DATABASE_URL", None)

    cleanup_conn = psycopg.connect(test_url, sslmode="require", autocommit=True)
    cleanup_conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")  # noqa: S608
    cleanup_conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_farmer(chat_id: int = 100001) -> FarmerSession:
    return FarmerSession(
        chat_id=chat_id,
        language="hi",
        lat=30.3150,
        lon=76.4120,
        village_text="Rauni, Patiala",
        district="Patiala",
        state="Punjab",
        acres=8.0,
        sowing_deadline=date(2026, 11, 25),
    )


def _make_machine(machine_id: str = "MCH_CTR_001") -> Machine:
    return Machine(
        machine_id=machine_id,
        machine_type=MachineType.SUPER_SEEDER,
        village="Rauni",
        district="Patiala",
        lat=30.3200,
        lon=76.4200,
        rate_per_acre=2000.0,
        travel_charge_per_km=20.0,
        service_radius_km=30.0,
        available_from=date(2026, 10, 15),
        status="ACTIVE",
    )


def _make_provider(provider_id: str = "PRV_001") -> Provider:
    return Provider(
        provider_id=provider_id,
        provider_type=ProviderType.CHC,
        name="KVK Patiala CHC",
        contact_phone="+919876543210",
        district="Patiala",
        state="Punjab",
        lat=30.3150,
        lon=76.4120,
        status=ProviderStatus.PENDING,
    )


# ── Test 1: Farmer profile memory ─────────────────────────────────────────────


def test_profile_memory(db: DatabaseClient) -> None:
    farmer = _make_farmer(100001)
    db.put_session(farmer)

    retrieved = db.get_session(100001)
    assert retrieved is not None
    assert retrieved.chat_id == 100001
    assert retrieved.acres == 8.0
    assert retrieved.district == "Patiala"

    # Update and re-save
    farmer.acres = 12.0
    farmer.state = "Punjab"
    db.put_session(farmer)
    updated = db.get_session(100001)
    assert updated is not None
    assert updated.acres == 12.0


# ── Test 2: Conversation memory with rolling summary ──────────────────────────


def test_conversation_memory_and_summary(db: DatabaseClient) -> None:
    farmer = _make_farmer(100002)
    db.put_session(farmer)

    expires = _utc_now() + timedelta(days=30)

    msg1 = db.append_chat_message(
        ChatMessage(chat_id=100002, role="user", text="Hello", expires_at=expires)
    )
    msg2 = db.append_chat_message(
        ChatMessage(chat_id=100002, role="assistant", text="Sat Sri Akal!", expires_at=expires)
    )

    assert msg1.id is not None
    assert msg2.id is not None
    assert msg2.id > msg1.id  # type: ignore[operator]

    loaded = db.load_chat_messages(100002, limit=20)
    assert len(loaded) == 2
    assert loaded[0].role == "user"
    assert loaded[1].role == "assistant"

    # Rolling summary
    state = ChatState(
        chat_id=100002,
        summary="Farmer from Patiala, 8 acres, needs help.",
        summarized_upto=msg2.id,
        version=0,
    )
    db.put_chat_state(state)

    retrieved_state = db.get_chat_state(100002)
    assert retrieved_state is not None
    assert retrieved_state.summary is not None
    assert "Patiala" in retrieved_state.summary
    assert retrieved_state.version >= 0  # postgres increments on upsert


# ── Test 3: /forget_me cascade delete ────────────────────────────────────────


def test_forget_me_cascade(db: DatabaseClient) -> None:
    farmer = _make_farmer(100003)
    db.put_session(farmer)

    expires = _utc_now() + timedelta(days=30)
    db.append_chat_message(
        ChatMessage(chat_id=100003, role="user", text="Hi", expires_at=expires)
    )

    db.forget_farmer(100003)

    assert db.get_session(100003) is None
    msgs = db.load_chat_messages(100003)
    assert msgs == []


# ── Test 4: Provider verification flow ───────────────────────────────────────


def test_provider_verification_flow(db: DatabaseClient) -> None:
    p = _make_provider("PRV_CTR_001")
    db.put_provider(p)

    retrieved = db.get_provider("PRV_CTR_001")
    assert retrieved is not None
    assert retrieved.status == ProviderStatus.PENDING

    verified = db.update_provider_status(
        "PRV_CTR_001", ProviderStatus.VERIFIED, verified_by="admin_123"
    )
    assert verified is not None
    assert verified.status == ProviderStatus.VERIFIED
    assert verified.verified_by == "admin_123"

    suspended = db.update_provider_status("PRV_CTR_001", ProviderStatus.SUSPENDED)
    assert suspended is not None
    assert suspended.status == ProviderStatus.SUSPENDED


# ── Test 5: Nearby machines filtering (VERIFIED/ACTIVE only) ─────────────────


def test_nearby_machines_filtering(db: DatabaseClient) -> None:
    # Provider (VERIFIED)
    p = _make_provider("PRV_NRB_001")
    p = p.model_copy(update={"status": ProviderStatus.VERIFIED})
    db.put_provider(p)

    # Active machine with provider_id
    m_near = Machine(
        machine_id="MCH_NRB_NEAR",
        provider_id="PRV_NRB_001",
        machine_type=MachineType.HAPPY_SEEDER,
        village="Nabha",
        district="Patiala",
        lat=30.38,
        lon=76.15,
        rate_per_acre=1800.0,
        travel_charge_per_km=18.0,
        service_radius_km=25.0,
        available_from=date(2026, 10, 10),
        status="ACTIVE",
    )
    db.put_machine(m_near)

    # Machine too far away
    m_far = Machine(
        machine_id="MCH_NRB_FAR",
        provider_id="PRV_NRB_001",
        machine_type=MachineType.BALER,
        village="Amritsar",
        district="Amritsar",
        lat=31.63,
        lon=74.87,
        rate_per_acre=2200.0,
        travel_charge_per_km=22.0,
        service_radius_km=25.0,
        available_from=date(2026, 10, 10),
        status="ACTIVE",
    )
    db.put_machine(m_far)

    # Farmer at Patiala: 30.3150, 76.4120
    results = db.list_machines_nearby(lat=30.3150, lon=76.4120, radius_km=50.0)
    ids = [m.machine_id for m in results]
    assert "MCH_NRB_NEAR" in ids
    assert "MCH_NRB_FAR" not in ids


# ── Test 6: Booking transitions ───────────────────────────────────────────────


def test_booking_transitions(db: DatabaseClient) -> None:
    farmer = _make_farmer(100006)
    db.put_session(farmer)

    bk = Booking(
        booking_id="BKG_CTR_001",
        farmer_chat_id=100006,
        option_type=OptionType.IN_SITU,
        target_id="MCH_CTR_001",
        acres=8.0,
        requested_date=date(2026, 10, 25),
        status=BookingStatus.PENDING,
    )
    db.put_booking(bk)

    assert db.get_booking("BKG_CTR_001") is not None
    assert db.get_booking("BKG_CTR_001").status == BookingStatus.PENDING  # type: ignore[union-attr]

    confirmed = db.update_booking_status("BKG_CTR_001", BookingStatus.CONFIRMED)
    assert confirmed is not None
    assert confirmed.status == BookingStatus.CONFIRMED

    completed = db.update_booking_status("BKG_CTR_001", BookingStatus.COMPLETED)
    assert completed is not None
    assert completed.status == BookingStatus.COMPLETED

    farmer_bookings = db.list_bookings_by_farmer(100006)
    assert len(farmer_bookings) == 1
    assert farmer_bookings[0].booking_id == "BKG_CTR_001"


# ── Test 7: Idempotent update dedupe ─────────────────────────────────────────


def test_idempotent_update_dedupe(db: DatabaseClient) -> None:
    assert db.is_update_processed(99991) is False

    db.mark_update_processed(99991, ttl_seconds=3600)
    assert db.is_update_processed(99991) is True

    # Mark same update_id again — should not raise
    db.mark_update_processed(99991, ttl_seconds=3600)
    assert db.is_update_processed(99991) is True


# ── Test 8: prune_expired ────────────────────────────────────────────────────


def test_prune_expired(db: DatabaseClient) -> None:
    farmer = _make_farmer(100008)
    db.put_session(farmer)

    past = _utc_now() - timedelta(hours=1)
    future = _utc_now() + timedelta(hours=24)

    # Insert one expired and one live message
    db.append_chat_message(
        ChatMessage(chat_id=100008, role="user", text="old message", expires_at=past)
    )
    db.append_chat_message(
        ChatMessage(chat_id=100008, role="user", text="live message", expires_at=future)
    )

    # Insert expired hotspot
    expired_hs = Hotspot(
        grid_cell="PRUNE_G1",
        acq_date=date(2026, 9, 1),
        lat=30.0,
        lon=76.0,
        frp=10.0,
        confidence="nominal",
        expires_at=past,
    )
    db.put_hotspots([expired_hs])

    # Insert expired update
    db.mark_update_processed(88881, ttl_seconds=1)  # effectively expired

    db.prune_expired()

    # Only live message should remain
    msgs = db.load_chat_messages(100008, limit=50)
    assert all(m.text != "old message" for m in msgs)
    assert any(m.text == "live message" for m in msgs)

    # Expired hotspot should be gone
    active_hotspots = db.list_hotspots()
    assert not any(h.grid_cell == "PRUNE_G1" for h in active_hotspots)
