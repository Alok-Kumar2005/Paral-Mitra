"""Unit tests for Telegram update router branches."""

from __future__ import annotations

from datetime import date
from typing import Any
import pytest

from src.bot.router import handle_update
from src.bot.telegram_client import TelegramClient
from src.common.db import InMemoryDatabase
from src.common.models import FarmerSession


class RecordingTelegramClient(TelegramClient):
    """Mock TelegramClient that records all outgoing method calls in memory."""

    def __init__(self) -> None:
        super().__init__(token="FAKE_TOKEN")
        self.sent_messages: list[dict[str, Any]] = []
        self.sent_actions: list[dict[str, Any]] = []
        self.answered_callbacks: list[dict[str, Any]] = []

    async def sendMessage(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> list[dict[str, Any]]:
        record = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        }
        self.sent_messages.append(record)
        return [{"message_id": len(self.sent_messages), **record}]

    async def sendChatAction(self, chat_id: int | str, action: str = "typing") -> dict[str, Any]:
        self.sent_actions.append({"chat_id": chat_id, "action": action})
        return True

    async def answerCallbackQuery(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int = 0,
    ) -> dict[str, Any]:
        self.answered_callbacks.append({
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        })
        return True


@pytest.fixture
def mock_db() -> InMemoryDatabase:
    db = InMemoryDatabase()
    db.clear_all()
    return db


@pytest.fixture
def mock_client() -> RecordingTelegramClient:
    return RecordingTelegramClient()


# ── Router Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_router_start_command(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    update = {
        "update_id": 1001,
        "message": {
            "message_id": 1,
            "chat": {"id": 1111},
            "from": {"id": 1111, "first_name": "Gurpreet"},
            "text": "/start",
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 1
    msg = mock_client.sent_messages[0]
    assert msg["chat_id"] == 1111
    assert "Parali Mitra" in msg["text"]
    assert "inline_keyboard" in msg["reply_markup"]


@pytest.mark.asyncio
async def test_router_language_callback(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    update = {
        "update_id": 1002,
        "callback_query": {
            "id": "cb_1",
            "from": {"id": 2222, "first_name": "Balwinder"},
            "data": "lang:pa",
            "message": {"chat": {"id": 2222}},
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    session = mock_db.get_session(2222)
    assert session is not None
    assert session.language == "pa"

    assert len(mock_client.answered_callbacks) == 1
    assert len(mock_client.sent_messages) == 1
    assert "ਪੰਜਾਬੀ" in mock_client.sent_messages[0]["text"]
    assert "keyboard" in mock_client.sent_messages[0]["reply_markup"]


@pytest.mark.asyncio
async def test_router_location_message(
    mock_db: InMemoryDatabase,
    mock_client: RecordingTelegramClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_turn(chat_id: int, user_message: str, **kwargs: Any) -> str:
        return "Received coordinates. How many acres is your paddy farm?"

    monkeypatch.setattr("src.bot.router.run_agent_turn", fake_run_turn)

    update = {
        "update_id": 1003,
        "message": {
            "message_id": 3,
            "chat": {"id": 3333},
            "location": {"latitude": 30.34, "longitude": 76.38},
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    session = mock_db.get_session(3333)
    assert session is not None
    assert session.lat == 30.34
    assert session.lon == 76.38

    assert len(mock_client.sent_actions) == 1
    assert mock_client.sent_actions[0]["action"] == "typing"
    assert len(mock_client.sent_messages) == 1
    assert "Received coordinates" in mock_client.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_router_voice_message(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    """Voice messages now invoke the real STT pipeline.

    In the unit-test environment (no S3_BUCKET_NAME, boto3 blocked by conftest),
    the pipeline sends:
      1. A "processing…" notice
      2. An error fallback asking the farmer to type or resend

    The test verifies that at least one message was sent and that the farmer
    receives a meaningful response (not silence).
    """
    update = {
        "update_id": 1004,
        "message": {
            "message_id": 4,
            "chat": {"id": 4444},
            "voice": {"file_id": "voice_123", "duration": 5},
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    # At least one message must reach the farmer (processing notice or fallback)
    assert len(mock_client.sent_messages) >= 1
    # All sent messages must target the correct chat
    for msg in mock_client.sent_messages:
        assert msg["chat_id"] == 4444



@pytest.mark.asyncio
async def test_router_help_command(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    update = {
        "update_id": 1005,
        "message": {
            "message_id": 5,
            "chat": {"id": 5555},
            "text": "/help",
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 1
    assert "/start" in mock_client.sent_messages[0]["text"]
    assert "/help" in mock_client.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_router_reset_command(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    # Setup prior session state
    session = FarmerSession(chat_id=6666, acres=10.0, lat=30.3, lon=76.4, language="hi")
    mock_db.put_session(session)

    update = {
        "update_id": 1006,
        "message": {
            "message_id": 6,
            "chat": {"id": 6666},
            "text": "/reset",
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    updated = mock_db.get_session(6666)
    assert updated.acres is None
    assert updated.lat is None

    assert len(mock_client.sent_messages) == 1
    assert "रीसेट" in mock_client.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_router_owner_command(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    update = {
        "update_id": 1007,
        "message": {
            "message_id": 7,
            "chat": {"id": 7777},
            "text": "/owner secretpass123",
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 1
    assert "CHC" in mock_client.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_router_text_message_to_agent(
    mock_db: InMemoryDatabase,
    mock_client: RecordingTelegramClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_turn(chat_id: int, user_message: str, **kwargs: Any) -> str:
        return "I found 3 great machinery options for your 8 acres in Patiala."

    monkeypatch.setattr("src.bot.router.run_agent_turn", fake_run_turn)

    update = {
        "update_id": 1008,
        "message": {
            "message_id": 8,
            "chat": {"id": 8888},
            "text": "I have 8 acres of parali in Patiala",
        },
    }

    await handle_update(update, client=mock_client, db=mock_db)

    assert len(mock_client.sent_actions) == 1
    assert len(mock_client.sent_messages) == 1
    assert "8 acres in Patiala" in mock_client.sent_messages[0]["text"]


@pytest.mark.asyncio
async def test_router_booking_callback_flow(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    # 1. Farmer session with cached options
    cached_options = [
        {
            "option_type": "IN_SITU",
            "machine_id": "M_SUPER_1",
            "machine_type": "Super Seeder",
            "provider_id": "CHC_PATIALA_1",
            "provider_name": "KVK Patiala CHC",
            "contact_phone": "+91 98765 43210",
            "net_cost": 7600.0,
        }
    ]
    session = FarmerSession(
        chat_id=9999,
        acres=8.0,
        sowing_deadline=date(2026, 11, 20),
        last_options=cached_options,
    )
    mock_db.put_session(session)

    # 2. Select option callback
    update_select = {
        "update_id": 1009,
        "callback_query": {
            "id": "cb_opt_0",
            "from": {"id": 9999},
            "data": "book_opt:0",
            "message": {"chat": {"id": 9999}},
        },
    }
    await handle_update(update_select, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 1
    assert "Super Seeder" in mock_client.sent_messages[0]["text"]
    assert "inline_keyboard" in mock_client.sent_messages[0]["reply_markup"]

    # 3. Confirm booking callback
    update_confirm = {
        "update_id": 1010,
        "callback_query": {
            "id": "cb_confirm_0",
            "from": {"id": 9999},
            "data": "confirm_book:0",
            "message": {"chat": {"id": 9999}},
        },
    }
    await handle_update(update_confirm, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 2
    assert "Booking Request Submitted" in mock_client.sent_messages[1]["text"]

    bookings = mock_db.list_bookings_by_farmer(9999)
    assert len(bookings) == 1
    assert bookings[0].target_id == "M_SUPER_1"
    assert bookings[0].acres == 8.0


@pytest.mark.asyncio
async def test_router_idempotency_deduplication(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    update = {
        "update_id": 55555,
        "message": {
            "message_id": 1,
            "chat": {"id": 1234},
            "text": "/help",
        },
    }

    # First delivery
    await handle_update(update, client=mock_client, db=mock_db)
    assert len(mock_client.sent_messages) == 1

    # Duplicate delivery (Telegram retry)
    await handle_update(update, client=mock_client, db=mock_db)
    assert len(mock_client.sent_messages) == 1  # No duplicate message sent


@pytest.mark.asyncio
async def test_router_status_command(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    session = FarmerSession(
        chat_id=1212,
        acres=12.0,
        lat=30.8,
        lon=75.8,
        village_text="Kaind, Ludhiana",
        sowing_deadline=date(2026, 11, 15),
        language="en",
    )
    mock_db.put_session(session)

    update = {
        "update_id": 2001,
        "message": {"message_id": 1, "chat": {"id": 1212}, "text": "/status"},
    }
    await handle_update(update, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 1
    text = mock_client.sent_messages[0]["text"]
    assert "Profile Status" in text
    assert "12.0 acres" in text
    assert "Kaind, Ludhiana" in text


@pytest.mark.asyncio
async def test_router_language_command(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    update = {
        "update_id": 2002,
        "message": {"message_id": 2, "chat": {"id": 3434}, "text": "/language"},
    }
    await handle_update(update, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 1
    assert "inline_keyboard" in mock_client.sent_messages[0]["reply_markup"]


@pytest.mark.asyncio
async def test_router_options_command_cached(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    cached = [
        {"target_name": "Super Seeder CHC", "net_cost": 5000.0, "distance_km": 4.2}
    ]
    session = FarmerSession(chat_id=5656, acres=5.0, last_options=cached, language="en")
    mock_db.put_session(session)

    update = {
        "update_id": 2003,
        "message": {"message_id": 3, "chat": {"id": 5656}, "text": "/options"},
    }
    await handle_update(update, client=mock_client, db=mock_db)

    assert len(mock_client.sent_messages) == 1
    assert "Super Seeder CHC" in mock_client.sent_messages[0]["text"]
    assert "inline_keyboard" in mock_client.sent_messages[0]["reply_markup"]


@pytest.mark.asyncio
async def test_router_lend_contact_other_user_rejected(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    chat_id = 7001
    # 1. Initiate /lend
    await handle_update({
        "update_id": 3001,
        "message": {"message_id": 1, "chat": {"id": chat_id}, "text": "/lend"},
    }, client=mock_client, db=mock_db)

    flow = mock_db.get_chat_flow(chat_id)
    assert flow is not None
    assert flow.flow == "LEND"
    assert flow.step == "CONTACT"

    # 2. Send contact from different user
    await handle_update({
        "update_id": 3002,
        "message": {
            "message_id": 2,
            "chat": {"id": chat_id},
            "contact": {"phone_number": "+919876543210", "user_id": 99999},  # mismatch!
        },
    }, client=mock_client, db=mock_db)

    # Should reject and remain on CONTACT step
    flow = mock_db.get_chat_flow(chat_id)
    assert flow.step == "CONTACT"
    assert any("own" in m["text"].lower() or "अपना" in m["text"] for m in mock_client.sent_messages)


@pytest.mark.asyncio
async def test_router_lend_typed_phone_fallback(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient) -> None:
    chat_id = 7002
    await handle_update({
        "update_id": 3003,
        "message": {"message_id": 1, "chat": {"id": chat_id}, "text": "/lend"},
    }, client=mock_client, db=mock_db)

    # User types fallback phone
    await handle_update({
        "update_id": 3004,
        "message": {"message_id": 2, "chat": {"id": chat_id}, "text": "9876543210"},
    }, client=mock_client, db=mock_db)

    flow = mock_db.get_chat_flow(chat_id)
    assert flow.step == "NAME"
    assert flow.data["phone"] == "9876543210"
    assert flow.data["phone_verified"] is False


@pytest.mark.asyncio
async def test_router_lend_typed_coordinates_and_geocode_retry(mock_db: InMemoryDatabase, mock_client: RecordingTelegramClient, monkeypatch: pytest.MonkeyPatch) -> None:
    chat_id = 7003
    from src.common.models import ChatFlow
    # Place flow directly at LOCATION step
    mock_db.put_chat_flow(ChatFlow(
        chat_id=chat_id,
        flow="LEND",
        step="LOCATION",
        data={"name": "Kisan Trader", "phone": "9812345678", "phone_verified": False},
    ))

    # Test geocode failure: mock Geocoder to return None
    from src.connectors.geocode import Geocoder
    async def mock_geocode_none(self, text: str):
        return None
    monkeypatch.setattr(Geocoder, "geocode", mock_geocode_none)

    await handle_update({
        "update_id": 3005,
        "message": {"message_id": 1, "chat": {"id": chat_id}, "text": "UnfindableNonexistentPlace999"},
    }, client=mock_client, db=mock_db)

    # Must ask again, never default to Patiala
    flow = mock_db.get_chat_flow(chat_id)
    assert flow.step == "LOCATION"
    assert any("not find" in m["text"].lower() or "नहीं मिला" in m["text"] for m in mock_client.sent_messages)

    # Now provide typed coordinates "30.41, 76.47"
    async def mock_geocode_coords(self, text: str):
        class GC:
            lat = 30.41
            lon = 76.47
            district = "Patiala"
            state = "Punjab"
        return GC()
    monkeypatch.setattr(Geocoder, "geocode", mock_geocode_coords)

    await handle_update({
        "update_id": 3006,
        "message": {"message_id": 2, "chat": {"id": chat_id}, "text": "30.41, 76.47"},
    }, client=mock_client, db=mock_db)

    flow = mock_db.get_chat_flow(chat_id)
    assert flow.step == "MACHINE_TYPE"
    assert flow.data["lat"] == 30.41
    assert flow.data["lon"] == 76.47


