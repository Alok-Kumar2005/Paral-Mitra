"""Scheduled Lambda handler for expiring stale bookings and background maintenance.

Triggered by EventBridge Scheduler every 15 minutes.
Runs:
  1. services.expire_stale_bookings() — expire PENDING bookings older than 48h and notify farmers.
  2. db.prune_expired()               — clean expired cache/messages.

Guarantees:
  - Fresh TelegramClient per asyncio.run() invocation (no closed loop reuse).
  - Pure deterministic transition logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.bot.telegram_client import TelegramClient
from src.common.db import DatabaseClient, get_db_client
from src.marketplace import services

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_db: DatabaseClient | None = None


def _get_db() -> DatabaseClient:
    global _db
    if _db is None:
        _db = get_db_client()
    return _db


async def _sweep(db: DatabaseClient) -> dict[str, Any]:
    expired_bookings, notifications = services.expire_stale_bookings(db=db)
    logger.info("[Sweeper] Expired %d stale bookings", len(expired_bookings))

    if notifications:
        # Create fresh TelegramClient for async execution
        async with TelegramClient() as client:
            for notif in notifications:
                try:
                    await client.send_message(
                        chat_id=notif.chat_id,
                        text=notif.text,
                        reply_markup=notif.reply_markup,
                    )
                except Exception as exc:
                    logger.warning("[Sweeper] Failed to send notification to %s: %s", notif.chat_id, exc)

    # Run DB maintenance
    try:
        db.prune_expired()
    except Exception as exc:
        logger.warning("[Sweeper] prune_expired warning: %s", exc)

    return {
        "ok": True,
        "expired_count": len(expired_bookings),
        "notifications_sent": len(notifications),
    }


def handler(event: Any, context: Any) -> dict[str, Any]:  # noqa: ARG001
    """EventBridge-triggered Lambda entrypoint."""
    db = _get_db()
    logger.info("[Sweeper] Starting scheduled booking sweep...")
    try:
        result = asyncio.run(_sweep(db=db))
        logger.info("[Sweeper] Sweep completed: %s", result)
        return result
    except Exception as exc:
        logger.exception("[Sweeper] Sweep failed: %s", exc)
        raise
