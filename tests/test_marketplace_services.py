"""Unit tests for Provider Marketplace services."""

from datetime import date, datetime, timedelta, timezone
import pytest

from src.common.db import InMemoryDatabase
from src.common.models import BookingStatus, MachineType, OptionType, ProviderStatus, ProviderType
from src.marketplace import services


@pytest.fixture
def db():
    database = InMemoryDatabase()
    database.clear_all()
    return database


def test_register_provider_lifecycle(db):
    # 1. Register
    provider, notifs = services.register_provider(
        db=db,
        provider_id="PRV_001",
        provider_type=ProviderType.CHC,
        name="Kisan Seva CHC",
        contact_phone="9876543210",
        district="Ludhiana",
        state="Punjab",
        lat=30.9010,
        lon=75.8573,
        telegram_chat_id=12345,
        admin_chat_ids=[999],
    )
    assert provider.status == ProviderStatus.PENDING
    assert len(notifs) == 1
    assert notifs[0].chat_id == 999

    # 2. Approve
    approved, notifs = services.approve_provider(db, "PRV_001", admin_chat_id=999)
    assert approved.status == ProviderStatus.VERIFIED
    assert len(notifs) == 1
    assert notifs[0].chat_id == 12345

    # 3. Suspend
    suspended, notifs = services.suspend_provider(db, "PRV_001", admin_chat_id=999)
    assert suspended.status == ProviderStatus.SUSPENDED
    assert len(notifs) == 1

    # 4. Reject
    rejected, notifs = services.reject_provider(db, "PRV_001", admin_chat_id=999)
    assert rejected.status == ProviderStatus.REJECTED


def test_add_and_update_machine(db):
    mch, _ = services.add_machine(
        db=db,
        machine_id="MCH_101",
        provider_id="PRV_001",
        machine_type=MachineType.SUPER_SEEDER,
        village="Raikot",
        district="Ludhiana",
        lat=30.6500,
        lon=75.6000,
        rate_per_acre=1800.0,
        travel_charge_per_km=15.0,
        service_radius_km=30.0,
    )
    assert mch.status == "ACTIVE"
    assert mch.rate_per_acre == 1800.0

    # Block date
    b_date = date(2026, 10, 25)
    updated, _ = services.set_machine_unavailable(db, "MCH_101", b_date)
    assert b_date in updated.blocked_dates

    # Update rates & deactivate
    updated, _ = services.update_machine(db, "MCH_101", rate_per_acre=1700.0)
    assert updated.rate_per_acre == 1700.0

    deact, _ = services.deactivate_machine(db, "MCH_101")
    assert deact.status == "INACTIVE"

    react, _ = services.reactivate_machine(db, "MCH_101")
    assert react.status == "ACTIVE"


def test_list_nearby_machines(db):
    services.register_provider(
        db=db,
        provider_id="PRV_001",
        provider_type=ProviderType.CHC,
        name="Ludhiana CHC",
        contact_phone="9876543210",
        district="Ludhiana",
        state="Punjab",
        lat=30.9010,
        lon=75.8573,
    )
    services.approve_provider(db, "PRV_001", admin_chat_id=999)

    services.add_machine(
        db=db,
        machine_id="MCH_001",
        provider_id="PRV_001",
        machine_type=MachineType.SUPER_SEEDER,
        village="Sarabha",
        district="Ludhiana",
        lat=30.9000,
        lon=75.8500,
        rate_per_acre=1600.0,
        travel_charge_per_km=0.0,
        service_radius_km=40.0,
    )

    views = services.list_nearby_machines(db, lat=30.9010, lon=75.8573, radius_km=50.0)
    assert len(views) == 1
    assert views[0].machine_id == "MCH_001"
    assert views[0].provider_name == "Ludhiana CHC"
    assert views[0].distance_km is not None
    assert views[0].distance_km < 5.0


def test_register_lender_constraints(db):
    # 1. Register lender
    provider, machine, notifs = services.register_lender(
        db=db,
        provider_id="PRV_LEND_1",
        name="Harpreet Singh",
        contact_phone="9811122233",
        district="Patiala",
        state="Punjab",
        lat=30.3753,
        lon=76.1517,
        telegram_chat_id=7777,
        machine_type=MachineType.SUPER_SEEDER,
        rate_per_acre=1500.0,
        travel_charge_per_km=10.0,
        service_radius_km=25.0,
        terms_note="Driver included, farmer pays diesel",
        phone_verified=True,
        admin_chat_ids=[999],
    )
    assert provider.provider_type == ProviderType.LENDER
    assert provider.status == ProviderStatus.PENDING
    assert provider.phone_verified is True
    assert machine.terms_note == "Driver included, farmer pays diesel"
    assert "YES" in notifs[0].text

    # 2. One provider per account rejected
    with pytest.raises(ValueError, match="already registered"):
        services.register_lender(
            db=db,
            provider_id="PRV_LEND_2",
            name="Another Name",
            contact_phone="9899999999",
            district="Patiala",
            state="Punjab",
            lat=30.3753,
            lon=76.1517,
            telegram_chat_id=7777,
            machine_type=MachineType.SUPER_SEEDER,
            rate_per_acre=1500.0,
            travel_charge_per_km=0.0,
            service_radius_km=20.0,
        )

    # 3. Duplicate phone rejected across providers
    with pytest.raises(ValueError, match="phone number already exists"):
        services.register_lender(
            db=db,
            provider_id="PRV_LEND_3",
            name="Third Name",
            contact_phone="9811122233",  # same phone
            district="Ludhiana",
            state="Punjab",
            lat=30.9,
            lon=75.8,
            telegram_chat_id=8888,
            machine_type=MachineType.SUPER_SEEDER,
            rate_per_acre=1500.0,
            travel_charge_per_km=0.0,
            service_radius_km=20.0,
        )

    # 4. Rate bounds enforced
    with pytest.raises(ValueError, match="below minimum"):
        services.register_lender(
            db=db,
            provider_id="PRV_LEND_LOW",
            name="Low Rate",
            contact_phone="9811100000",
            district="Ludhiana",
            state="Punjab",
            lat=30.9,
            lon=75.8,
            telegram_chat_id=8889,
            machine_type=MachineType.SUPER_SEEDER,
            rate_per_acre=100.0,
            travel_charge_per_km=0.0,
            service_radius_km=20.0,
        )

    # 5. Max 5 machines for LENDER enforced in add_machine
    # First machine was already added in register_lender
    for i in range(2, 6):
        services.add_machine(
            db=db,
            machine_id=f"MCH_LEND_{i}",
            provider_id="PRV_LEND_1",
            machine_type=MachineType.HAPPY_SEEDER,
            village="Patiala",
            district="Patiala",
            lat=30.3753,
            lon=76.1517,
            rate_per_acre=1500.0,
            travel_charge_per_km=0.0,
            service_radius_km=20.0,
        )
    # 6th machine should fail
    with pytest.raises(ValueError, match="at most 5 machines"):
        services.add_machine(
            db=db,
            machine_id="MCH_LEND_6",
            provider_id="PRV_LEND_1",
            machine_type=MachineType.BALER,
            village="Patiala",
            district="Patiala",
            lat=30.3753,
            lon=76.1517,
            rate_per_acre=1500.0,
            travel_charge_per_km=0.0,
            service_radius_km=20.0,
        )


def test_lender_pending_not_recommended_until_verified_and_booking_loop(db):
    # Register lender (PENDING)
    provider, machine, _ = services.register_lender(
        db=db,
        provider_id="PRV_LEND_PEND",
        name="Gurpreet Singh",
        contact_phone="9876541111",
        district="Nabha",
        state="Punjab",
        lat=30.3750,
        lon=76.1500,
        telegram_chat_id=6543,
        machine_type=MachineType.SUPER_SEEDER,
        rate_per_acre=1400.0,
        travel_charge_per_km=5.0,
        service_radius_km=30.0,
        terms_note="Owner provides operator",
        phone_verified=True,
    )

    # PENDING lender machine is not bookable
    bookable = db.list_bookable_machines(lat=30.3750, lon=76.1500, radius_km=50.0)
    assert not any(m.machine_id == machine.machine_id for m in bookable)

    # Admin approves provider
    services.approve_provider(db, "PRV_LEND_PEND", admin_chat_id=999)

    # Now VERIFIED: appears in bookable machines and nearby views with Lender badge and terms_note
    nearby = services.list_nearby_machines(db, lat=30.3750, lon=76.1500, radius_km=50.0)
    lender_view = next(v for v in nearby if v.machine_id == machine.machine_id)
    assert lender_view.provider_type == ProviderType.LENDER
    assert lender_view.terms_note == "Owner provides operator"

    # Farmer creates booking
    booking, notifs = services.create_booking(
        db=db,
        farmer_chat_id=5001,
        target_id=machine.machine_id,
        acres=8.0,
        requested_date=date(2026, 10, 25),
        option_type=OptionType.IN_SITU,
    )
    assert booking.status == BookingStatus.PENDING

    # Lender operator accepts
    updated, notifs = services.owner_decide(
        db=db,
        booking_id=booking.booking_id,
        operator_chat_id=6543,
        accept=True,
    )
    assert updated.status == BookingStatus.CONFIRMED

    # Phone is released to the farmer in notification
    farmer_notif = next(n for n in notifs if n.chat_id == 5001)
    assert "9876541111" in farmer_notif.text

