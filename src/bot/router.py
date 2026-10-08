"""Telegram update router and conversation coordinator for Parali Mitra."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
import uuid

from src.agent.agent import run_agent_turn
from src.agent.memory import clear_session_history
from src.bot.keyboards import (
    get_booking_confirm_keyboard,
    get_language_keyboard,
    get_location_keyboard,
    get_options_keyboard,
    get_remove_keyboard,
)
from src.bot.telegram_client import TelegramClient
from src.common.db import DatabaseClient, get_db_client
from src.common.models import Booking, BookingStatus, FarmerSession, OptionType

logger = logging.getLogger(__name__)

# ── Localized Messages ────────────────────────────────────────────────────────

GREETING_TEXT = (
    "🙏 *Welcome to Parali Mitra (पराली मित्र / ਪਰਾਲੀ ਮਿੱਤਰ)*\n\n"
    "I help paddy farmers in Punjab & Haryana manage crop residue profitably and sustainably without burning.\n\n"
    "Please choose your preferred language:\n"
    "कृपया अपनी भाषा चुनें:\n"
    "ਕਿਰਪਾ ਕਰਕੇ ਆਪਣੀ ਭਾਸ਼ਾ ਚੁਣੋ:"
)

LANGUAGE_ACK_TEXTS = {
    "en": (
        "✅ Language set to *English*.\n\n"
        "🌾 *How Parali Mitra helps you:*\n"
        "1. Compare in-situ machinery (Super Seeder, Happy Seeder, Mulcher) vs ex-situ biomass sales (CBG, Pellet units).\n"
        "2. Deterministic cost/profit ranking & weather-aligned scheduling.\n"
        "3. Direct booking with verified Custom Hiring Centres (CHCs).\n\n"
        "👉 *To get started:*\n"
        "• Tap the button below to share your farm location pin (or type your village & district).\n"
        "• Tell me your paddy acres and wheat sowing deadline."
    ),
    "hi": (
        "✅ भाषा *हिन्दी* सेट की गई।\n\n"
        "🌾 *पराली मित्र आपकी सहायता कैसे करता है:*\n"
        "1. इन-सिटू मशीनरी (सुपर सीडर, हैप्पी सीडर, मल्चर) और एक्स-सिटू बिक्री (CBG, बॉयोमास प्लांट) के विकल्पों की तुलना।\n"
        "2. शुद्ध लागत/मुनाफ़ा और मौसम आधारित सटीक समय सारिणी।\n"
        "3. नज़दीकी कस्टम हायरिंग सेंटर (CHC) से सीधी बुकिंग।\n\n"
        "👉 *शुरू करने के लिए:*\n"
        "• नीचे दिए बटन से अपने खेत का स्थान (GPS Pin) साझा करें या अपने गाँव/ज़िले का नाम लिखें।\n"
        "• अपनी धान की ज़मीन (एकड़) और गेहूँ बुवाई की तारीख बताएं।"
    ),
    "pa": (
        "✅ ਭਾਸ਼ਾ *ਪੰਜਾਬੀ* ਚੁਣੀ ਗਈ।\n\n"
        "🌾 *ਪਰਾਲੀ ਮਿੱਤਰ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰਦਾ ਹੈ:*\n"
        "1. ਇਨ-ਸੀਟੂ ਮਸ਼ੀਨਰੀ (ਸੁਪਰ ਸੀਡਰ, ਹੈਪੀ ਸੀਡਰ, ਮਲਚਰ) ਅਤੇ ਐਕਸ-ਸੀਟੂ ਪਰਾਲੀ ਵਿਕਰੀ (CBG, ਪੈਲੇਟ ਪਲਾਂਟ) ਦੀ ਤੁਲਨਾ।\n"
        "2. ਸਹੀ ਲਾਗਤ/ਮੁਨਾਫ਼ਾ ਅਤੇ ਮੌਸਮ ਅਨੁਸਾਰ ਤਾਰੀਖ਼ਾਂ।\n"
        "3. ਨੇੜਲੇ ਕਸਟਮ ਹਾਇਰਿੰਗ ਸੈਂਟਰ (CHC) ਤੋਂ ਸਿੱਧੀ ਬੁਕਿੰਗ।\n\n"
        "👉 *ਸ਼ੁਰੂ ਕਰਨ ਲਈ:*\n"
        "• ਹੇਠਾਂ ਦਿੱਤੇ ਬਟਨ ਨਾਲ ਆਪਣੇ ਖੇਤ ਦਾ ਸਥਾਨ ਸਾਂਝਾ ਕਰੋ ਜਾਂ ਆਪਣੇ ਪਿੰਡ ਤੇ ਜ਼ਿਲ੍ਹੇ ਦਾ ਨਾਮ ਦੱਸੋ।\n"
        "• ਆਪਣੀ ਝੋਨੇ ਦੀ ਜ਼ਮੀਨ (ਏਕੜ) ਅਤੇ ਕਣਕ ਬਿਜਾਈ ਦੀ ਆਖ਼ਰੀ ਤਾਰੀਖ਼ ਦੱਸੋ।"
    ),
}

HELP_TEXTS = {
    "en": (
        "📖 *Parali Mitra Help & Commands*\n\n"
        "• `/start` — Restart conversation & choose language.\n"
        "• `/options` — View recommended residue management options.\n"
        "• `/status` — View your saved farm profile & session details.\n"
        "• `/language` — Change your preferred language.\n"
        "• `/reset` — Clear conversation history and start fresh.\n"
        "• `/help` — View this guidance.\n"
        "• `/owner <passcode>` — CHC machine owner portal.\n\n"
        "💡 *Tips for best recommendations:*\n"
        "- Share your GPS location pin for accurate CHC distances and transport costs.\n"
        "- Provide farm size in acres and target wheat sowing deadline.\n"
        "- Tell me if you want to sell straw directly to CBG / biomass buyers."
    ),
    "hi": (
        "📖 *पराली मित्र सहायता और कमांड्स*\n\n"
        "• `/start` — बातचीत शुरू करें और भाषा चुनें।\n"
        "• `/options` — पराली प्रबंधन के अनुशंसित विकल्प देखें।\n"
        "• `/status` — अपनी सहेजी गई जानकारी देखें।\n"
        "• `/language` — अपनी भाषा बदलें।\n"
        "• `/reset` — पुराना सत्र साफ़ करके नया शुरू करें।\n"
        "• `/help` — सहायता गाइड देखें।\n"
        "• `/owner <passcode>` — CHC मशीन मालिक पोर्टल।\n\n"
        "💡 *सटीक सलाह के लिए:*\n"
        "- सही दूरी और किराए के लिए अपना GPS स्थान साझा करें।\n"
        "- अपने खेत का रकबा (एकड़) और गेहूँ बुवाई की अंतिम तारीख बताएं।"
    ),
    "pa": (
        "📖 *ਪਰਾਲੀ ਮਿੱਤਰ ਮਦਦ ਅਤੇ ਕਮਾਂਡਾਂ*\n\n"
        "• `/start` — ਗੱਲਬਾਤ ਸ਼ੁਰੂ ਕਰੋ ਅਤੇ ਭਾਸ਼ਾ ਚੁਣੋ।\n"
        "• `/options` — ਸਿਫ਼ਾਰਸ਼ ਕੀਤੇ ਪਰਾਲੀ ਪ੍ਰਬੰਧਨ ਵਿਕਲਪ ਵੇਖੋ।\n"
        "• `/status` — ਆਪਣੀ ਸੰਭਾਲੀ ਜਾਣਕਾਰੀ ਵੇਖੋ।\n"
        "• `/language` — ਆਪਣੀ ਭਾਸ਼ਾ ਬਦਲੋ।\n"
        "• `/reset` — ਪੁਰਾਣਾ ਸੈਸ਼ਨ ਸਾਫ਼ ਕਰਕੇ ਨਵਾਂ ਸ਼ੁਰੂ ਕਰੋ।\n"
        "• `/help` — ਮਦਦ ਗਾਈਡ ਵੇਖੋ।\n"
        "• `/owner <passcode>` — CHC ਮਸ਼ੀਨ ਮਾਲਕ ਪੋਰਟਲ।\n\n"
        "💡 *ਸਹੀ ਸਲਾਹ ਲਈ:*\n"
        "- ਸਹੀ ਦੂਰੀ ਅਤੇ ਕਿਰਾਏ ਲਈ ਆਪਣਾ GPS ਸਥਾਨ ਸਾਂਝਾ ਕਰੋ।\n"
        "- ਆਪਣੇ ਖੇਤ ਦਾ ਰਕਬਾ (ਏਕੜ) ਅਤੇ ਕਣਕ ਬਿਜਾਈ ਦੀ ਆਖ਼ਰੀ ਤਾਰੀਖ਼ ਦੱਸੋ।"
    ),
}

RESET_TEXTS = {
    "en": "🔄 Conversation memory has been reset. How can I help you manage your paddy straw today?",
    "hi": "🔄 आपका सत्र रीसेट कर दिया गया है। आज मैं आपकी पराली प्रबंधन में कैसे सहायता कर सकता हूँ?",
    "pa": "🔄 ਤੁਹਾਡਾ ਸੈਸ਼ਨ ਰੀਸੈਟ ਕਰ ਦਿੱਤਾ ਗਿਆ ਹੈ। ਅੱਜ ਮੈਂ ਪਰਾਲੀ ਪ੍ਰਬੰਧਨ ਵਿੱਚ ਤੁਹਾਡੀ ਕੀ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?",
}

VOICE_SOON_TEXTS = {
    "en": "🎙️ Voice notes are coming soon in Step 9! Please type your message in English, Hindi, or Punjabi for now.",
    "hi": "🎙️ वॉइस मैसेज की सुविधा स्टेप 9 में जल्द आ रही है! कृपया अभी अपना संदेश टाइप करके भेजें।",
    "pa": "🎙️ ਵੌਇਸ ਮੈਸੇਜ ਦੀ ਸਹੂਲਤ ਸਟੈਪ 9 ਵਿੱਚ ਜਲਦੀ ਆ ਰਹੀ ਹੈ! ਕਿਰਪਾ ਕਰਕੇ ਹੁਣ ਲਈ ਆਪਣਾ ਸੰਦੇਸ਼ ਟਾਈਪ ਕਰਕੇ ਭੇਜੋ।",
}

OWNER_STUB_TEXTS = {
    "en": (
        "🌾 *CHC Machine Owner Portal*\n\n"
        "Owner registration is currently in closed preview for Step 8.\n"
        "To register your Custom Hiring Centre or equipment, please contact your local Agriculture Development Officer (ADO)."
    ),
    "hi": (
        "🌾 *कस्टम हायरिंग सेंटर (CHC) मालिक पोर्टल*\n\n"
        "मशीन मालिक पंजीकरण स्टेप 8 के लिए पूर्वावलोकन में है।\n"
        "अपने उपकरण सूचीबद्ध करने के लिए कृपया अपने ब्लॉक कृषि अधिकारी से संपर्क करें।"
    ),
    "pa": (
        "🌾 *ਕਸਟਮ ਹਾਇਰਿੰਗ ਸੈਂਟਰ (CHC) ਮਾਲਕ ਪੋਰਟਲ*\n\n"
        "ਮਸ਼ੀਨ ਮਾਲਕ ਰਜਿਸਟ੍ਰੇਸ਼ਨ ਸਟੈਪ 8 ਲਈ ਬੰਦ ਪ੍ਰੀਵਿਊ ਵਿੱਚ ਹੈ।\n"
        "ਆਪਣੇ ਸੰਦ ਦਰਜ ਕਰਵਾਉਣ ਲਈ ਕਿਰਪਾ ਕਰਕੇ ਆਪਣੇ ਬਲਾਕ ਖੇਤੀਬਾੜੀ ਅਫ਼ਸਰ ਨਾਲ ਸੰਪਰਕ ਕਰੋ।"
    ),
}


# ── Update Handler ────────────────────────────────────────────────────────────


async def handle_update(
    update: dict[str, Any],
    client: TelegramClient | None = None,
    db: DatabaseClient | None = None,
) -> None:
    """Entry point for handling incoming Telegram webhook and polling updates."""
    database = db or get_db_client()
    tg_client = client or TelegramClient()

    # 1. Idempotency Guard
    update_id = update.get("update_id")
    if update_id is not None:
        if database.is_update_processed(update_id):
            logger.info("Ignoring duplicate update_id=%s", update_id)
            return
        database.mark_update_processed(update_id)

    # 2. Callback Queries (Inline button clicks)
    if "callback_query" in update:
        await _handle_callback_query(update["callback_query"], tg_client, database)
        return

    # 3. Message Handling
    if "message" in update:
        await _handle_message(update["message"], tg_client, database)
        return

    logger.debug("Unhandled update structure: %s", list(update.keys()))


async def _handle_callback_query(
    cb: dict[str, Any],
    client: TelegramClient,
    db: DatabaseClient,
) -> None:
    cb_id = str(cb.get("id", ""))
    from_user = cb.get("from", {})
    chat_id = int(from_user.get("id") or cb.get("message", {}).get("chat", {}).get("id", 0))
    data = str(cb.get("data", ""))

    if not chat_id:
        await client.answerCallbackQuery(cb_id)
        return

    session = db.get_session(chat_id)
    if session is None:
        session = FarmerSession(chat_id=chat_id)
        db.put_session(session)

    lang = session.language or "hi"

    # Language selection
    if data.startswith("lang:"):
        selected_lang = data.split(":", 1)[1]
        session.language = selected_lang
        session.last_seen_at = datetime.now(timezone.utc)
        db.put_session(session)

        ack_text = LANGUAGE_ACK_TEXTS.get(selected_lang, LANGUAGE_ACK_TEXTS["hi"])
        await client.answerCallbackQuery(cb_id, text=f"Language: {selected_lang.upper()}")
        await client.sendMessage(
            chat_id=chat_id,
            text=ack_text,
            reply_markup=get_location_keyboard(selected_lang),
        )
        return

    # Booking option selection
    if data.startswith("book_opt:"):
        try:
            opt_idx = int(data.split(":", 1)[1])
            cached_opts = session.last_options or []
            if 0 <= opt_idx < len(cached_opts):
                opt = cached_opts[opt_idx]
                name = (
                    opt.get("target_name")
                    or opt.get("display_name")
                    or opt.get("machine_type")
                    or opt.get("buyer_type")
                    or opt.get("category")
                    or f"Option #{opt_idx + 1}"
                )
                net_cost = opt.get("net_cost", 0)
                cost_str = f"₹{abs(int(net_cost)):,}"
                cost_desc = f"+{cost_str} (Profit/Subsidy)" if net_cost < 0 else f"-{cost_str} (Net Cost)"
                dist = opt.get("distance_km", 0.0)

                msg = (
                    f"🚜 *Booking Confirmation Request*\n\n"
                    f"• *Selected Option:* {name}\n"
                    f"• *Distance:* {dist:.1f} km\n"
                    f"• *Acreage:* {session.acres or 'As specified'} acres\n"
                    f"• *Estimated Economics:* {cost_desc}\n\n"
                    f"Would you like to send this booking request to the Custom Hiring Centre / Aggregator?"
                )
                await client.answerCallbackQuery(cb_id)
                await client.sendMessage(
                    chat_id=chat_id,
                    text=msg,
                    reply_markup=get_booking_confirm_keyboard(opt_idx, lang=lang),
                )
                return
        except Exception as exc:
            logger.error("Error processing book_opt callback: %s", exc)

    # Booking confirmation execution
    if data.startswith("confirm_book:"):
        try:
            opt_idx = int(data.split(":", 1)[1])
            cached_opts = session.last_options or []
            if 0 <= opt_idx < len(cached_opts):
                opt = cached_opts[opt_idx]
                booking_id = f"BK-{uuid.uuid4().hex[:8].upper()}"
                raw_opt_type = opt.get("option_type", "IN_SITU")
                if isinstance(raw_opt_type, OptionType):
                    option_type = raw_opt_type
                elif isinstance(raw_opt_type, str) and raw_opt_type in OptionType._value2member_map_:
                    option_type = OptionType(raw_opt_type)
                else:
                    option_type = OptionType.IN_SITU

                target_id = opt.get("target_id") or opt.get("machine_id") or opt.get("buyer_id") or "UNKNOWN"
                acres = float(session.acres or 5.0)
                requested_date = session.sowing_deadline or datetime.now(timezone.utc).date()

                booking = Booking(
                    booking_id=booking_id,
                    farmer_chat_id=chat_id,
                    provider_id=opt.get("provider_id") or target_id,
                    option_type=option_type,
                    target_id=target_id,
                    acres=acres,
                    requested_date=requested_date,
                    status=BookingStatus.PENDING,
                )
                db.put_booking(booking)

                contact = (
                    opt.get("metadata", {}).get("owner_phone")
                    or opt.get("metadata", {}).get("buyer_phone")
                    or opt.get("contact_phone")
                    or "Local CHC / Aggregator"
                )
                provider_name = opt.get("target_name") or opt.get("provider_name") or "Local CHC / Aggregator"

                confirmation_msg = (
                    f"🎉 *Booking Request Submitted!*\n\n"
                    f"• *Booking ID:* `{booking_id}`\n"
                    f"• *Provider:* {provider_name}\n"
                    f"• *Contact:* {contact}\n"
                    f"• *Target Date:* {requested_date}\n"
                    f"• *Status:* PENDING OPERATOR CONFIRMATION\n\n"
                    f"The operator has received your request and will contact you directly."
                )
                await client.answerCallbackQuery(cb_id, text="Booking confirmed!")
                await client.sendMessage(chat_id=chat_id, text=confirmation_msg)
                return
        except Exception as exc:
            logger.error("Error creating booking from callback: %s", exc)

    # Booking cancellation
    if data == "cancel_book":
        await client.answerCallbackQuery(cb_id, text="Booking cancelled")
        await client.sendMessage(
            chat_id=chat_id,
            text="❌ Booking was cancelled. You can pick another option or ask more questions.",
        )
        return

    await client.answerCallbackQuery(cb_id)


async def _handle_message(
    message: dict[str, Any],
    client: TelegramClient,
    db: DatabaseClient,
) -> None:
    chat_id = int(message.get("chat", {}).get("id", 0))
    if not chat_id:
        return

    session = db.get_session(chat_id)
    if session is None:
        session = FarmerSession(chat_id=chat_id)
        db.put_session(session)

    lang = session.language or "hi"
    text = (message.get("text") or "").strip()

    # 1. Voice Notes
    if message.get("voice") or message.get("audio"):
        voice_msg = VOICE_SOON_TEXTS.get(lang, VOICE_SOON_TEXTS["hi"])
        await client.sendMessage(chat_id=chat_id, text=voice_msg)
        return

    # 2. Location Messages (GPS pin)
    if "location" in message:
        loc = message["location"]
        lat = float(loc.get("latitude", 0.0))
        lon = float(loc.get("longitude", 0.0))

        session.lat = lat
        session.lon = lon
        session.last_seen_at = datetime.now(timezone.utc)
        db.put_session(session)

        await client.sendChatAction(chat_id=chat_id, action="typing")

        # Pass location context to conversational agent turn
        agent_input = f"I have shared my exact farm GPS coordinates: Latitude {lat:.6f}, Longitude {lon:.6f}."
        reply = await run_agent_turn(chat_id=chat_id, user_message=agent_input, db=db)

        # Remove location reply keyboard now that location is saved
        await client.sendMessage(
            chat_id=chat_id,
            text=reply,
            reply_markup=get_remove_keyboard(),
        )
        return

    # 3. Slash Commands
    if text.startswith("/"):
        cmd_parts = text.split(maxsplit=1)
        command = cmd_parts[0].lower()

        if command == "/start":
            await client.sendMessage(
                chat_id=chat_id,
                text=GREETING_TEXT,
                reply_markup=get_language_keyboard(),
            )
            return

        if command in ("/language", "/lang"):
            await client.sendMessage(
                chat_id=chat_id,
                text=GREETING_TEXT,
                reply_markup=get_language_keyboard(),
            )
            return

        if command == "/help":
            help_msg = HELP_TEXTS.get(lang, HELP_TEXTS["hi"])
            await client.sendMessage(chat_id=chat_id, text=help_msg)
            return

        if command == "/status":
            lang_names = {"en": "English", "hi": "हिन्दी (Hindi)", "pa": "ਪੰਜਾਬੀ (Punjabi)"}
            days_rem = f" (in {(session.sowing_deadline - datetime.now(timezone.utc).date()).days} days)" if session.sowing_deadline else ""
            status_lines = [
                "🌾 *Parali Mitra — Farmer Profile Status*",
                f"• *Language:* {lang_names.get(lang, lang)}",
                f"• *Farm Size:* {f'{session.acres} acres' if session.acres is not None else 'Not set'}",
                f"• *Location:* {session.village_text or (f'{session.lat:.4f}°N, {session.lon:.4f}°E' if session.lat else 'Not set')}",
                f"• *Sowing Deadline:* {f'{session.sowing_deadline}{days_rem}' if session.sowing_deadline else 'Not set'}",
                f"• *Evaluated Options:* {f'{len(session.last_options)} cached' if session.last_options else 'None'}",
                "",
                "💡 *Tip:* Send new farm details to update, or type `/options` to view recommendations.",
            ]
            await client.sendMessage(chat_id=chat_id, text="\n".join(status_lines))
            return

        if command == "/options":
            # If session has cached options, display them with keyboard
            if session.last_options:
                opt_msg = [
                    f"🌾 *Parali Mitra — Evaluated Options ({len(session.last_options)})*",
                    f"📊 *Farm:* {session.acres or 'N/A'} acres | 📍 _{session.village_text or 'Saved Pin'}_",
                    "",
                ]
                emojis = ["🥇", "🥈", "🥉"]
                for i, opt in enumerate(session.last_options[:3], start=1):
                    net = opt.get("net_cost", 0)
                    cost_str = f"💰 *Earns ₹{abs(int(net)):,}*" if net < 0 else f"💵 *Costs ₹{int(net):,}*"
                    name = opt.get("target_name") or opt.get("category") or f"Option {i}"
                    dist = opt.get("distance_km", 0.0)
                    opt_msg.append(f"{emojis[i - 1]} *Option {i}:* {name}\n  {cost_str} | 📍 {dist:.1f} km\n")
                opt_msg.append("👇 *Tap an option button below to book:*")
                await client.sendMessage(
                    chat_id=chat_id,
                    text="\n".join(opt_msg),
                    reply_markup=get_options_keyboard(session.last_options, lang=lang),
                )
                return

            # If complete details are present, run engine
            if session.acres and session.lat and session.lon and session.sowing_deadline:
                await client.sendChatAction(chat_id=chat_id, action="typing")
                reply = await run_agent_turn(chat_id=chat_id, user_message="Show my residue options", db=db)
                updated_session = db.get_session(chat_id)
                reply_markup = get_options_keyboard(updated_session.last_options, lang=lang) if (updated_session and updated_session.last_options) else None
                await client.sendMessage(chat_id=chat_id, text=reply, reply_markup=reply_markup)
                return

            # Otherwise prompt for missing fields
            from src.agent.agent import _format_missing_fields
            missing_msg = _format_missing_fields(session) or "Please share your farm acreage, village name, and sowing deadline."
            reply_markup = get_location_keyboard(lang=lang) if (session.lat is None or session.lon is None) else None
            await client.sendMessage(chat_id=chat_id, text=missing_msg, reply_markup=reply_markup)
            return

        if command == "/reset":
            clear_session_history(chat_id=chat_id, db=db)
            session.lat = None
            session.lon = None
            session.village_text = None
            session.acres = None
            session.sowing_deadline = None
            session.last_options = None
            session.last_seen_at = datetime.now(timezone.utc)
            db.put_session(session)

            reset_msg = RESET_TEXTS.get(lang, RESET_TEXTS["hi"])
            await client.sendMessage(
                chat_id=chat_id,
                text=reset_msg,
                reply_markup=get_language_keyboard(),
            )
            return

        if command == "/owner":
            owner_msg = OWNER_STUB_TEXTS.get(lang, OWNER_STUB_TEXTS["hi"])
            await client.sendMessage(chat_id=chat_id, text=owner_msg)
            return

    # 4. Regular Text Messages -> Agent Turn
    if text:
        await client.sendChatAction(chat_id=chat_id, action="typing")
        try:
            reply = await run_agent_turn(chat_id=chat_id, user_message=text, db=db)
        except Exception as exc:
            logger.error("Error during agent invocation for chat_id=%s: %s", chat_id, exc)
            fallback_msgs = {
                "en": "🌾 *Parali Mitra Advisor*\n\nYour message was received. Please share your farm location pin or village name, acreage, and sowing deadline to get residue recommendations.",
                "hi": "🌾 *पराली मित्र*\n\nआपका संदेश प्राप्त हुआ। कृपया पराली प्रबंधन विकल्पों के लिए अपना स्थान (GPS Pin या गाँव), एकड़ और बुवाई की तारीख साझा करें।",
                "pa": "🌾 *ਪਰਾਲੀ ਮਿੱਤਰ*\n\nਤੁਹਾਡਾ ਸੁਨੇਹਾ ਮਿਲ ਗਿਆ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਪਰਾਲੀ ਪ੍ਰਬੰਧਨ ਵਿਕਲਪਾਂ ਲਈ ਆਪਣਾ ਸਥਾਨ (GPS Pin ਜਾਂ ਪਿੰਡ), ਏਕੜ ਅਤੇ ਬਿਜਾਈ ਦੀ ਤਾਰੀਖ਼ ਦੱਸੋ।",
            }
            reply = fallback_msgs.get(lang, fallback_msgs["hi"])

        # Check if updated session has options cached from the turn
        updated_session = db.get_session(chat_id)
        reply_markup = None

        if updated_session and updated_session.last_options:
            reply_markup = get_options_keyboard(updated_session.last_options, lang=lang)
        elif updated_session and (updated_session.lat is None or updated_session.lon is None):
            # Prompt with location button if location not yet provided
            if any(k in reply.lower() for k in ("location", "village", "district", "स्थान", "ਪਿੰਡ", "ਸਥਾਨ")):
                reply_markup = get_location_keyboard(lang=lang)

        await client.sendMessage(
            chat_id=chat_id,
            text=reply,
            reply_markup=reply_markup,
        )

