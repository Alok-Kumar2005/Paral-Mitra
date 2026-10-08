"""Unit tests for Parali Mitra Pydantic domain models."""

from datetime import date, datetime
import pytest
from pydantic import ValidationError

from src.common.models import (
    Booking,
    BookingStatus,
    Buyer,
    BuyerType,
    FarmerSession,
    Hotspot,
    Machine,
    MachineType,
    OptionType,
    TransportTerms,
)


def test_machine_valid():
    m = Machine(
        machine_id="MCH_100",
        owner_name="Baljit Singh",
        owner_phone="+919876543210",
        machine_type=MachineType.SUPER_SEEDER,
        village="Raikot",
        district="Ludhiana",
        lat=30.6500,
        lon=75.6000,
        rate_per_acre=2000.0,
        travel_charge_per_km=25.0,
        service_radius_km=15.0,
        available_from=date(2026, 10, 15),
        blocked_dates=[date(2026, 10, 18)],
        source="CHC_PORTAL",
        is_synthetic=False,
    )
    assert m.machine_id == "MCH_100"
    assert m.rate_per_acre == 2000.0
    assert m.blocked_dates == [date(2026, 10, 18)]
    assert m.owner_telegram_chat_id is None


def test_machine_blocked_dates_string_parsing():
    m = Machine(
        machine_id="MCH_101",
        owner_name="Baljit Singh",
        owner_phone="+919876543210",
        machine_type="HAPPY_SEEDER",
        village="Raikot",
        district="Ludhiana",
        lat=30.6500,
        lon=75.6000,
        rate_per_acre=1800.0,
        travel_charge_per_km=20.0,
        service_radius_km=20.0,
        available_from=date(2026, 10, 15),
        blocked_dates="2026-10-18; 2026-10-19",  # String formatted from CSV
    )
    assert len(m.blocked_dates) == 2
    assert m.blocked_dates[0] == date(2026, 10, 18)
    assert m.blocked_dates[1] == date(2026, 10, 19)


def test_machine_invalid_coordinates():
    with pytest.raises(ValidationError):
        Machine(
            machine_id="MCH_BAD",
            owner_name="Test",
            owner_phone="+919876543210",
            machine_type="SUPER_SEEDER",
            village="V",
            district="D",
            lat=95.0,  # Invalid lat > 90
            lon=75.0,
            rate_per_acre=2000.0,
            travel_charge_per_km=10.0,
            service_radius_km=10.0,
            available_from=date(2026, 10, 10),
        )


def test_machine_negative_rate():
    with pytest.raises(ValidationError):
        Machine(
            machine_id="MCH_BAD",
            owner_name="Test",
            owner_phone="+919876543210",
            machine_type="SUPER_SEEDER",
            village="V",
            district="D",
            lat=30.0,
            lon=75.0,
            rate_per_acre=-500.0,  # Invalid negative
            travel_charge_per_km=10.0,
            service_radius_km=10.0,
            available_from=date(2026, 10, 10),
        )


def test_buyer_valid():
    b = Buyer(
        buyer_id="BYR_01",
        name="Verbio Bio-Gas",
        buyer_type=BuyerType.CBG_PLANT,
        lat=30.12,
        lon=75.80,
        price_per_tonne=1800.0,
        min_quantity_tonnes=10.0,
        transport_terms=TransportTerms.EX_FARM,
        phone="+919876543211",
        is_synthetic=True,
    )
    assert b.buyer_id == "BYR_01"
    assert b.is_synthetic is True


def test_booking_status_and_defaults():
    bk = Booking(
        booking_id="BKG_001",
        farmer_chat_id=12345678,
        option_type=OptionType.IN_SITU,
        target_id="MCH_100",
        acres=5.5,
        requested_date=date(2026, 10, 20),
    )
    assert bk.status == BookingStatus.PENDING
    assert isinstance(bk.created_at, datetime)
    assert bk.acres == 5.5


def test_farmer_session():
    session = FarmerSession(
        chat_id=987654321,
        language="pa",
        lat=30.5,
        lon=76.2,
        acres=12.0,
        sowing_deadline=date(2026, 11, 10),
    )
    assert session.chat_id == 987654321
    assert session.language == "pa"
    assert session.acres == 12.0


def test_hotspot():
    h = Hotspot(
        grid_cell="CELL_30_76",
        lat=30.123,
        lon=76.456,
        acq_date=date(2026, 10, 15),
        frp=42.5,
        confidence="nominal",
    )
    assert h.frp == 42.5
    assert h.confidence == "nominal"
