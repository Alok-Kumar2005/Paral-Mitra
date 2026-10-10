"""Unit tests for booking lifecycle transitions and concurrency guards."""

from datetime import date, datetime, timedelta, timezone
import pytest

from src.common.db import InMemoryDatabase
from src.common.models import BookingStatus, MachineType, OptionType, ProviderStatus, ProviderType
from src.marketplace import services


@pytest.fixture
def db():
    database = InMemoryDatabase()
    database.clear_all()

    # Seed verified provider and active machine
    services.register_provider(
        db=database,
        provider_id="PRV_PUNJAB",
        provider_type=ProviderType.CHC,
        name="Patiala Farmers CHC",
        contact_phone="9876500000",
        district="Patiala",
        state="Punjab",
        lat=30.3753,
        lon=76.1517,
        telegram_chat_id=8888,
    )
    services.approve_provider(database, "PRV_PUNJAB", admin_chat_id=1)

    services.add_machine(
        db=database,
        machine_id="MCH_TEST",
        provider_id="PRV_PUNJAB",
        machine_type=MachineType.SUPER_SEEDER,
        village="Nabha",
        district="Patiala",
        lat=30.3750,
        lon=76.1500,
        rate_per_acre=1500.0,
        travel_charge_per_km=10.0,
        service_radius_km=30.0,
    )
    return database


def test_create_booking_in_situ(db):
    booking, notifs = services.create_booking(
        db=db,
        farmer_chat_id=1001,
        target_id="MCH_TEST",
        acres=12.5,
        requested_date=date(2026, 10, 20),
        option_type=OptionType.IN_SITU,
    )
    assert booking.status == BookingStatus.PENDING
    assert booking.booking_id.startswith("BK-")
    assert booking.expires_at is not None
    # Check notifications: 1 for farmer, 1 for operator
    assert len(notifs) == 2
    farmer_notif = next(n for n in notifs if n.chat_id == 1001)
    op_notif = next(n for n in notifs if n.chat_id == 8888)
    assert "PENDING" in farmer_notif.text
    assert "New Job Request" in op_notif.text
    assert op_notif.reply_markup is not None


def test_owner_decide_accept(db):
    booking, _ = services.create_booking(
        db=db,
        farmer_chat_id=1001,
        target_id="MCH_TEST",
        acres=10.0,
        requested_date=date(2026, 10, 22),
        option_type=OptionType.IN_SITU,
    )

    # Operator accepts
    updated, notifs = services.owner_decide(
        db=db,
        booking_id=booking.booking_id,
        operator_chat_id=8888,
        accept=True,
    )
    assert updated is not None
    assert updated.status == BookingStatus.CONFIRMED

    # Machine date must be blocked
    machine = db.get_machine("MCH_TEST")
    assert date(2026, 10, 22) in machine.blocked_dates

    # Farmer gets provider phone number in notification
    farmer_notif = next(n for n in notifs if n.chat_id == 1001)
    assert "9876500000" in farmer_notif.text


def test_owner_decide_decline(db):
    booking, _ = services.create_booking(
        db=db,
        farmer_chat_id=1001,
        target_id="MCH_TEST",
        acres=10.0,
        requested_date=date(2026, 10, 23),
        option_type=OptionType.IN_SITU,
    )

    updated, notifs = services.owner_decide(
        db=db,
        booking_id=booking.booking_id,
        operator_chat_id=8888,
        accept=False,
    )
    assert updated is not None
    assert updated.status == BookingStatus.REJECTED


def test_owner_decide_double_tap_guarded(db):
    booking, _ = services.create_booking(
        db=db,
        farmer_chat_id=1001,
        target_id="MCH_TEST",
        acres=10.0,
        requested_date=date(2026, 10, 24),
        option_type=OptionType.IN_SITU,
    )

    # First accept succeeds
    first, _ = services.owner_decide(db, booking.booking_id, operator_chat_id=8888, accept=True)
    assert first.status == BookingStatus.CONFIRMED

    # Second accept fails gracefully (not pending)
    second, notifs = services.owner_decide(db, booking.booking_id, operator_chat_id=8888, accept=True)
    assert second is None
    assert "no longer pending" in notifs[0].text


def test_unauthorized_owner_decision_rejected(db):
    booking, _ = services.create_booking(
        db=db,
        farmer_chat_id=1001,
        target_id="MCH_TEST",
        acres=10.0,
        requested_date=date(2026, 10, 25),
        option_type=OptionType.IN_SITU,
    )

    # Random unauthorized chat ID
    res, notifs = services.owner_decide(db, booking.booking_id, operator_chat_id=99999, accept=True)
    assert res is None
    assert "not authorised" in notifs[0].text


def test_filter_unverified_and_inactive(db):
    # Add pending unverified provider
    services.register_provider(
        db=db,
        provider_id="PRV_UNVERIFIED",
        provider_type=ProviderType.CHC,
        name="Unverified CHC",
        contact_phone="9999999999",
        district="Patiala",
        state="Punjab",
        lat=30.3753,
        lon=76.1517,
    )
    services.add_machine(
        db=db,
        machine_id="MCH_UNVERIFIED",
        provider_id="PRV_UNVERIFIED",
        machine_type=MachineType.SUPER_SEEDER,
        village="Nabha",
        district="Patiala",
        lat=30.3750,
        lon=76.1500,
        rate_per_acre=1200.0,
        travel_charge_per_km=0.0,
        service_radius_km=30.0,
    )

    bookable = db.list_bookable_machines(lat=30.3753, lon=76.1517, radius_km=50.0)
    # MCH_UNVERIFIED must NOT be in bookable machines
    ids = [m.machine_id for m in bookable]
    assert "MCH_UNVERIFIED" not in ids
    assert "MCH_TEST" in ids
