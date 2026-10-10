"""Unit tests for farmer ratings on completed bookings."""

from datetime import date, datetime, timezone
import pytest

from src.common.db import InMemoryDatabase
from src.common.models import Booking, BookingStatus, MachineType, OptionType, ProviderType
from src.marketplace import services


@pytest.fixture
def db():
    database = InMemoryDatabase()
    database.clear_all()

    services.register_provider(
        db=database,
        provider_id="PRV_TEST",
        provider_type=ProviderType.CHC,
        name="Ludhiana CHC",
        contact_phone="9876543210",
        district="Ludhiana",
        state="Punjab",
        lat=30.9010,
        lon=75.8573,
    )
    services.approve_provider(database, "PRV_TEST", admin_chat_id=1)

    services.add_machine(
        db=database,
        machine_id="MCH_RATE_TEST",
        provider_id="PRV_TEST",
        machine_type=MachineType.SUPER_SEEDER,
        village="Raikot",
        district="Ludhiana",
        lat=30.9000,
        lon=75.8500,
        rate_per_acre=1500.0,
        travel_charge_per_km=0.0,
        service_radius_km=30.0,
    )
    return database


def test_rating_updates_machine_average(db):
    booking = Booking(
        booking_id="BK-RATE01",
        farmer_chat_id=501,
        provider_id="PRV_TEST",
        option_type=OptionType.IN_SITU,
        target_id="MCH_RATE_TEST",
        acres=10.0,
        requested_date=date.today(),
        status=BookingStatus.COMPLETED,
    )
    db.put_booking(booking)

    # First rating: 5 stars
    rated_booking, notifs = services.rate_provider(db, "BK-RATE01", farmer_chat_id=501, rating=5)
    assert rated_booking.rating == 5
    assert len(notifs) == 1

    machine = db.get_machine("MCH_RATE_TEST")
    assert machine.rating_count == 1
    assert machine.rating_avg == 5.0

    # Second rating on new booking: 3 stars
    b2 = Booking(
        booking_id="BK-RATE02",
        farmer_chat_id=502,
        provider_id="PRV_TEST",
        option_type=OptionType.IN_SITU,
        target_id="MCH_RATE_TEST",
        acres=5.0,
        requested_date=date.today(),
        status=BookingStatus.COMPLETED,
    )
    db.put_booking(b2)
    services.rate_provider(db, "BK-RATE02", farmer_chat_id=502, rating=3)

    machine2 = db.get_machine("MCH_RATE_TEST")
    assert machine2.rating_count == 2
    assert machine2.rating_avg == 4.0  # (5 + 3) / 2


def test_invalid_rating_rejected(db):
    with pytest.raises(ValueError):
        services.rate_provider(db, "BK-TEST", farmer_chat_id=501, rating=6)

    with pytest.raises(ValueError):
        services.rate_provider(db, "BK-TEST", farmer_chat_id=501, rating=0)
