"""Unit tests for DatabaseClient (InMemory and access layer logic)."""

from datetime import date
import time
import pytest

from src.common.db import InMemoryDatabase
from src.common.models import (
    Booking,
    BookingStatus,
    Buyer,
    FarmerSession,
    Hotspot,
    Machine,
    MachineType,
    OptionType,
    TransportTerms,
)


@pytest.fixture
def db():
    database = InMemoryDatabase()
    database.clear_all()
    return database


def test_machine_crud(db: InMemoryDatabase):
    m = Machine(
        machine_id="MCH_TEST_01",
        owner_name="Owner A",
        owner_phone="+919876543210",
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
    assert retrieved.owner_name == "Owner A"
    assert retrieved.rate_per_acre == 2100.0

    all_ludhiana = db.list_machines(district="Ludhiana")
    assert len(all_ludhiana) == 1

    all_karnal = db.list_machines(district="Karnal")
    assert len(all_karnal) == 0


def test_buyer_crud(db: InMemoryDatabase):
    b = Buyer(
        buyer_id="BYR_TEST_01",
        name="CBG Bio Gas Plant",
        buyer_type="CBG_PLANT",
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


def test_booking_crud_and_status_update(db: InMemoryDatabase):
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


def test_session_state(db: InMemoryDatabase):
    session = FarmerSession(
        chat_id=55555,
        language="hi",
        acres=15.0,
        lat=30.0,
        lon=76.0,
    )
    db.put_session(session)

    res = db.get_session(55555)
    assert res is not None
    assert res.language == "hi"
    assert res.acres == 15.0


def test_hotspot_saving_and_ttl(db: InMemoryDatabase):
    now_epoch = int(time.time())
    active_h = Hotspot(
        grid_cell="G1",
        lat=30.1,
        lon=76.1,
        acq_date=date(2026, 10, 8),
        frp=25.0,
        confidence="nominal",
        ttl=now_epoch + 3600,  # Valid for 1 hour
    )
    expired_h = Hotspot(
        grid_cell="G2",
        lat=30.2,
        lon=76.2,
        acq_date=date(2026, 10, 8),
        frp=15.0,
        confidence="low",
        ttl=now_epoch - 100,  # Already expired
    )
    db.put_hotspots([active_h, expired_h])

    active_list = db.list_hotspots()
    assert len(active_list) == 1
    assert active_list[0].grid_cell == "G1"


def test_processed_updates_idempotency_and_ttl(db: InMemoryDatabase):
    assert db.is_update_processed("upd_123") is False

    db.mark_update_processed("upd_123", ttl_seconds=3600)
    assert db.is_update_processed("upd_123") is True

    # Check expired update
    db.processed_updates["expired_upd"] = int(time.time()) - 10
    assert db.is_update_processed("expired_upd") is False
