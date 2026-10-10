"""Top-level Telegram update router and dispatcher for Parali Mitra."""

from __future__ import annotations

import logging
import os
from typing import Any

from src.agent.agent import run_agent_turn  # imported here so tests can monkeypatch
from src.bot import tts_handler, voice_handler
from src.bot.flows import admin, booking, farmer, owner
from src.bot.telegram_client import TelegramClient
from src.bot.voice_config import POLLY_VOICES
from src.common.db import DatabaseClient, get_db_client
from src.common.models import FarmerSession

logger = logging.getLogger(__name__)

_VOICE_REPLY_ENABLED: bool = os.environ.get("VOICE_REPLY_ENABLED", "false").lower() == "true"


async def handle_update(
    update: dict[str, Any],
    client: TelegramClient | None = None,
    db: DatabaseClient | None = None,
    telegram_client: TelegramClient | None = None,
) -> None:
    """Top-level entry point.  Accepts `client` or `telegram_client` for the
    Telegram API client so both the production handler and test fixtures work.
    """
    tg = client or telegram_client
    if tg is None:
        raise ValueError("Either 'client' or 'telegram_client' must be provided")
    db_client = db or get_db_client()
    await route_update(update, db=db_client, telegram_client=tg)


async def route_update(
    update: dict[str, Any],
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Primary router for incoming Telegram updates."""
    update_id = update.get("update_id")
    if update_id is not None:
        if db.is_update_processed(update_id):
            logger.info("[Router] Duplicate update %s skipped", update_id)
            return
        db.mark_update_processed(update_id)

    if "callback_query" in update:
        await _route_callback_query(update["callback_query"], db, telegram_client)
    elif "message" in update:
        await _route_message(update["message"], db, telegram_client)


async def _route_callback_query(
    cq: dict[str, Any],
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    cq_id = cq.get("id")
    if cq_id:
        await telegram_client.answer_callback_query(cq_id)

    data = cq.get("data", "")
    user = cq.get("from", {})
    chat_id = user.get("id") or cq.get("message", {}).get("chat", {}).get("id")
    if not chat_id:
        return

    session = db.get_session(chat_id) or FarmerSession(chat_id=chat_id, language="hi")
    lang = session.language or "hi"

    if data.startswith("lang:"):
        await farmer.handle_language_callback(data, chat_id, session, db, telegram_client)
    elif data.startswith("adm_"):
        await admin.handle_admin_callback(data, chat_id, db, telegram_client, lang=lang)
    elif data.startswith("own_") or data.startswith("mch_type:"):
        await owner.handle_owner_callback(data, chat_id, db, telegram_client, lang=lang)
    elif (
        data.startswith("bk_")
        or data.startswith("book_opt:")
        or data.startswith("confirm_book:")
        or data == "cancel_book"
    ):
        await booking.handle_booking_callback(data, chat_id, db, telegram_client, lang=lang)
    elif data.startswith("tts:"):
        # Voice reply: synthesize the cached last assistant message with Polly
        await tts_handler.handle_tts_callback(data, chat_id, session, telegram_client)


async def _route_message(
    msg: dict[str, Any],
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    if not chat_id:
        return

    session = db.get_session(chat_id)
    if not session:
        session = FarmerSession(chat_id=chat_id, language="hi")
        db.put_session(session)

    # 1. Location Pin attachment — save lat/lon then invoke agent via router-level run_agent_turn
    if "location" in msg:
        loc = msg["location"]
        lat = loc.get("latitude", 0.0)
        lon = loc.get("longitude", 0.0)
        session.lat = lat
        session.lon = lon
        db.put_session(session)
        lang = session.language or "hi"
        loc_label = session.village_text or session.district or f"{lat:.4f}, {lon:.4f}"
        loc_msg = f"📍 Location received: {loc_label}. How many acres of paddy do you have and when is your sowing deadline?"
        try:
            await telegram_client.send_chat_action(chat_id, "typing")
            response_text = await run_agent_turn(
                chat_id=chat_id,
                user_message=f"My farm location is at GPS coordinates ({lat:.6f}, {lon:.6f}). {loc_label}",
                db=db,
            )
            await telegram_client.send_message(chat_id, response_text)
        except Exception as exc:
            logger.warning("[Router] Agent error on location for %s: %s", chat_id, exc)
            await telegram_client.send_message(chat_id, loc_msg)
        return

    # 2. Voice / audio messages — full STT pipeline via Amazon Transcribe
    if "voice" in msg or "audio" in msg:
        transcript = await voice_handler.handle_voice_message(
            msg=msg, session=session, db=db, telegram_client=telegram_client
        )
        if transcript is None:
            # Error already surfaced to farmer; nothing more to do
            return
        # Run the normal agent turn with the transcript as the user's message
        lang = session.language or "hi"
        try:
            await telegram_client.send_chat_action(chat_id, "typing")
            response_text = await run_agent_turn(
                chat_id=chat_id,
                user_message=transcript,
                db=db,
            )
            reply_markup = _build_reply_markup(response_text, session, lang)
            await telegram_client.send_message(chat_id, response_text, reply_markup=reply_markup)
        except Exception as exc:
            logger.error("[Router] Agent voice turn error for chat %s: %s", chat_id, exc)
            await telegram_client.send_message(
                chat_id, "⚠️ Service is busy. Please type /options or /machines to proceed."
            )
        return

    # 3. Text message processing
    text = msg.get("text", "").strip()
    if not text:
        return

    # Check if user is in an active interactive chat flow (e.g. owner registration)
    flow = db.get_chat_flow(chat_id)
    if flow and not text.startswith("/"):
        handled = await owner.handle_owner_text_input(
            text=text,
            chat_id=chat_id,
            db=db,
            telegram_client=telegram_client,
            flow=flow,
            lang=session.language or "hi",
        )
        if handled:
            return

    # Command routing
    cmd = text.split()[0].lower()
    if cmd == "/start":
        await farmer.handle_start(chat_id, db, telegram_client)
    elif cmd == "/help":
        await farmer.handle_help(chat_id, session, telegram_client)
    elif cmd == "/language":
        await farmer.handle_language_command(chat_id, telegram_client)
    elif cmd == "/status":
        await farmer.handle_status(chat_id, session, telegram_client)
    elif cmd == "/reset":
        await farmer.handle_reset(chat_id, session, db, telegram_client)
    elif cmd == "/forget_me":
        await farmer.handle_forget_me(chat_id, db, telegram_client, lang=session.language or "hi")
    elif cmd == "/owner":
        await owner.handle_owner_command(text, chat_id, db, telegram_client, lang=session.language or "hi")
    elif cmd == "/admin":
        await admin.handle_admin_command(chat_id, db, telegram_client, lang=session.language or "en")
    elif cmd == "/mymachines":
        await owner.show_owner_machines(chat_id, db, telegram_client)
    elif cmd == "/machines":
        await farmer.handle_machines_command(chat_id, session, db, telegram_client)
    elif cmd == "/mybookings":
        # If registered provider, show incoming operator jobs; otherwise show farmer's requests
        provider = db.get_provider_by_chat_id(chat_id)
        if provider:
            await owner.show_owner_incoming_bookings(chat_id, db, telegram_client)
        else:
            await farmer.handle_mybookings_command(chat_id, session, db, telegram_client)
    elif cmd == "/options":
        await farmer.handle_options_command(chat_id, session, db, telegram_client)
    else:
        # Free conversational dialogue via Strands Agent (called at router level so tests can monkeypatch)
        lang = session.language or "hi"
        try:
            await telegram_client.send_chat_action(chat_id, "typing")
            response_text = await run_agent_turn(
                chat_id=chat_id,
                user_message=text,
                db=db,
            )
            reply_markup = _build_reply_markup(response_text, session, lang)
            await telegram_client.send_message(chat_id, response_text, reply_markup=reply_markup)
        except Exception as exc:
            logger.error("[Router] Agent text turn error for chat %s: %s", chat_id, exc)
            await telegram_client.send_message(
                chat_id, "⚠️ Service is busy. Please type /options or /machines to proceed."
            )


def _build_reply_markup(
    response_text: str,
    session: FarmerSession,
    lang: str,
) -> dict[str, Any] | None:
    """Builds the inline keyboard for an agent response.

    - Always attaches the /options keyboard if last_options are cached.
    - If VOICE_REPLY_ENABLED and the farmer's language has a Polly voice,
      appends a '🔊 Listen' button that triggers TTS via callback 'tts:last'.
      The last response text is cached on the session object for retrieval.
    """
    # Cache last response for TTS callback (no DB write; in-process for Lambda)
    object.__setattr__(session, "_voice_last_response", response_text) if hasattr(
        session, "__dict__"
    ) else None
    try:
        session._voice_last_response = response_text  # type: ignore[attr-defined]
    except Exception:
        pass

    inline_rows: list[list[dict[str, str]]] = []

    # Options keyboard rows (first)
    options_markup: dict[str, Any] | None = None
    if session.last_options:
        from src.bot.keyboards import get_options_keyboard
        options_markup = get_options_keyboard(session.last_options[:5], lang=lang)
        if options_markup and "inline_keyboard" in options_markup:
            inline_rows.extend(options_markup["inline_keyboard"])

    # TTS 'Listen' button (appended as a separate row)
    if _VOICE_REPLY_ENABLED and lang in POLLY_VOICES:
        inline_rows.append(
            [{"text": "🔊 Listen", "callback_data": "tts:last"}]
        )

    if not inline_rows:
        return options_markup  # original markup or None

    return {"inline_keyboard": inline_rows}
