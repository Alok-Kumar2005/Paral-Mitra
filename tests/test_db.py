"""Unit tests for InMemoryDatabase (local backend)."""

from datetime import date, datetime, timedelta, timezone
import pytest

from src.common.db import InMemoryDatabase
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
    TransportTerms,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def db():
    database = InMemoryDatabase()
    database.clear_all()
    return database


# ── Machine CRUD ──────────────────────────────────────────────────────────────


def test_machine_crud(db: InMemoryDatabase):
    m = Machine(
        machine_id="MCH_TEST_01",
        machine_type=MachineType.SUPER_SEEDER,
        village="Village 1",
        district="Ludhiana",
        lat=30.9,
        lon=75.8,
        rate_per_acre=2100.0,
        travel_charge_per_km=25.0,
        service_radius_km=15.0,
        available_from=date(2026, 10, 15),
    )
    db.put_machine(m)

    retrieved = db.get_machine("MCH_TEST_01")
    assert retrieved is not None
    assert retrieved.rate_per_acre == 2100.0

    all_ludhiana = db.list_machines(district="Ludhiana")
    assert len(all_ludhiana) == 1

    all_karnal = db.list_machines(district="Karnal")
    assert len(all_karnal) == 0


# ── Buyer CRUD ────────────────────────────────────────────────────────────────


def test_buyer_crud(db: InMemoryDatabase):
    b = Buyer(
        buyer_id="BYR_TEST_01",
        name="CBG Bio Gas Plant",
        buyer_type="CBG_PLANT",
        district="Ludhiana",
        lat=30.2,
        lon=75.7,
        price_per_tonne=1900.0,
        min_quantity_tonnes=10.0,
        transport_terms=TransportTerms.EX_FARM,
        phone="+919812345678",
    )
    db.put_buyer(b)

    retrieved = db.get_buyer("BYR_TEST_01")
    assert retrieved is not None
    assert retrieved.price_per_tonne == 1900.0
    assert len(db.list_buyers()) == 1


# ── Booking CRUD and status transitions ───────────────────────────────────────


def test_booking_crud_and_status_update(db: InMemoryDatabase):
    farmer = FarmerSession(chat_id=12345)
    db.put_session(farmer)

    bk = Booking(
        booking_id="BKG_999",
        farmer_chat_id=12345,
        option_type=OptionType.IN_SITU,
        target_id="MCH_TEST_01",
        acres=8.0,
        requested_date=date(2026, 10, 22),
    )
    db.put_booking(bk)

    assert db.get_booking("BKG_999") is not None
    assert db.get_booking("BKG_999").status == BookingStatus.PENDING

    updated = db.update_booking_status("BKG_999", BookingStatus.CONFIRMED)
    assert updated is not None
    assert updated.status == BookingStatus.CONFIRMED

    farmer_bookings = db.list_bookings_by_farmer(12345)
    assert len(farmer_bookings) == 1
    assert farmer_bookings[0].booking_id == "BKG_999"


# ── Session / farmer profile ──────────────────────────────────────────────────


def test_session_state(db: InMemoryDatabase):
    session = FarmerSession(
        chat_id=55555,
        language="hi",
        acres=15.0,
        lat=30.0,
        lon=76.0,
        district="Ludhiana",
        state="Punjab",
    )
    db.put_session(session)

    res = db.get_session(55555)
    assert res is not None
    assert res.language == "hi"
    assert res.acres == 15.0
    assert res.district == "Ludhiana"


# ── Hotspot expires_at (replaces DynamoDB-era ttl) ────────────────────────────


def test_hotspot_saving_and_expiry(db: InMemoryDatabase):
    now = _utc_now()
    active_h = Hotspot(
        grid_cell="G1",
        lat=30.1,
        lon=76.1,
        acq_date=date(2026, 10, 8),
        frp=25.0,
        confidence="nominal",
        expires_at=now + timedelta(hours=1),
    )
    expired_h = Hotspot(
        grid_cell="G2",
        lat=30.2,
        lon=76.2,
        acq_date=date(2026, 10, 8),
        frp=15.0,
        confidence="low",
        expires_at=now - timedelta(seconds=10),
    )
    db.put_hotspots([active_h, expired_h])

    active_list = db.list_hotspots()
    assert len(active_list) == 1
    assert active_list[0].grid_cell == "G1"


def test_hotspot_ttl_property_backcompat():
    """Hotspot.ttl property still works as a Unix-epoch shim."""
    now = _utc_now()
    expires = now + timedelta(hours=1)
    h = Hotspot(
        grid_cell="GX",
        lat=30.0,
        lon=76.0,
        acq_date=date(2026, 10, 8),
        frp=10.0,
        confidence="high",
        expires_at=expires,
    )
    assert h.ttl is not None
    assert abs(h.ttl - int(expires.timestamp())) <= 1

    # Setting via .ttl setter updates expires_at
    import time
    epoch = int(time.time()) + 3600
    h.ttl = epoch
    assert h.expires_at is not None
    assert abs(int(h.expires_at.timestamp()) - epoch) <= 1


# ── Idempotency / processed updates ──────────────────────────────────────────


def test_processed_updates_idempotency(db: InMemoryDatabase):
    assert db.is_update_processed("upd_123") is False

    db.mark_update_processed("upd_123", ttl_seconds=3600)
    assert db.is_update_processed("upd_123") is True

    # A second mark_update_processed on the same id should not raise
    db.mark_update_processed("upd_123", ttl_seconds=3600)
    assert db.is_update_processed("upd_123") is True


def test_processed_updates_expired(db: InMemoryDatabase):
    import time
    db._processed_updates["expired_upd"] = time.time() - 10
    assert db.is_update_processed("expired_upd") is False


# ── Chat messages and rolling summary ────────────────────────────────────────


def test_chat_messages_append_and_load(db: InMemoryDatabase):
    farmer = FarmerSession(chat_id=77777)
    db.put_session(farmer)
    expires = _utc_now() + timedelta(days=30)

    m1 = db.append_chat_message(
        ChatMessage(chat_id=77777, role="user", text="Hello", expires_at=expires)
    )
    m2 = db.append_chat_message(
        ChatMessage(chat_id=77777, role="assistant", text="Namaste!", expires_at=expires)
    )

    assert m1.id is not None
    assert m2.id is not None and m2.id > m1.id  # type: ignore[operator]

    loaded = db.load_chat_messages(77777, limit=10)
    assert len(loaded) == 2
    assert loaded[0].text == "Hello"


def test_chat_state_roundtrip(db: InMemoryDatabase):
    farmer = FarmerSession(chat_id=88888)
    db.put_session(farmer)

    assert db.get_chat_state(88888) is None

    state = ChatState(
        chat_id=88888,
        summary="Farmer from Punjab, 10 acres.",
        summarized_upto=5,
        version=0,
    )
    db.put_chat_state(state)

    retrieved = db.get_chat_state(88888)
    assert retrieved is not None
    assert "Punjab" in retrieved.summary  # type: ignore[operator]


# ── Geocode cache ─────────────────────────────────────────────────────────────


def test_geocode_cache(db: InMemoryDatabase):
    assert db.get_geocode_cache("patiala_punjab") is None

    db.set_geocode_cache(
        "patiala_punjab",
        lat=30.3398,
        lon=76.3869,
        payload={"display_name": "Patiala, Punjab, India"},
        ttl_seconds=3600,
    )

    result = db.get_geocode_cache("patiala_punjab")
    assert result is not None
    assert abs(result["lat"] - 30.3398) < 0.001


# ── forget_farmer cascade ─────────────────────────────────────────────────────


def test_forget_farmer(db: InMemoryDatabase):
    farmer = FarmerSession(chat_id=99999)
    db.put_session(farmer)
    expires = _utc_now() + timedelta(days=30)
    db.append_chat_message(
        ChatMessage(chat_id=99999, role="user", text="test", expires_at=expires)
    )

    db.forget_farmer(99999)

    assert db.get_session(99999) is None
    assert db.load_chat_messages(99999) == []


# ── prune_expired ─────────────────────────────────────────────────────────────


def test_prune_expired(db: InMemoryDatabase):
    farmer = FarmerSession(chat_id=11111)
    db.put_session(farmer)

    now = _utc_now()
    db.append_chat_message(
        ChatMessage(chat_id=11111, role="user", text="old", expires_at=now - timedelta(hours=1))
    )
    db.append_chat_message(
        ChatMessage(chat_id=11111, role="user", text="new", expires_at=now + timedelta(hours=24))
    )

    db.prune_expired()

    msgs = db.load_chat_messages(11111, limit=50)
    assert all(m.text != "old" for m in msgs)
    assert any(m.text == "new" for m in msgs)
