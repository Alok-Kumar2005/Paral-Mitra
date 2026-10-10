"""Owner / CHC / Buyer portal interactive flow state machine."""

from __future__ import annotations

from datetime import date, datetime, timezone
import logging
import os
import secrets
from typing import Any

from src.bot.i18n import t
from src.bot.keyboards import (
    get_accept_decline_keyboard,
    get_machine_type_selection_keyboard,
    get_owner_menu_keyboard,
)
from src.bot.telegram_client import TelegramClient
from src.common.db import DatabaseClient
from src.common.models import (
    BookingStatus,
    ChatFlow,
    MachineType,
    Provider,
    ProviderStatus,
    ProviderType,
)
from src.connectors.geocode import Geocoder
from src.marketplace import services

logger = logging.getLogger(__name__)


async def handle_owner_command(
    text: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "hi",
) -> None:
    """Handle /owner or /owner <passcode>."""
    parts = text.strip().split(maxsplit=1)
    passcode = parts[1] if len(parts) > 1 else None

    flow = db.get_chat_flow(chat_id) or ChatFlow(
        chat_id=chat_id,
        flow="OWNER_PORTAL",
        step="PASSCODE",
        data={},
    )

    if passcode:
        is_valid, err = services.verify_owner_passcode(passcode, flow)
        db.put_chat_flow(flow)
        if not is_valid:
            if err and err.startswith("LOCKED_OUT"):
                mins = err.split(":")[1]
                await telegram_client.send_message(chat_id, t("owner_locked_out", lang, mins=mins))
            else:
                await telegram_client.send_message(chat_id, t("owner_invalid_passcode", lang))
            return

        # Authenticated!
        db.delete_chat_flow(chat_id)
        await show_owner_dashboard(chat_id, db, telegram_client, lang)
        return

    # No passcode supplied in command: check if already a registered provider
    provider = db.get_provider_by_chat_id(chat_id)
    if provider:
        await show_owner_dashboard(chat_id, db, telegram_client, lang)
        return

    # Request passcode
    flow.step = "PASSCODE"
    db.put_chat_flow(flow)
    await telegram_client.send_message(chat_id, t("owner_enter_passcode", lang))


async def handle_owner_text_input(
    text: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    flow: ChatFlow,
    lang: str = "hi",
) -> bool:
    """Process text inputs during multi-step owner registration / machine addition.
    
    Returns True if handled, False otherwise.
    """
    if flow.flow == "OWNER_PORTAL" and flow.step == "PASSCODE":
        is_valid, err = services.verify_owner_passcode(text, flow)
        db.put_chat_flow(flow)
        if not is_valid:
            if err and err.startswith("LOCKED_OUT"):
                mins = err.split(":")[1]
                await telegram_client.send_message(chat_id, t("owner_locked_out", lang, mins=mins))
            else:
                await telegram_client.send_message(chat_id, t("owner_invalid_passcode", lang))
            return True

        db.delete_chat_flow(chat_id)
        await show_owner_dashboard(chat_id, db, telegram_client, lang)
        return True

    elif flow.flow == "OWNER_REGISTER":
        if flow.step == "NAME":
            flow.data["name"] = text.strip()
            flow.step = "PHONE"
            db.put_chat_flow(flow)
            await telegram_client.send_message(chat_id, "📞 Please enter your 10-digit contact phone number:")
            return True

        elif flow.step == "PHONE":
            clean_phone = "".join(filter(str.isdigit, text))
            if len(clean_phone) < 10:
                await telegram_client.send_message(chat_id, "⚠️ Invalid phone number. Please enter a valid 10-digit number:")
                return True
            flow.data["phone"] = clean_phone[-10:]
            flow.step = "LOCATION"
            db.put_chat_flow(flow)
            await telegram_client.send_message(chat_id, "📍 Enter your base Village and District (e.g. Nabha, Patiala) or share a GPS location pin:")
            return True

        elif flow.step == "LOCATION":
            loc_text = text.strip()
            # Geocode
            lat, lon, district, state = 30.3753, 76.1517, "Patiala", "Punjab"
            try:
                gc = await Geocoder().geocode(loc_text)
                if gc:
                    lat, lon = gc.lat, gc.lon
                    district = gc.district or district
                    state = gc.state or state
            except Exception:
                pass

            p_id = f"PRV_{secrets.token_hex(3).upper()}"
            p_type = flow.data.get("type", "CHC")
            provider, notifs = services.register_provider(
                db=db,
                provider_id=p_id,
                provider_type=p_type,
                name=flow.data.get("name", "CHC Operator"),
                contact_phone=flow.data.get("phone", "9876543210"),
                district=district,
                state=state,
                lat=lat,
                lon=lon,
                telegram_chat_id=chat_id,
            )
            db.delete_chat_flow(chat_id)

            await telegram_client.send_message(
                chat_id=chat_id,
                text=(
                    f"✅ *Registration Submitted!*\n\n"
                    f"Provider ID: `{provider.provider_id}`\n"
                    f"Name: *{provider.name}*\n"
                    f"District: *{provider.district}, {provider.state}*\n"
                    f"Status: ⏳ *PENDING VERIFICATION*\n\n"
                    f"An administrator will verify your profile shortly."
                ),
            )
            for n in notifs:
                await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)
            return True

    elif flow.flow == "ADD_MACHINE":
        if flow.step == "RATE":
            try:
                rate = float(text.replace("₹", "").replace(",", "").strip())
                flow.data["rate_per_acre"] = rate
                flow.step = "RADIUS"
                db.put_chat_flow(flow)
                await telegram_client.send_message(chat_id, "📏 Enter maximum service operational radius in km (e.g. 25):")
                return True
            except ValueError:
                await telegram_client.send_message(chat_id, "⚠️ Please enter a valid numerical rate (e.g. 1500):")
                return True

        elif flow.step == "RADIUS":
            try:
                radius = float(text.replace("km", "").strip())
                provider = db.get_provider_by_chat_id(chat_id)
                if not provider:
                    await telegram_client.send_message(chat_id, "⚠️ Provider profile not found. Please register first.")
                    db.delete_chat_flow(chat_id)
                    return True

                m_id = f"MCH_{secrets.token_hex(3).upper()}"
                mch, notifs = services.add_machine(
                    db=db,
                    machine_id=m_id,
                    provider_id=provider.provider_id,
                    machine_type=flow.data.get("machine_type", "SUPER_SEEDER"),
                    village=provider.district,
                    district=provider.district,
                    lat=provider.lat,
                    lon=provider.lon,
                    rate_per_acre=flow.data.get("rate_per_acre", 1500.0),
                    travel_charge_per_km=0.0,
                    service_radius_km=radius,
                )
                db.delete_chat_flow(chat_id)
                await telegram_client.send_message(
                    chat_id=chat_id,
                    text=(
                        f"✅ *Machine Added Successfully!*\n\n"
                        f"Machine ID: `{mch.machine_id}`\n"
                        f"Type: *{mch.machine_type}*\n"
                        f"Rate: *₹{mch.rate_per_acre:,.0f}/acre*\n"
                        f"Service Radius: *{mch.service_radius_km} km*\n"
                        f"Status: *{mch.status}*"
                    ),
                    reply_markup=get_owner_menu_keyboard(is_registered=True),
                )
                return True
            except ValueError:
                await telegram_client.send_message(chat_id, "⚠️ Please enter a valid number for radius in km (e.g. 25):")
                return True

    return False


async def handle_owner_callback(
    data: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "hi",
) -> None:
    """Handle owner menu inline button callbacks."""
    if data.startswith("own_reg:"):
        ptype = data.split(":", 1)[1]
        flow = ChatFlow(
            chat_id=chat_id,
            flow="OWNER_REGISTER",
            step="NAME",
            data={"type": ptype},
        )
        db.put_chat_flow(flow)
        await telegram_client.send_message(chat_id, f"📝 *Register as {ptype}*\n\nPlease enter your Business / CHC Operator Name:")

    elif data == "own_add_mch":
        provider = db.get_provider_by_chat_id(chat_id)
        if not provider:
            await telegram_client.send_message(chat_id, "⚠️ Please register as a provider first.")
            return
        flow = ChatFlow(
            chat_id=chat_id,
            flow="ADD_MACHINE",
            step="TYPE",
            data={},
        )
        db.put_chat_flow(flow)
        await telegram_client.send_message(
            chat_id,
            "🚜 *Add Machinery*\n\nSelect the type of equipment:",
            reply_markup=get_machine_type_selection_keyboard(),
        )

    elif data.startswith("mch_type:"):
        mtype = data.split(":", 1)[1]
        flow = db.get_chat_flow(chat_id)
        if flow and flow.flow == "ADD_MACHINE":
            flow.data["machine_type"] = mtype
            flow.step = "RATE"
            db.put_chat_flow(flow)
            await telegram_client.send_message(chat_id, f"💰 Enter rental rate per acre in INR for *{mtype}* (e.g. 1500):")

    elif data == "own_list_mch":
        await show_owner_machines(chat_id, db, telegram_client)

    elif data == "own_list_bkg":
        await show_owner_incoming_bookings(chat_id, db, telegram_client)


async def show_owner_dashboard(
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "hi",
) -> None:
    """Render operator dashboard."""
    provider = db.get_provider_by_chat_id(chat_id)
    is_reg = provider is not None
    status_msg = ""
    if provider:
        status_msg = f"\nProvider: *{provider.name}* (`{provider.provider_id}`)\nStatus: *{provider.status.value}*\nDistrict: *{provider.district}*\n"

    msg = f"👨‍🌾 *Parali Mitra CHC / Operator Portal*\n{status_msg}\nSelect an option below:"
    await telegram_client.send_message(
        chat_id=chat_id,
        text=msg,
        reply_markup=get_owner_menu_keyboard(is_registered=is_reg),
    )


async def show_owner_machines(
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Display registered machines for this provider."""
    provider = db.get_provider_by_chat_id(chat_id)
    if not provider:
        await telegram_client.send_message(chat_id, "⚠️ No provider profile found.")
        return

    machines = db.list_machines_by_provider(provider.provider_id)
    if not machines:
        await telegram_client.send_message(
            chat_id,
            "🚜 You haven't added any machinery yet. Tap *Add New Machine* to get started.",
            reply_markup=get_owner_menu_keyboard(is_registered=True),
        )
        return

    lines = [f"🚜 *Your Registered Machinery ({len(machines)}):*\n"]
    for m in machines:
        rating_str = f"⭐ {m.rating_avg:.1f} ({m.rating_count})" if m.rating_avg else "No ratings"
        lines.append(
            f"• *{m.machine_type}* [`{m.machine_id}`]\n"
            f"  Rate: ₹{m.rate_per_acre:,.0f}/acre | Radius: {m.service_radius_km} km\n"
            f"  Status: *{m.status}* | Rating: {rating_str}\n"
        )

    await telegram_client.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=get_owner_menu_keyboard(is_registered=True),
    )


async def show_owner_incoming_bookings(
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
) -> None:
    """Display incoming job requests for this provider."""
    provider = db.get_provider_by_chat_id(chat_id)
    if not provider:
        await telegram_client.send_message(chat_id, "⚠️ No provider profile found.")
        return

    bookings = db.list_bookings_by_provider(provider.provider_id)
    if not bookings:
        await telegram_client.send_message(
            chat_id,
            "📥 No job requests received yet.",
            reply_markup=get_owner_menu_keyboard(is_registered=True),
        )
        return

    pending = [b for b in bookings if b.status == BookingStatus.PENDING]
    others = [b for b in bookings if b.status != BookingStatus.PENDING][:5]

    for b in pending:
        msg = (
            f"🚜 *Pending Job Request!* [`{b.booking_id}`]\n"
            f"Target: *{b.target_id}*\n"
            f"Area: *{b.acres:.1f} acres*\n"
            f"Date: *{b.requested_date.isoformat()}*\n"
        )
        await telegram_client.send_message(
            chat_id=chat_id,
            text=msg,
            reply_markup=get_accept_decline_keyboard(b.booking_id),
        )

    if others:
        lines = ["📋 *Recent Completed / Confirmed Jobs:*\n"]
        for b in others:
            lines.append(f"• `{b.booking_id}`: *{b.status.value}* on {b.requested_date.isoformat()} ({b.acres:.1f} ac)")
        await telegram_client.send_message(chat_id, "\n".join(lines))
