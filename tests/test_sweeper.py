"""Unit tests for the booking sweeper background job."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest

from src.common.db import InMemoryDatabase
from src.common.models import Booking, BookingStatus, OptionType
from src.handlers.sweeper import _sweep
from src.marketplace import services


@pytest.fixture
def db():
    database = InMemoryDatabase()
    database.clear_all()
    return database


def test_expire_stale_bookings(db):
    now = datetime.now(timezone.utc)
    past_49h = now - timedelta(hours=49)
    past_10h = now - timedelta(hours=10)

    # 1. Stale booking (expired)
    stale_booking = Booking(
        booking_id="BK-STALE01",
        farmer_chat_id=101,
        target_id="MCH_1",
        option_type=OptionType.IN_SITU,
        acres=10.0,
        requested_date=date.today(),
        status=BookingStatus.PENDING,
        created_at=past_49h,
        expires_at=now - timedelta(hours=1),
    )
    db.put_booking(stale_booking)

    # 2. Fresh booking (not expired)
    fresh_booking = Booking(
        booking_id="BK-FRESH01",
        farmer_chat_id=102,
        target_id="MCH_1",
        option_type=OptionType.IN_SITU,
        acres=5.0,
        requested_date=date.today() + timedelta(days=2),
        status=BookingStatus.PENDING,
        created_at=past_10h,
        expires_at=now + timedelta(hours=38),
    )
    db.put_booking(fresh_booking)

    expired, notifs = services.expire_stale_bookings(db, cutoff_utc=now)
    assert len(expired) == 1
    assert expired[0].booking_id == "BK-STALE01"
    assert expired[0].status == BookingStatus.EXPIRED

    # Verify fresh booking is still PENDING
    fresh_check = db.get_booking("BK-FRESH01")
    assert fresh_check.status == BookingStatus.PENDING


@pytest.mark.asyncio
async def test_sweeper_handler(db):
    now = datetime.now(timezone.utc)
    stale_booking = Booking(
        booking_id="BK-SWEEP01",
        farmer_chat_id=201,
        target_id="MCH_1",
        option_type=OptionType.IN_SITU,
        acres=8.0,
        requested_date=date.today(),
        status=BookingStatus.PENDING,
        created_at=now - timedelta(hours=50),
        expires_at=now - timedelta(hours=2),
    )
    db.put_booking(stale_booking)

    with patch("src.handlers.sweeper.TelegramClient") as mock_tg:
        client_instance = AsyncMock()
        mock_tg.return_value.__aenter__.return_value = client_instance

        res = await _sweep(db)
        assert res["ok"] is True
        assert res["expired_count"] == 1
        assert res["notifications_sent"] == 1
        client_instance.send_message.assert_awaited_once()
