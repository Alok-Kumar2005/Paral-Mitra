"""Pure business logic services for Provider Marketplace and Booking Loop.

Rules:
  - NO Telegram calls or httpx network requests in this file.
  - Returns (domain_entity, list[Notification]) tuples for callers (Lambda/bot router) to send.
  - Strict input validation and atomic state transitions via DatabaseClient.
  - Booking ID format: BK-XXXXXXXX (8-char upper hex).
  - Phone numbers are NEVER logged.
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any

from src.common.db import DatabaseClient, _haversine_km
from src.common.models import (
    Booking,
    BookingStatus,
    Buyer,
    BuyerType,
    ChatFlow,
    Machine,
    MachineType,
    Notification,
    OptionType,
    Provider,
    ProviderStatus,
    ProviderType,
    PublicMachineView,
    TransportTerms,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_booking_id() -> str:
    """Generate canonical booking ID: BK-XXXXXXXX (8-character uppercase hex)."""
    return f"BK-{secrets.token_hex(4).upper()}"


# ── Passcode & Flow Security ──────────────────────────────────────────────────


def verify_owner_passcode(
    passcode: str,
    flow: ChatFlow,
    expected_passcode: str | None = None,
    max_attempts: int = 3,
    lockout_minutes: int = 15,
) -> tuple[bool, str | None]:
    """Verify owner portal passcode with exponential-style lockout.

    Returns:
        (is_valid, error_message_key)
    """
    now = _utc_now()
    if flow.locked_until and flow.locked_until > now:
        remaining_mins = int((flow.locked_until - now).total_seconds() / 60) + 1
        return False, f"LOCKED_OUT:{remaining_mins}"

    expected = expected_passcode or os.getenv("OWNER_PASSCODE", "kisan123")
    if passcode.strip() == expected.strip():
        flow.attempts = 0
        flow.locked_until = None
        return True, None

    flow.attempts += 1
    if flow.attempts >= max_attempts:
        flow.locked_until = now + timedelta(minutes=lockout_minutes)
        return False, f"LOCKED_OUT:{lockout_minutes}"

    return False, "INVALID_PASSCODE"


# ── Provider Lifecycle ────────────────────────────────────────────────────────


def register_provider(
    db: DatabaseClient,
    provider_id: str,
    provider_type: ProviderType | str,
    name: str,
    contact_phone: str,
    district: str,
    state: str,
    lat: float,
    lon: float,
    telegram_chat_id: int | str | None = None,
    admin_chat_ids: list[int] | None = None,
) -> tuple[Provider, list[Notification]]:
    """Register a new CHC or Buyer provider in PENDING status.
    
    Emits notification to admins for verification.
    """
    provider = Provider(
        provider_id=provider_id,
        provider_type=provider_type,
        name=name.strip(),
        contact_phone=contact_phone.strip(),
        telegram_chat_id=str(telegram_chat_id) if telegram_chat_id else None,
        district=district.strip(),
        state=state.strip(),
        lat=lat,
        lon=lon,
        status=ProviderStatus.PENDING,
        created_at=_utc_now(),
    )
    db.put_provider(provider)
    logger.info("[Marketplace] Provider registered: provider_id=%s, district=%s", provider_id, district)

    notifications: list[Notification] = []
    # Notify admins with interactive inline keyboard
    admins = admin_chat_ids or [
        int(x.strip())
        for x in os.getenv("ADMIN_CHAT_IDS", "").split(",")
        if x.strip().isdigit()
    ]
    for admin_chat_id in admins:
        notifications.append(
            Notification(
                chat_id=admin_chat_id,
                text=(
                    f"🚜 *New Provider Registration*\n\n"
                    f"ID: `{provider.provider_id}`\n"
                    f"Type: *{provider.provider_type}*\n"
                    f"Name: *{provider.name}*\n"
                    f"District: *{provider.district}, {provider.state}*\n"
                    f"Status: *PENDING*"
                ),
                reply_markup={
                    "inline_keyboard": [
                        [
                            {"text": "✅ Approve", "callback_data": f"adm_app:{provider.provider_id}"},
                            {"text": "❌ Reject", "callback_data": f"adm_rej:{provider.provider_id}"},
                        ]
                    ]
                },
            )
        )

    return provider, notifications


def approve_provider(
    db: DatabaseClient,
    provider_id: str,
    admin_chat_id: int | str,
) -> tuple[Provider | None, list[Notification]]:
    """Approve a pending provider and notify them."""
    provider = db.update_provider_status(
        provider_id=provider_id,
        status=ProviderStatus.VERIFIED,
        verified_by=str(admin_chat_id),
    )
    if not provider:
        return None, []

    logger.info("[Marketplace] Provider approved: provider_id=%s by admin=%s", provider_id, admin_chat_id)
    notifications: list[Notification] = []
    if provider.telegram_chat_id and provider.telegram_chat_id.isdigit():
        notifications.append(
            Notification(
                chat_id=int(provider.telegram_chat_id),
                text=(
                    "🎉 *Your provider account has been VERIFIED!*\n\n"
                    "Farmers in your district can now discover your machinery/facility and send bookings."
                ),
            )
        )
    return provider, notifications


def reject_provider(
    db: DatabaseClient,
    provider_id: str,
    admin_chat_id: int | str,
) -> tuple[Provider | None, list[Notification]]:
    """Reject a pending provider and notify them."""
    provider = db.update_provider_status(
        provider_id=provider_id,
        status=ProviderStatus.REJECTED,
        verified_by=str(admin_chat_id),
    )
    if not provider:
        return None, []

    logger.info("[Marketplace] Provider rejected: provider_id=%s by admin=%s", provider_id, admin_chat_id)
    notifications: list[Notification] = []
    if provider.telegram_chat_id and provider.telegram_chat_id.isdigit():
        notifications.append(
            Notification(
                chat_id=int(provider.telegram_chat_id),
                text=(
                    "❌ *Your provider registration was not approved.*\n\n"
                    "Please contact support or re-check the submitted details."
                ),
            )
        )
    return provider, notifications


def suspend_provider(
    db: DatabaseClient,
    provider_id: str,
    admin_chat_id: int | str,
) -> tuple[Provider | None, list[Notification]]:
    """Suspend a verified provider."""
    provider = db.update_provider_status(
        provider_id=provider_id,
        status=ProviderStatus.SUSPENDED,
        verified_by=str(admin_chat_id),
    )
    if not provider:
        return None, []

    logger.info("[Marketplace] Provider suspended: provider_id=%s", provider_id)
    notifications: list[Notification] = []
    if provider.telegram_chat_id and provider.telegram_chat_id.isdigit():
        notifications.append(
            Notification(
                chat_id=int(provider.telegram_chat_id),
                text="⚠️ *Your provider account has been temporarily suspended.*",
            )
        )
    return provider, notifications


# ── Machinery Management ──────────────────────────────────────────────────────


def add_machine(
    db: DatabaseClient,
    machine_id: str,
    provider_id: str,
    machine_type: MachineType | str,
    village: str,
    district: str,
    lat: float,
    lon: float,
    rate_per_acre: float,
    travel_charge_per_km: float,
    service_radius_km: float,
    available_from: date | None = None,
) -> tuple[Machine, list[Notification]]:
    """Register agricultural machinery under a provider."""
    machine = Machine(
        machine_id=machine_id,
        provider_id=provider_id,
        machine_type=machine_type,
        village=village.strip(),
        district=district.strip(),
        lat=lat,
        lon=lon,
        rate_per_acre=rate_per_acre,
        travel_charge_per_km=travel_charge_per_km,
        service_radius_km=service_radius_km,
        available_from=available_from or date.today(),
        blocked_dates=[],
        status="ACTIVE",
        rating_avg=None,
        rating_count=0,
        source="MARKETPLACE",
        is_synthetic=False,
    )
    db.put_machine(machine)
    logger.info("[Marketplace] Machine added: machine_id=%s for provider=%s", machine_id, provider_id)
    return machine, []


def update_machine(
    db: DatabaseClient,
    machine_id: str,
    rate_per_acre: float | None = None,
    travel_charge_per_km: float | None = None,
    service_radius_km: float | None = None,
    status: str | None = None,
) -> tuple[Machine | None, list[Notification]]:
    """Update machine rates, radius, or status."""
    machine = db.get_machine(machine_id)
    if not machine:
        return None, []

    updates = machine.model_dump()
    if rate_per_acre is not None:
        updates["rate_per_acre"] = rate_per_acre
    if travel_charge_per_km is not None:
        updates["travel_charge_per_km"] = travel_charge_per_km
    if service_radius_km is not None:
        updates["service_radius_km"] = service_radius_km
    if status is not None:
        updates["status"] = status

    updated = Machine.model_validate(updates)
    db.put_machine(updated)
    logger.info("[Marketplace] Machine updated: machine_id=%s", machine_id)
    return updated, []


def set_machine_unavailable(
    db: DatabaseClient,
    machine_id: str,
    blocked_date: date,
) -> tuple[Machine | None, list[Notification]]:
    """Add a blocked date to machine schedule."""
    machine = db.get_machine(machine_id)
    if not machine:
        return None, []

    if blocked_date not in machine.blocked_dates:
        machine.blocked_dates.append(blocked_date)
        db.put_machine(machine)
    return machine, []


def deactivate_machine(
    db: DatabaseClient,
    machine_id: str,
) -> tuple[Machine | None, list[Notification]]:
    """Mark machine INACTIVE."""
    return update_machine(db, machine_id, status="INACTIVE")


def reactivate_machine(
    db: DatabaseClient,
    machine_id: str,
) -> tuple[Machine | None, list[Notification]]:
    """Mark machine ACTIVE."""
    return update_machine(db, machine_id, status="ACTIVE")


# ── Buyer Management ──────────────────────────────────────────────────────────


def register_buyer(
    db: DatabaseClient,
    buyer_id: str,
    provider_id: str | None,
    name: str,
    buyer_type: BuyerType | str,
    district: str,
    lat: float,
    lon: float,
    price_per_tonne: float,
    min_quantity_tonnes: float,
    transport_terms: TransportTerms | str,
    phone: str,
) -> tuple[Buyer, list[Notification]]:
    """Register commercial buyer facility."""
    buyer = Buyer(
        buyer_id=buyer_id,
        provider_id=provider_id,
        name=name.strip(),
        buyer_type=buyer_type,
        district=district.strip(),
        lat=lat,
        lon=lon,
        price_per_tonne=price_per_tonne,
        min_quantity_tonnes=min_quantity_tonnes,
        transport_terms=transport_terms,
        phone=phone.strip(),
        source="MARKETPLACE",
        is_synthetic=False,
    )
    db.put_buyer(buyer)
    logger.info("[Marketplace] Buyer facility registered: buyer_id=%s", buyer_id)
    return buyer, []


def update_buyer_price(
    db: DatabaseClient,
    buyer_id: str,
    price_per_tonne: float,
) -> tuple[Buyer | None, list[Notification]]:
    """Update commercial buyer procurement price."""
    buyer = db.get_buyer(buyer_id)
    if not buyer:
        return None, []

    updates = buyer.model_dump()
    updates["price_per_tonne"] = price_per_tonne
    updated = Buyer.model_validate(updates)
    db.put_buyer(updated)
    return updated, []


# ── Public Discovery Views ────────────────────────────────────────────────────


def list_nearby_machines(
    db: DatabaseClient,
    lat: float,
    lon: float,
    radius_km: float = 50.0,
) -> list[PublicMachineView]:
    """Return sanitized public machine views within radius with distance calculation."""
    machines = db.list_bookable_machines(lat=lat, lon=lon, radius_km=radius_km)
    results: list[PublicMachineView] = []
    for m in machines:
        dist = round(_haversine_km(lat, lon, m.lat, m.lon), 1)
        p_name = m.owner_name or "Verified CHC"
        p_status = ProviderStatus.VERIFIED
        if m.provider_id:
            p = db.get_provider(m.provider_id)
            if p:
                p_name = p.name
                p_status = p.status
        results.append(
            PublicMachineView(
                machine_id=m.machine_id,
                machine_type=m.machine_type,
                village=m.village,
                district=m.district,
                rate_per_acre=m.rate_per_acre,
                travel_charge_per_km=m.travel_charge_per_km,
                service_radius_km=m.service_radius_km,
                rating_avg=m.rating_avg,
                rating_count=m.rating_count,
                provider_name=p_name,
                provider_status=p_status,
                distance_km=dist,
            )
        )
    return sorted(results, key=lambda x: x.distance_km or 0.0)


# ── Real Booking Loop ─────────────────────────────────────────────────────────


def create_booking(
    db: DatabaseClient,
    farmer_chat_id: int,
    target_id: str,
    acres: float,
    requested_date: date,
    option_type: OptionType | str,
    booking_id: str | None = None,
) -> tuple[Booking, list[Notification]]:
    """Unified entrypoint for creating booking requests.

    Validates target availability, writes booking in PENDING state with 48h TTL,
    and returns notifications for farmer and operator.
    """
    bid = booking_id or generate_booking_id()
    now = _utc_now()
    expires_at = now + timedelta(hours=48)

    provider_id: str | None = None
    target_name: str = target_id
    operator_chat_id: int | None = None
    farmer_district: str = ""

    # Fetch farmer district for anonymous context in operator notification
    session = db.get_session(farmer_chat_id)
    if session and session.district:
        farmer_district = session.district

    # Normalize option_type to string value for comparison
    opt_type_str = option_type.value if hasattr(option_type, "value") else str(option_type).upper()

    # Determine target and provider details
    if opt_type_str == OptionType.IN_SITU.value:
        machine = db.get_machine(target_id)
        if not machine:
            raise ValueError(f"Machine {target_id} not found.")
        if machine.status != "ACTIVE":
            raise ValueError(f"Machine {target_id} is currently inactive.")
        if requested_date in machine.blocked_dates:
            raise ValueError(f"Machine {target_id} is unavailable on {requested_date.isoformat()}.")
        target_name = f"{machine.machine_type} ({machine.village})"
        provider_id = machine.provider_id
        if machine.owner_telegram_chat_id:
            operator_chat_id = machine.owner_telegram_chat_id
    else:
        buyer = db.get_buyer(target_id)
        if not buyer:
            raise ValueError(f"Buyer facility {target_id} not found.")
        target_name = f"{buyer.name} ({buyer.buyer_type})"
        provider_id = buyer.provider_id

    if provider_id:
        provider = db.get_provider(provider_id)
        if provider and provider.telegram_chat_id and provider.telegram_chat_id.isdigit():
            operator_chat_id = int(provider.telegram_chat_id)

    booking = Booking(
        booking_id=bid,
        farmer_chat_id=farmer_chat_id,
        provider_id=provider_id,
        option_type=option_type,
        target_id=target_id,
        acres=acres,
        requested_date=requested_date,
        status=BookingStatus.PENDING,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
    )
    db.put_booking(booking)
    logger.info("[Marketplace] Booking created: booking_id=%s, target=%s", bid, target_id)

    notifications: list[Notification] = []

    # 1. Notification to Farmer
    notifications.append(
        Notification(
            chat_id=farmer_chat_id,
            text=(
                f"📋 *Booking Request Created*\n\n"
                f"Booking ID: `{bid}`\n"
                f"Target: *{target_name}*\n"
                f"Area: *{acres:.1f} acres*\n"
                f"Date: *{requested_date.isoformat()}*\n"
                f"Status: ⏳ *PENDING (Awaiting Operator Confirmation)*\n\n"
                f"The operator has 48 hours to confirm your request."
            ),
        )
    )

    # 2. Notification to Operator (if linked on Telegram)
    if operator_chat_id:
        location_label = f"in *{farmer_district}*" if farmer_district else "in your service area"
        notifications.append(
            Notification(
                chat_id=operator_chat_id,
                text=(
                    f"🚜 *New Job Request!* [ID: `{bid}`]\n\n"
                    f"Equipment/Facility: *{target_name}*\n"
                    f"Location: {location_label}\n"
                    f"Area: *{acres:.1f} acres*\n"
                    f"Requested Date: *{requested_date.isoformat()}*\n\n"
                    f"Please accept or decline this booking request:"
                ),
                reply_markup={
                    "inline_keyboard": [
                        [
                            {"text": "✅ Accept Job", "callback_data": f"bk_acc:{bid}"},
                            {"text": "❌ Decline", "callback_data": f"bk_dec:{bid}"},
                        ]
                    ]
                },
            )
        )

    return booking, notifications


def owner_decide(
    db: DatabaseClient,
    booking_id: str,
    operator_chat_id: int | str,
    accept: bool,
) -> tuple[Booking | None, list[Notification]]:
    """Atomic decision by machine/facility operator on a pending booking.

    Uses atomic Compare-And-Swap (CAS) in DB to prevent race conditions or late actions.
    """
    booking = db.get_booking(booking_id)
    if not booking:
        return None, [Notification(chat_id=int(operator_chat_id), text="Booking not found.")]

    # Authorisation check
    is_authorized = False
    operator_phone = ""
    if booking.provider_id:
        provider = db.get_provider(booking.provider_id)
        if provider:
            if provider.telegram_chat_id == str(operator_chat_id):
                is_authorized = True
                operator_phone = provider.contact_phone
    if not is_authorized:
        # Check if legacy machine owner
        machine = db.get_machine(booking.target_id)
        if machine and machine.owner_telegram_chat_id == int(operator_chat_id):
            is_authorized = True
            operator_phone = machine.owner_phone or ""

    # Allow admins to decide if configured
    admins = [
        int(x.strip())
        for x in os.getenv("ADMIN_CHAT_IDS", "").split(",")
        if x.strip().isdigit()
    ]
    if int(operator_chat_id) in admins:
        is_authorized = True

    if not is_authorized:
        logger.warning("[Marketplace] Unauthorized decision attempt on %s by %s", booking_id, operator_chat_id)
        return None, [Notification(chat_id=int(operator_chat_id), text="⛔ You are not authorised to decide on this booking.")]

    new_status = BookingStatus.CONFIRMED if accept else BookingStatus.REJECTED
    now = _utc_now()

    updated = db.update_booking_status_if(
        booking_id=booking_id,
        expected_current_statuses=[BookingStatus.PENDING],
        new_status=new_status,
        decided_by=str(operator_chat_id),
        decided_at=now,
    )

    if not updated:
        # Atomic CAS failed: already decided or expired
        return None, [
            Notification(
                chat_id=int(operator_chat_id),
                text=f"⚠️ Booking `{booking_id}` is no longer pending (already decided or expired).",
            )
        ]

    notifications: list[Notification] = []

    if accept:
        # Block machine date if in-situ
        machine = db.get_machine(booking.target_id)
        if machine:
            set_machine_unavailable(db, machine.machine_id, booking.requested_date)

        contact_msg = f"\nOperator Phone: *{operator_phone}*" if operator_phone else ""
        notifications.append(
            Notification(
                chat_id=booking.farmer_chat_id,
                text=(
                    f"🎉 *Booking CONFIRMED!* [ID: `{booking_id}`]\n\n"
                    f"Target: *{booking.target_id}*\n"
                    f"Scheduled Date: *{booking.requested_date.isoformat()}*\n"
                    f"Area: *{booking.acres:.1f} acres*{contact_msg}\n\n"
                    f"The operator will arrive on the scheduled date."
                ),
            )
        )
        notifications.append(
            Notification(
                chat_id=int(operator_chat_id),
                text=f"✅ You accepted booking `{booking_id}` for {booking.requested_date.isoformat()}.",
            )
        )
    else:
        notifications.append(
            Notification(
                chat_id=booking.farmer_chat_id,
                text=(
                    f"❌ *Booking Declined* [ID: `{booking_id}`]\n\n"
                    f"The operator was unable to accept your request for {booking.requested_date.isoformat()}.\n"
                    f"Please type /options or /machines to check alternative available machinery."
                ),
            )
        )
        notifications.append(
            Notification(
                chat_id=int(operator_chat_id),
                text=f"❌ You declined booking `{booking_id}`.",
            )
        )

    logger.info("[Marketplace] Booking %s decided: status=%s by operator=%s", booking_id, new_status.value, operator_chat_id)
    return updated, notifications


def mark_completed(
    db: DatabaseClient,
    booking_id: str,
    actor_chat_id: int | str,
) -> tuple[Booking | None, list[Notification]]:
    """Mark a confirmed booking as COMPLETED and send rating prompt to farmer."""
    updated = db.update_booking_status_if(
        booking_id=booking_id,
        expected_current_statuses=[BookingStatus.CONFIRMED],
        new_status=BookingStatus.COMPLETED,
        decided_by=str(actor_chat_id),
        decided_at=_utc_now(),
    )
    if not updated:
        return None, []

    logger.info("[Marketplace] Booking %s marked COMPLETED", booking_id)
    notifications = [
        Notification(
            chat_id=updated.farmer_chat_id,
            text=(
                f"✅ *Work Completed!* [ID: `{booking_id}`]\n\n"
                f"Your residue management job has been marked complete.\n"
                f"Please rate your operator's service:"
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "⭐ 1", "callback_data": f"bk_rate:{booking_id}:1"},
                        {"text": "⭐⭐ 2", "callback_data": f"bk_rate:{booking_id}:2"},
                        {"text": "⭐⭐⭐ 3", "callback_data": f"bk_rate:{booking_id}:3"},
                    ],
                    [
                        {"text": "⭐⭐⭐⭐ 4", "callback_data": f"bk_rate:{booking_id}:4"},
                        {"text": "⭐⭐⭐⭐⭐ 5", "callback_data": f"bk_rate:{booking_id}:5"},
                    ]
                ]
            },
        )
    ]
    return updated, notifications


def rate_provider(
    db: DatabaseClient,
    booking_id: str,
    farmer_chat_id: int,
    rating: int,
) -> tuple[Booking | None, list[Notification]]:
    """Record farmer rating (1-5) and update aggregate machine ratings."""
    if not (1 <= rating <= 5):
        raise ValueError("Rating must be an integer between 1 and 5.")

    booking = db.get_booking(booking_id)
    if not booking:
        return None, []
    if booking.farmer_chat_id != farmer_chat_id:
        logger.warning("[Marketplace] Unauthorized rating attempt on %s by farmer %s", booking_id, farmer_chat_id)
        return None, []

    updated = db.add_booking_rating(booking_id, rating)
    logger.info("[Marketplace] Rating submitted for booking %s: %d stars", booking_id, rating)
    notifications = [
        Notification(
            chat_id=farmer_chat_id,
            text=f"🙏 *Thank you!* Your rating of {rating} ⭐ has been recorded.",
        )
    ]
    return updated, notifications


def expire_stale_bookings(
    db: DatabaseClient,
    cutoff_utc: datetime | None = None,
) -> tuple[list[Booking], list[Notification]]:
    """Sweeper job: find expired PENDING bookings, mark EXPIRED, and notify farmers."""
    now = cutoff_utc or _utc_now()
    stale_list = db.list_stale_pending_bookings(cutoff_utc=now)
    expired_bookings: list[Booking] = []
    notifications: list[Notification] = []

    for b in stale_list:
        updated = db.update_booking_status_if(
            booking_id=b.booking_id,
            expected_current_statuses=[BookingStatus.PENDING],
            new_status=BookingStatus.EXPIRED,
            decided_by="system:sweeper",
            decided_at=now,
        )
        if updated:
            expired_bookings.append(updated)
            notifications.append(
                Notification(
                    chat_id=updated.farmer_chat_id,
                    text=(
                        f"⏰ *Booking Request Expired* [ID: `{updated.booking_id}`]\n\n"
                        f"The operator did not respond within 48 hours.\n"
                        f"Please explore other available equipment or buyers via /options or /machines."
                    ),
                )
            )

    logger.info("[Marketplace] Sweeper expired %d stale bookings", len(expired_bookings))
    return expired_bookings, notifications
