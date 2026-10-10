"""Booking lifecycle callback and confirmation handlers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any

from src.bot.keyboards import get_booking_confirm_keyboard
from src.bot.telegram_client import TelegramClient
from src.common.db import DatabaseClient
from src.common.models import OptionType
from src.marketplace import services

logger = logging.getLogger(__name__)


async def handle_booking_callback(
    data: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "hi",
) -> None:
    """Route callback queries related to booking lifecycle."""
    if data.startswith("book_opt:"):
        await _handle_book_opt(data, chat_id, db, telegram_client, lang)
    elif data == "cancel_book":
        await telegram_client.send_message(
            chat_id=chat_id,
            text="❌ Booking request cancelled. Type /options to check other residue solutions.",
        )
    elif data.startswith("confirm_book:"):
        await _handle_confirm_book(data, chat_id, db, telegram_client, lang)
    elif data.startswith("bk_acc:"):
        booking_id = data.split(":", 1)[1].strip()
        _, notifs = services.owner_decide(db, booking_id, operator_chat_id=chat_id, accept=True)
        for n in notifs:
            await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)
    elif data.startswith("bk_dec:"):
        booking_id = data.split(":", 1)[1].strip()
        _, notifs = services.owner_decide(db, booking_id, operator_chat_id=chat_id, accept=False)
        for n in notifs:
            await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)
    elif data.startswith("bk_rate:"):
        parts = data.split(":")
        if len(parts) == 3:
            booking_id = parts[1]
            stars = int(parts[2])
            _, notifs = services.rate_provider(db, booking_id, farmer_chat_id=chat_id, rating=stars)
            for n in notifs:
                await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)


async def _handle_book_opt(
    data: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str,
) -> None:
    opt_idx_str = data.split(":", 1)[1]
    if not opt_idx_str.isdigit():
        return
    idx = int(opt_idx_str)

    session = db.get_session(chat_id)
    if not session or not session.last_options or idx >= len(session.last_options):
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⚠️ Options have expired. Please type /options to recalculate current rates.",
        )
        return

    opt = session.last_options[idx]
    target_name = (
        opt.get("target_name")
        or opt.get("display_name")
        or opt.get("machine_type")
        or opt.get("buyer_type")
        or f"Option #{idx + 1}"
    )
    net_cost = opt.get("net_cost", 0)
    cost_label = f"+₹{abs(int(net_cost)):,} (Profit)" if net_cost < 0 else f"-₹{abs(int(net_cost)):,}"
    acres = opt.get("acres") or session.acres or 10.0

    msg = (
        f"📝 *Confirm Booking Request*\n\n"
        f"Option #{idx + 1}: *{target_name}*\n"
        f"Farm Size: *{acres:.1f} acres*\n"
        f"Estimated Net: *{cost_label}*\n\n"
        f"Are you sure you want to send this booking request to the operator?"
    )
    await telegram_client.send_message(
        chat_id=chat_id,
        text=msg,
        reply_markup=get_booking_confirm_keyboard(idx, lang=lang),
    )


async def _handle_confirm_book(
    data: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str,
) -> None:
    opt_idx_str = data.split(":", 1)[1]
    if not opt_idx_str.isdigit():
        return
    idx = int(opt_idx_str)

    session = db.get_session(chat_id)
    if not session or not session.last_options or idx >= len(session.last_options):
        await telegram_client.send_message(
            chat_id=chat_id,
            text="⚠️ Option session expired. Please type /options to find available machinery.",
        )
        return

    opt = session.last_options[idx]
    target_id = opt.get("target_id") or opt.get("machine_id") or opt.get("buyer_id") or f"TGT_{idx}"
    acres = float(opt.get("acres") or session.acres or 10.0)
    opt_type_raw = opt.get("option_type") or "IN_SITU"
    opt_type = OptionType.IN_SITU if "IN_SITU" in str(opt_type_raw).upper() else OptionType.EX_SITU
    req_date_str = opt.get("recommended_start_date") or opt.get("start_date")
    if req_date_str:
        try:
            req_date = date.fromisoformat(str(req_date_str))
        except Exception:
            req_date = date.today() + timedelta(days=1)
    else:
        req_date = date.today() + timedelta(days=1)

    try:
        booking, notifs = services.create_booking(
            db=db,
            farmer_chat_id=chat_id,
            target_id=target_id,
            acres=acres,
            requested_date=req_date,
            option_type=opt_type,
        )
        await telegram_client.send_message(
            chat_id=chat_id,
            text=(
                f"✅ *Booking Request Submitted!* [ID: `{booking.booking_id}`]\n\n"
                f"Target: *{opt.get('target_name', target_id)}*\n"
                f"Area: *{acres:.1f} acres* | Date: *{req_date.isoformat()}*\n\n"
                "The operator has been notified and will confirm within 48 hours."
            ),
        )
        for n in notifs[1:]:  # skip farmer notif (already sent above), send operator notif
            await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)
    except ValueError:
        # Target not in marketplace DB (legacy seed data): create PENDING_MANUAL booking directly
        import secrets as _secrets
        from src.common.models import Booking, BookingStatus
        now = datetime.now(timezone.utc)
        bid = f"BK-{_secrets.token_hex(4).upper()}"
        booking = Booking(
            booking_id=bid,
            farmer_chat_id=chat_id,
            option_type=opt_type,
            target_id=target_id,
            acres=acres,
            requested_date=req_date,
            status=BookingStatus.PENDING_MANUAL,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=48),
        )
        db.put_booking(booking)
        contact = opt.get("contact_phone") or opt.get("provider_phone") or ""
        contact_line = f"\nOperator Contact: *{contact}*" if contact else ""
        await telegram_client.send_message(
            chat_id=chat_id,
            text=(
                f"✅ *Booking Request Submitted!* [ID: `{bid}`]\n\n"
                f"Target: *{opt.get('target_name', target_id)}*\n"
                f"Area: *{acres:.1f} acres* | Date: *{req_date.isoformat()}*{contact_line}\n\n"
                "Please contact the operator directly using the number above to confirm the visit."
            ),
        )
    except Exception as e:
        logger.error("[BookingFlow] Error creating booking: %s", e)
        await telegram_client.send_message(
            chat_id=chat_id,
            text=f"⚠️ Could not create booking: {e}",
        )
