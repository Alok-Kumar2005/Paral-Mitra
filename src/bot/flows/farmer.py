"""Farmer conversational flows, standard bot commands, and agent execution."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any

from src.agent.agent import run_agent_turn
from src.agent.memory import clear_session_history
from src.agent.tools import get_agricultural_constants
from src.bot.i18n import STRINGS, t
from src.bot.keyboards import (
    get_language_keyboard,
    get_location_keyboard,
    get_options_keyboard,
    get_remove_keyboard,
)
from src.bot.telegram_client import TelegramClient
from src.common.db import DatabaseClient
from src.common.models import FarmerSession, OptionType
from src.engine.recommender import rank_options
from src.marketplace import services

logger = logging.getLogger(__name__)

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


async def handle_start(
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Handle /start greeting and language picker."""
    session = db.get_session(chat_id)
    if not session:
        session = FarmerSession(chat_id=chat_id, language="hi")
        db.put_session(session)

    await telegram_client.send_message(
        chat_id=chat_id,
        text=GREETING_TEXT,
        reply_markup=get_language_keyboard(),
    )


async def handle_help(
    chat_id: int,
    session: FarmerSession,
    telegram_client: TelegramClient,
) -> None:
    """Handle /help."""
    lang = session.language or "hi"
    await telegram_client.send_message(chat_id=chat_id, text=t("help", lang))


async def handle_language_command(
    chat_id: int,
    telegram_client: TelegramClient,
) -> None:
    """Handle /language."""
    await telegram_client.send_message(
        chat_id=chat_id,
        text="🌐 Choose your preferred language / अपनी भाषा चुनें / ਆਪਣੀ ਭਾਸ਼ਾ ਚੁਣੋ:",
        reply_markup=get_language_keyboard(),
    )


async def handle_language_callback(
    data: str,
    chat_id: int,
    session: FarmerSession,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Handle lang:en / lang:hi / lang:pa callback."""
    lang = data.split(":", 1)[1] if ":" in data else "hi"
    if lang not in ("en", "hi", "pa"):
        lang = "hi"

    session.language = lang
    session.last_seen_at = datetime.now(timezone.utc)
    db.put_session(session)

    ack_text = LANGUAGE_ACK_TEXTS.get(lang, LANGUAGE_ACK_TEXTS["hi"])
    await telegram_client.send_message(
        chat_id=chat_id,
        text=ack_text,
        reply_markup=get_location_keyboard(lang=lang),
    )


async def handle_status(
    chat_id: int,
    session: FarmerSession,
    telegram_client: TelegramClient,
) -> None:
    """Handle /status profile overview."""
    lang = session.language or "hi"
    loc_str = session.village_text or (f"{session.lat:.4f}, {session.lon:.4f}" if session.lat else "Not set")
    acres_str = f"{session.acres:.1f} acres" if session.acres else "Not set"
    crop_str = session.crop or "Paddy (धान / ਝੋਨਾ)"
    deadline_str = session.sowing_deadline.isoformat() if session.sowing_deadline else "Not set"

    msg = (
        f"📊 *Profile Status — Your Farm Profile:*\n\n"
        f"• *Language:* `{lang}`\n"
        f"• *Location:* {loc_str}\n"
        f"• *District:* {session.district or 'Not set'}, {session.state or ''}\n"
        f"• *Acreage:* {acres_str}\n"
        f"• *Crop:* {crop_str}\n"
        f"• *Wheat Sowing Deadline:* {deadline_str}\n\n"
        f"💡 Type `/options` to calculate residue solutions, or `/machines` to explore nearby equipment."
    )
    await telegram_client.send_message(chat_id=chat_id, text=msg)


async def handle_reset(
    chat_id: int,
    session: FarmerSession,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Handle /reset conversation memory and cached options."""
    clear_session_history(chat_id)
    session.acres = None
    session.lat = None
    session.lon = None
    session.village_text = None
    session.district = None
    session.state = None
    session.last_options = None
    session.sowing_deadline = None
    session.updated_at = datetime.now(timezone.utc)
    db.put_session(session)

    lang = session.language or "hi"
    ack = {
        "en": "🔄 Conversation history and profile have been reset. How can I help you today?",
        "hi": "🔄 बातचीत का इतिहास और प्रोफ़ाइल रीसेट (reset) कर दी गई है। मैं आज आपकी क्या सहायता करूँ?",
        "pa": "🔄 ਗੱਲਬਾਤ ਦਾ ਇਤਿਹਾਸ ਅਤੇ ਪ੍ਰੋਫਾਈਲ ਰੀਸੈੱਟ ਕਰ ਦਿੱਤਾ ਗਿਆ ਹੈ। ਮੈਂ ਅੱਜ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?",
    }.get(lang, "🔄 रीसेट पूर्ण हुआ।")

    await telegram_client.send_message(
        chat_id=chat_id,
        text=ack,
        reply_markup=get_location_keyboard(lang=lang),
    )


async def handle_forget_me(
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "hi",
) -> None:
    """Handle /forget_me (GDPR / privacy deletion)."""
    db.forget_farmer(chat_id)
    await telegram_client.send_message(
        chat_id=chat_id,
        text=t("data_forgotten", lang),
        reply_markup=get_remove_keyboard(),
    )


async def handle_machines_command(
    chat_id: int,
    session: FarmerSession,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Handle /machines exploration command."""
    lang = session.language or "hi"
    lat = session.lat or 30.3753
    lon = session.lon or 76.1517

    views = services.list_nearby_machines(db, lat=lat, lon=lon, radius_km=50.0)
    if not views:
        await telegram_client.send_message(chat_id, t("no_nearby_machines", lang, radius_km=50))
        return

    lines = [f"{t('nearby_machines_header', lang, radius_km=50)}\n"]
    for idx, v in enumerate(views[:10]):
        rating_str = f"⭐ {v.rating_avg:.1f} ({v.rating_count})" if v.rating_avg else "New"
        dist_str = f" • {v.distance_km} km away" if v.distance_km is not None else ""
        lines.append(
            f"*{idx + 1}. {v.machine_type}* [`{v.machine_id}`]\n"
            f"   CHC: *{v.provider_name}* ({v.village}, {v.district}{dist_str})\n"
            f"   Rate: *₹{v.rate_per_acre:,.0f}/acre* | Rating: {rating_str}\n"
        )
    lines.append("💡 Type `/options` for custom cost-optimization based on your acreage.")
    await telegram_client.send_message(chat_id, "\n".join(lines))


async def handle_mybookings_command(
    chat_id: int,
    session: FarmerSession,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Handle /mybookings status command."""
    lang = session.language or "hi"
    bookings = db.list_bookings_by_farmer(chat_id)
    if not bookings:
        await telegram_client.send_message(chat_id, t("no_bookings", lang))
        return

    lines = [f"{t('mybookings_header', lang)}\n"]
    for b in bookings:
        status_emoji = {
            "PENDING": "⏳",
            "PENDING_MANUAL": "⏳",
            "CONFIRMED": "✅",
            "COMPLETED": "🎉",
            "REJECTED": "❌",
            "EXPIRED": "⏰",
        }.get(b.status.value, "📋")
        rating_str = f" | Rating: {b.rating} ⭐" if b.rating else ""
        lines.append(
            f"{status_emoji} *ID:* `{b.booking_id}`\n"
            f"   Target: *{b.target_id}* ({b.option_type})\n"
            f"   Status: *{b.status.value}*\n"
            f"   Date: *{b.requested_date.isoformat()}* | Area: {b.acres:.1f} ac{rating_str}\n"
        )
    await telegram_client.send_message(chat_id, "\n".join(lines))


async def handle_options_command(
    chat_id: int,
    session: FarmerSession,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Handle /options recommendation ranking."""
    lang = session.language or "hi"

    # Fast path: show cached last_options if the session already has ranked results
    if session.last_options:
        ranked_options = session.last_options
        acres = session.acres or 0.0
        lines = [f"🌾 *Recommended Residue Solutions{f' for {acres:.1f} Acres' if acres else ''}:*\n"]
        for idx, opt in enumerate(ranked_options[:5]):
            name = opt.get("target_name") or opt.get("machine_type") or f"Option {idx + 1}"
            net = opt.get("net_cost", 0)
            cost_str = f"+₹{abs(int(net)):,} (Profit)" if net < 0 else f"-₹{abs(int(net)):,}"
            dist = opt.get("distance_km")
            dist_str = f" | {dist:.1f} km" if dist is not None else ""
            lines.append(f"*{idx + 1}. {name}*\n   Net: *{cost_str}*{dist_str}\n")
        lines.append("Tap an option below to confirm a booking:")
        await telegram_client.send_message(
            chat_id=chat_id,
            text="\n".join(lines),
            reply_markup=get_options_keyboard(ranked_options[:5], lang=lang),
        )
        return

    # Full ranking path: requires lat, lon, sowing_deadline
    lat = session.lat or 30.3753
    lon = session.lon or 76.1517
    acres = session.acres or 10.0
    deadline = session.sowing_deadline or (date.today() + timedelta(days=20))

    machines = db.list_bookable_machines(lat=lat, lon=lon, radius_km=50.0)
    buyers = db.list_bookable_buyers(lat=lat, lon=lon, radius_km=50.0)
    constants = get_agricultural_constants()

    try:
        ranking = rank_options(
            farmer=session,
            machines=machines,
            buyers=buyers,
            constants=constants,
            weather=None,
            today=date.today(),
        )
    except ValueError:
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⚠️ Please share your farm location and acreage before viewing options.\nType your village and district or share a GPS pin.",
        )
        return

    ranked_options = [opt.model_dump(mode="json") for opt in ranking.feasible]
    if not ranked_options:
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⚠️ No feasible residue management options found within operational distance.",
        )
        return

    session.last_options = ranked_options
    session.updated_at = datetime.now(timezone.utc)
    db.put_session(session)

    lines = [f"🌾 *Top Recommended Residue Solutions for {acres:.1f} Acres:*\n"]
    for idx, opt in enumerate(ranked_options[:5]):
        name = opt.get("target_name") or opt.get("machine_type") or opt.get("buyer_type") or f"Option {idx + 1}"
        net = opt.get("net_cost", 0)
        cost_str = f"+₹{abs(int(net)):,} (Profit)" if net < 0 else f"-₹{abs(int(net)):,}"
        slack = opt.get("slack_days", 0)
        lines.append(f"*{idx + 1}. {name}*\n   Net: *{cost_str}* | Slack: {slack} days | Score: {opt.get('score', 0):.2f}\n")

    lines.append("Tap an option below to book:")
    await telegram_client.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=get_options_keyboard(ranked_options[:5], lang=lang),
    )


async def handle_location_message(
    chat_id: int,
    lat: float,
    lon: float,
    session: FarmerSession,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Handle incoming GPS location attachment."""
    session.lat = lat
    session.lon = lon
    session.last_seen_at = datetime.now(timezone.utc)
    db.put_session(session)

    lang = session.language or "hi"
    loc_display = session.village_text or session.district or f"{lat:.4f}, {lon:.4f}"

    await telegram_client.send_message(
        chat_id=chat_id,
        text=t("location_saved", lang, location=loc_display),
        reply_markup=get_remove_keyboard(),
    )


async def handle_agent_text_turn(
    chat_id: int,
    text: str,
    session: FarmerSession,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Pass farmer text message to LLM Strands Agent."""
    lang = session.language or "hi"
    try:
        # Show typing status
        await telegram_client.send_chat_action(chat_id, "typing")

        response_text = await run_agent_turn(
            chat_id=chat_id,
            user_text=text,
            session=session,
            db=db,
        )

        # If options are cached in session, attach options keyboard
        reply_markup = None
        if session.last_options:
            reply_markup = get_options_keyboard(session.last_options[:5], lang=lang)

        await telegram_client.send_message(
            chat_id=chat_id,
            text=response_text,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error("[FarmerFlow] Agent turn error for chat %s: %s", chat_id, e)
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⚠️ Service is busy. Please type /options or /machines to proceed.",
        )
