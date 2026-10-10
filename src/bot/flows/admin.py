"""Administrator command and verification flow handlers."""

from __future__ import annotations

import logging
import os
from typing import Any

from src.bot.i18n import t
from src.bot.keyboards import get_admin_approve_reject_keyboard
from src.bot.telegram_client import TelegramClient
from src.common.db import DatabaseClient
from src.common.models import ProviderStatus
from src.marketplace import services

logger = logging.getLogger(__name__)


def is_admin(chat_id: int) -> bool:
    """Check if telegram chat ID is configured in ADMIN_CHAT_IDS."""
    admins = [
        int(x.strip())
        for x in os.getenv("ADMIN_CHAT_IDS", "").split(",")
        if x.strip().isdigit()
    ]
    # If no admins configured in development, allow dev access
    if not admins and os.getenv("DB_ENV", "prod").strip().lower() in ("dev", "test"):
        return True
    return chat_id in admins


async def handle_admin_command(
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "en",
) -> None:
    """Handle /admin dashboard command."""
    if not is_admin(chat_id):
        await telegram_client.send_message(chat_id, t("admin_only", lang))
        return

    pending_providers = db.list_providers(status=ProviderStatus.PENDING)
    if not pending_providers:
        await telegram_client.send_message(
            chat_id=chat_id,
            text="🛡️ *Admin Portal*\n\n✅ No pending provider registrations at this time.",
        )
        return

    await telegram_client.send_message(
        chat_id=chat_id,
        text=f"🛡️ *Admin Portal*\n\n📋 Found *{len(pending_providers)}* pending provider(s) awaiting verification:",
    )

    for p in pending_providers:
        msg = (
            f"🚜 *Provider Registration Review*\n\n"
            f"ID: `{p.provider_id}`\n"
            f"Type: *{p.provider_type}*\n"
            f"Name: *{p.name}*\n"
            f"Phone: *{p.contact_phone}*\n"
            f"District: *{p.district}, {p.state}*\n"
            f"Coordinates: `{p.lat:.4f}, {p.lon:.4f}`"
        )
        await telegram_client.send_message(
            chat_id=chat_id,
            text=msg,
            reply_markup=get_admin_approve_reject_keyboard(p.provider_id),
        )


async def handle_admin_callback(
    data: str,
    chat_id: int,
    db: DatabaseClient,
    telegram_client: TelegramClient,
    lang: str = "en",
) -> None:
    """Handle adm_app: and adm_rej: callbacks."""
    if not is_admin(chat_id):
        await telegram_client.send_message(chat_id, t("admin_only", lang))
        return

    if data.startswith("adm_app:"):
        provider_id = data.split(":", 1)[1].strip()
        provider, notifs = services.approve_provider(db, provider_id, admin_chat_id=chat_id)
        if provider:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=f"✅ Provider `{provider.provider_id}` (*{provider.name}*) has been APPROVED.",
            )
            for n in notifs:
                await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)
        else:
            await telegram_client.send_message(chat_id, f"⚠️ Provider `{provider_id}` not found.")

    elif data.startswith("adm_rej:"):
        provider_id = data.split(":", 1)[1].strip()
        provider, notifs = services.reject_provider(db, provider_id, admin_chat_id=chat_id)
        if provider:
            await telegram_client.send_message(
                chat_id=chat_id,
                text=f"❌ Provider `{provider.provider_id}` (*{provider.name}*) has been REJECTED.",
            )
            for n in notifs:
                await telegram_client.send_message(n.chat_id, n.text, reply_markup=n.reply_markup)
        else:
            await telegram_client.send_message(chat_id, f"⚠️ Provider `{provider_id}` not found.")
