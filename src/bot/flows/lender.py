"""Lender (Individual Machine Owner) interactive registration flow state machine."""

from __future__ import annotations

import logging
import os
import re
import secrets
from typing import Any

from src.bot.flows import owner
from src.bot.i18n import t
from src.bot.keyboards import (
    get_contact_keyboard,
    get_machine_type_selection_keyboard,
    get_remove_keyboard,
)
from src.bot.telegram_client import TelegramClient
from src.common.constants import get_constants
from src.common.db import DatabaseClient
from src.common.models import ChatFlow
from src.connectors.geocode import Geocoder
from src.marketplace import services

logger = logging.getLogger(__name__)

INDIA_LAT_MIN = 6.0
INDIA_LAT_MAX = 38.0
INDIA_LON_MIN = 68.0
INDIA_LON_MAX = 98.0


def _is_within_india(lat: float, lon: float) -> bool:
    return INDIA_LAT_MIN <= lat <= INDIA_LAT_MAX and INDIA_LON_MIN <= lon <= INDIA_LON_MAX


def _parse_coordinates(text: str) -> tuple[float, float] | None:
    cleaned = text.replace(";", ",").strip()
    parts = [p.strip() for p in cleaned.split(",")]
    if len(parts) == 2:
        try:
            lat = float(parts[0])
            lon = float(parts[1])
            return lat, lon
        except ValueError:
            return None
    return None


async def handle_lend_command(
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "hi",
) -> None:
    """Handle /lend command.

    If user is already a registered provider, shows existing owner dashboard.
    Otherwise initiates the LEND registration wizard.
    """
    existing_provider = db.get_provider_by_chat_id(chat_id)
    if existing_provider:
        await owner.show_owner_dashboard(chat_id, db, telegram_client, lang)
        return

    flow = ChatFlow(
        chat_id=chat_id,
        flow="LEND",
        step="CONTACT",
        data={},
    )
    db.put_chat_flow(flow)

    await telegram_client.send_message(chat_id, t("lend_disclaimer", lang))
    await telegram_client.send_message(
        chat_id,
        t("lend_ask_contact", lang),
        reply_markup=get_contact_keyboard(lang),
    )


async def handle_lender_contact_input(
    msg: dict[str, Any],
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    flow: ChatFlow,
    lang: str = "hi",
) -> bool:
    """Handle contact attachment during LEND CONTACT step."""
    if flow.flow != "LEND" or flow.step != "CONTACT":
        return False

    contact = msg.get("contact", {})
    contact_user_id = contact.get("user_id")

    # Reject contact if not from the same user
    if contact_user_id != chat_id:
        await telegram_client.send_message(
            chat_id,
            t("lend_contact_wrong_user", lang),
            reply_markup=get_contact_keyboard(lang),
        )
        return True

    raw_phone = str(contact.get("phone_number", ""))
    clean_phone = "".join(filter(str.isdigit, raw_phone))
    if len(clean_phone) >= 10:
        phone_10 = clean_phone[-10:]
    else:
        phone_10 = clean_phone

    flow.data["phone"] = phone_10
    flow.data["phone_verified"] = True
    flow.step = "NAME"
    db.put_chat_flow(flow)

    await telegram_client.send_message(
        chat_id,
        t("lend_ask_name", lang),
        reply_markup=get_remove_keyboard(),
    )
    return True


async def handle_lender_location_input(
    msg: dict[str, Any],
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    flow: ChatFlow,
    lang: str = "hi",
) -> bool:
    """Handle GPS pin attachment during LEND LOCATION step."""
    if flow.flow != "LEND" or flow.step != "LOCATION":
        return False

    loc = msg.get("location", {})
    lat = float(loc.get("latitude", 0.0))
    lon = float(loc.get("longitude", 0.0))

    if not _is_within_india(lat, lon):
        await telegram_client.send_message(chat_id, t("lend_location_outside_india", lang))
        return True

    district = None
    state = None
    try:
        gc = await Geocoder().geocode(f"{lat:.4f}, {lon:.4f}")
        if gc:
            district = gc.district
            state = gc.state
    except Exception:
        pass

    flow.data["lat"] = lat
    flow.data["lon"] = lon

    if not district or not state:
        flow.step = "DISTRICT_STATE"
        db.put_chat_flow(flow)
        await telegram_client.send_message(chat_id, t("lend_ask_district_state", lang))
        return True

    flow.data["district"] = district
    flow.data["state"] = state
    flow.step = "MACHINE_TYPE"
    db.put_chat_flow(flow)

    await telegram_client.send_message(
        chat_id,
        t("lend_ask_machine_type", lang),
        reply_markup=get_machine_type_selection_keyboard(),
    )
    return True


async def handle_lender_text_input(
    text: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    flow: ChatFlow,
    lang: str = "hi",
) -> bool:
    """Handle text input at each step of the LEND wizard. Returns True if handled."""
    if flow.flow != "LEND":
        return False

    stripped = text.strip()

    # /cancel is permitted at any step
    if stripped.lower() == "/cancel":
        db.delete_chat_flow(chat_id)
        await telegram_client.send_message(
            chat_id,
            t("lend_cancelled", lang),
            reply_markup=get_remove_keyboard(),
        )
        return True

    step = flow.step

    if step == "CONTACT":
        clean_phone = "".join(filter(str.isdigit, stripped))
        if len(clean_phone) < 10:
            await telegram_client.send_message(chat_id, t("lend_invalid_phone", lang))
            return True

        phone_10 = clean_phone[-10:]
        flow.data["phone"] = phone_10
        flow.data["phone_verified"] = False
        flow.step = "NAME"
        db.put_chat_flow(flow)

        await telegram_client.send_message(
            chat_id,
            t("lend_ask_name", lang),
            reply_markup=get_remove_keyboard(),
        )
        return True

    elif step == "NAME":
        if len(stripped) < 2 or len(stripped) > 60:
            await telegram_client.send_message(chat_id, t("lend_invalid_name", lang))
            return True

        flow.data["name"] = stripped
        flow.step = "LOCATION"
        db.put_chat_flow(flow)

        await telegram_client.send_message(chat_id, t("lend_ask_location", lang))
        return True

    elif step == "LOCATION":
        coords = _parse_coordinates(stripped)
        district = None
        state = None

        if coords:
            lat, lon = coords
            if not _is_within_india(lat, lon):
                await telegram_client.send_message(chat_id, t("lend_location_outside_india", lang))
                return True
            try:
                gc = await Geocoder().geocode(f"{lat:.4f}, {lon:.4f}")
                if gc:
                    district = gc.district
                    state = gc.state
            except Exception:
                pass
        else:
            gc = None
            try:
                gc = await Geocoder().geocode(stripped)
            except Exception:
                pass

            if not gc or gc.lat is None or gc.lon is None:
                await telegram_client.send_message(chat_id, t("lend_location_failed", lang))
                return True

            lat, lon = gc.lat, gc.lon
            if not _is_within_india(lat, lon):
                await telegram_client.send_message(chat_id, t("lend_location_outside_india", lang))
                return True

            district = gc.district
            state = gc.state

        flow.data["lat"] = lat
        flow.data["lon"] = lon

        if not district or not state:
            flow.step = "DISTRICT_STATE"
            db.put_chat_flow(flow)
            await telegram_client.send_message(chat_id, t("lend_ask_district_state", lang))
            return True

        flow.data["district"] = district
        flow.data["state"] = state
        flow.step = "MACHINE_TYPE"
        db.put_chat_flow(flow)

        await telegram_client.send_message(
            chat_id,
            t("lend_ask_machine_type", lang),
            reply_markup=get_machine_type_selection_keyboard(),
        )
        return True

    elif step == "DISTRICT_STATE":
        parts = [p.strip() for p in stripped.split(",") if p.strip()]
        if not parts:
            await telegram_client.send_message(chat_id, t("lend_ask_district_state", lang))
            return True

        district = parts[0]
        state = parts[1] if len(parts) > 1 else "Punjab"
        flow.data["district"] = district
        flow.data["state"] = state
        flow.step = "MACHINE_TYPE"
        db.put_chat_flow(flow)

        await telegram_client.send_message(
            chat_id,
            t("lend_ask_machine_type", lang),
            reply_markup=get_machine_type_selection_keyboard(),
        )
        return True

    elif step == "RATE":
        try:
            rate = float(stripped.replace("₹", "").replace(",", "").strip())
        except ValueError:
            constants = get_constants()
            lo = int(constants.lender_min_rate_per_acre or 500)
            hi = int(constants.lender_max_rate_per_acre or 4000)
            await telegram_client.send_message(chat_id, t("lend_invalid_rate", lang, lo=lo, hi=hi))
            return True

        constants = get_constants()
        lo = constants.lender_min_rate_per_acre or 500.0
        hi = constants.lender_max_rate_per_acre or 4000.0

        if rate < lo or rate > hi:
            await telegram_client.send_message(
                chat_id,
                t("lend_invalid_rate", lang, lo=int(lo), hi=int(hi)),
            )
            return True

        flow.data["rate_per_acre"] = rate
        flow.step = "TRAVEL"
        db.put_chat_flow(flow)

        await telegram_client.send_message(chat_id, t("lend_ask_travel", lang))
        return True

    elif step == "TRAVEL":
        try:
            travel = float(stripped.replace("₹", "").strip())
        except ValueError:
            await telegram_client.send_message(chat_id, t("lend_invalid_travel", lang))
            return True

        if travel < 0 or travel > 1000:
            await telegram_client.send_message(chat_id, t("lend_invalid_travel", lang))
            return True

        flow.data["travel_charge_per_km"] = travel
        flow.step = "RADIUS"
        db.put_chat_flow(flow)

        await telegram_client.send_message(chat_id, t("lend_ask_radius", lang))
        return True

    elif step == "RADIUS":
        try:
            radius = float(stripped.replace("km", "").strip())
        except ValueError:
            await telegram_client.send_message(chat_id, t("lend_invalid_radius", lang))
            return True

        if radius < 1 or radius > 100:
            await telegram_client.send_message(chat_id, t("lend_invalid_radius", lang))
            return True

        flow.data["service_radius_km"] = radius
        flow.step = "TERMS"
        db.put_chat_flow(flow)

        await telegram_client.send_message(chat_id, t("lend_ask_terms", lang))
        return True

    elif step == "TERMS":
        if stripped.lower() in ("/skip", "skip", "none", "-"):
            terms_note = None
        else:
            terms_note = stripped[:160]

        provider_id = f"PRV_{secrets.token_hex(3).upper()}"
        try:
            provider, machine, notifs = services.register_lender(
                db=db,
                provider_id=provider_id,
                name=flow.data["name"],
                contact_phone=flow.data["phone"],
                district=flow.data["district"],
                state=flow.data["state"],
                lat=flow.data["lat"],
                lon=flow.data["lon"],
                telegram_chat_id=chat_id,
                machine_type=flow.data.get("machine_type", "SUPER_SEEDER"),
                rate_per_acre=flow.data["rate_per_acre"],
                travel_charge_per_km=flow.data.get("travel_charge_per_km", 0.0),
                service_radius_km=flow.data["service_radius_km"],
                terms_note=terms_note,
                phone_verified=flow.data.get("phone_verified", False),
            )
        except ValueError as exc:
            err_msg = str(exc)
            if "phone number already exists" in err_msg.lower():
                await telegram_client.send_message(chat_id, t("lend_duplicate_phone", lang))
                flow.step = "CONTACT"
                db.put_chat_flow(flow)
                return True
            logger.error("[LenderFlow] Registration error: %s", exc)
            await telegram_client.send_message(chat_id, f"⚠️ Error: {err_msg}")
            return True

        db.delete_chat_flow(chat_id)

        await telegram_client.send_message(
            chat_id,
            t(
                "lend_success",
                lang,
                provider_id=provider.provider_id,
                machine_type=machine.machine_type,
                rate=machine.rate_per_acre,
                district=provider.district,
            ),
        )
        for n in notifs:
            await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)

        return True

    return False


async def handle_lender_callback(
    data: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    flow: ChatFlow,
    lang: str = "hi",
) -> bool:
    """Handle callback button clicks (e.g. machine type) during LEND flow."""
    if flow.flow != "LEND":
        return False

    if flow.step == "MACHINE_TYPE" and data.startswith("mch_type:"):
        mtype = data.split(":", 1)[1]
        flow.data["machine_type"] = mtype
        flow.step = "RATE"
        db.put_chat_flow(flow)

        await telegram_client.send_message(chat_id, t("lend_ask_rate", lang))
        return True

    return False
