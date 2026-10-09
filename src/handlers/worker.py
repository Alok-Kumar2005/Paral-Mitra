"""SQS worker Lambda handler for Parali Mitra.

Triggered by an SQS FIFO queue (batch size 1, ReportBatchItemFailures enabled).

Design rules:
  - asyncio.run() per record — creates a FRESH TelegramClient on each invocation.
    The event loop is closed after asyncio.run(); never cache an httpx.AsyncClient
    across Lambda invocations (the underlying event loop is gone).
  - Module-level DatabaseClient singleton IS safe to reuse (psycopg connection
    is synchronous and reused across warm invocations via health-check ping).
  - ServiceUnavailableError (Neon wake-up) → send farmer "waking up" message +
    report item as failed for SQS retry.
  - Any other exception → log update_id + chat_id only (no message text, no
    secrets) → report failure for retry. Send generic apology ONLY on the final
    attempt (ApproximateReceiveCount >= maxReceiveCount from message attributes).
  - Returns {"batchItemFailures": [...]} for ReportBatchItemFailures.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Module-level DB singleton ─────────────────────────────────────────────────
# Safe to reuse across warm invocations; PostgresClient health-checks each use.
_db = None


def _get_db():
    """Lazy-initialise the module-level DatabaseClient singleton."""
    global _db
    if _db is None:
        from src.common.db import get_db_client
        _db = get_db_client()
    return _db


# ── Localised retry messages ───────────────────────────────────────────────────

_WAKING_UP_MSGS: dict[str, str] = {
    "en": (
        "⏳ The service is waking up — please try again in a minute. "
        "Your message has been saved and will be processed shortly."
    ),
    "hi": (
        "⏳ सेवा अभी शुरू हो रही है — कृपया एक मिनट में दोबारा प्रयास करें। "
        "आपका संदेश सुरक्षित है और जल्द ही संसाधित होगा।"
    ),
    "pa": (
        "⏳ ਸੇਵਾ ਹੁਣੇ ਸ਼ੁਰੂ ਹੋ ਰਹੀ ਹੈ — ਕਿਰਪਾ ਕਰਕੇ ਇੱਕ ਮਿੰਟ ਵਿੱਚ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ। "
        "ਤੁਹਾਡਾ ਸੁਨੇਹਾ ਸੁਰੱਖਿਅਤ ਹੈ ਅਤੇ ਜਲਦੀ ਹੀ ਪ੍ਰਕਿਰਿਆ ਕੀਤਾ ਜਾਵੇਗਾ।"
    ),
}

_APOLOGY_MSGS: dict[str, str] = {
    "en": (
        "❌ Something went wrong processing your message. "
        "Please try again — I apologise for the inconvenience."
    ),
    "hi": (
        "❌ आपका संदेश संसाधित करने में कोई समस्या आई। "
        "कृपया दोबारा प्रयास करें — असुविधा के लिए खेद है।"
    ),
    "pa": (
        "❌ ਤੁਹਾਡਾ ਸੁਨੇਹਾ ਪ੍ਰਕਿਰਿਆ ਕਰਨ ਵਿੱਚ ਕੋਈ ਸਮੱਸਿਆ ਆਈ। "
        "ਕਿਰਪਾ ਕਰਕੇ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ — ਅਸੁਵਿਧਾ ਲਈ ਮਾਫ਼ੀ।"
    ),
}


def _get_lang(update: dict, db) -> str:
    """Best-effort language lookup for the farmer — defaults to 'hi'."""
    try:
        chat_id = _extract_chat_id(update)
        if chat_id:
            session = db.get_session(chat_id)
            if session and session.language:
                return session.language
    except Exception:  # noqa: BLE001
        pass
    return "hi"


def _extract_chat_id(update: dict) -> int | None:
    """Extract chat_id from a Telegram update dict."""
    cb = update.get("callback_query")
    if cb:
        uid = cb.get("from", {}).get("id")
        if uid is not None:
            return int(uid)

    msg = update.get("message")
    if msg:
        cid = msg.get("chat", {}).get("id")
        if cid is not None:
            return int(cid)

    return None


def _is_final_attempt(record: dict, max_receive_count: int = 3) -> bool:
    """Return True if this is the last SQS delivery attempt."""
    # SQS system attributes live in "attributes", custom attributes in "messageAttributes"
    attrs = record.get("attributes") or record.get("messageAttributes") or {}
    arc_val = attrs.get("ApproximateReceiveCount", "1")
    if isinstance(arc_val, dict):
        arc_val = arc_val.get("stringValue", "1")
    try:
        arc = int(arc_val)
    except (ValueError, TypeError):
        arc = 1
    return arc >= max_receive_count


async def _process_record(record: dict) -> None:
    """Async coroutine that processes a single SQS record."""
    from src.bot.router import handle_update
    from src.bot.telegram_client import TelegramClient
    from src.common.db import ServiceUnavailableError

    body_str: str = record.get("body", "{}")
    update: dict = {}
    update_id: int | None = None
    chat_id: int | None = None

    db = _get_db()

    # Create a FRESH TelegramClient per invocation — never cached across calls
    # because asyncio.run() closes the event loop each time.
    client = TelegramClient()

    try:
        update = json.loads(body_str)
        update_id = update.get("update_id")
        chat_id = _extract_chat_id(update)

        logger.info(
            "Processing update_id=%s chat_id=%s",
            update_id,
            chat_id,
        )

        await handle_update(update, client=client, db=db)

    except ServiceUnavailableError as exc:
        logger.warning(
            "ServiceUnavailableError for update_id=%s chat_id=%s: %s",
            update_id,
            chat_id,
            exc,
        )
        # Send "waking up" message and re-raise so the record is retried.
        if chat_id:
            lang = _get_lang(update, db)
            msg = _WAKING_UP_MSGS.get(lang, _WAKING_UP_MSGS["en"])
            try:
                await client.sendMessage(chat_id, msg)
            except Exception:  # noqa: BLE001
                pass
        raise

    except Exception as exc:  # noqa: BLE001
        # Log only non-sensitive identifiers — never message text or secrets.
        logger.exception(
            "Unhandled exception for update_id=%s chat_id=%s: %s",
            update_id,
            chat_id,
            exc,
        )
        # Send apology only on final delivery attempt.
        if chat_id and _is_final_attempt(record):
            lang = _get_lang(update, db)
            msg = _APOLOGY_MSGS.get(lang, _APOLOGY_MSGS["en"])
            try:
                await client.sendMessage(chat_id, msg)
            except Exception:  # noqa: BLE001
                pass
        raise

    finally:
        # Always close the httpx client — its underlying event loop will be
        # destroyed by asyncio.run() returning, so this is belt-and-suspenders.
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            pass


def handler(event: dict, context: Any) -> dict:  # noqa: ARG001
    """AWS Lambda entry point for SQS FIFO trigger (batch size 1).

    Returns the ReportBatchItemFailures response format so failed records
    are retried while successful ones are deleted.
    """
    records: list[dict] = event.get("Records", [])
    batch_item_failures: list[dict] = []

    for record in records:
        message_id: str = record.get("messageId", "unknown")
        try:
            asyncio.run(_process_record(record))
        except Exception as exc:  # noqa: BLE001
            # Any exception → report this item as failed for SQS retry.
            logger.exception("Reporting messageId=%s as failed for retry: %s", message_id, exc)
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}
