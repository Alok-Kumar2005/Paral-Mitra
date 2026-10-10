"""Unit tests for Provider Marketplace services."""

from datetime import date, datetime, timedelta, timezone
import pytest

from src.common.db import InMemoryDatabase
from src.common.models import MachineType, OptionType, ProviderStatus, ProviderType
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
