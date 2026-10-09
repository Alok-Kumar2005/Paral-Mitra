"""Telegram webhook receiver Lambda handler.

Handles two routes from API Gateway HTTP API (payload format 2.0):
  POST /telegram/webhook  — verify secret, enqueue update to SQS FIFO, return 200.
  GET  /health            — liveness probe, no DB access.

Design rules:
  - Imports ONLY boto3 / json / hmac / os for fast cold start.
  - Returns 200 for all valid-secret requests (even if body is malformed) so
    Telegram does not retry the delivery. Returns 500 only if SQS throws.
  - Never logs message text or secrets.
"""

from __future__ import annotations

import hmac
import json
import logging
import os

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_VERSION = "0.1.0"

# Module-level SQS client (reused across warm invocations).
_sqs = boto3.client("sqs", region_name=os.environ.get("AWS_REGION", "ap-south-1"))
_QUEUE_URL: str = os.environ.get("UPDATE_QUEUE_URL", "")
_WEBHOOK_SECRET: str = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _get_chat_id(update: dict) -> str:
    """Extract the chat/user ID for FIFO MessageGroupId."""
    # Callback queries have from.id
    cb = update.get("callback_query")
    if cb:
        user_id = cb.get("from", {}).get("id")
        if user_id is not None:
            return str(user_id)

    # Regular messages have message.chat.id
    msg = update.get("message")
    if msg:
        chat_id = msg.get("chat", {}).get("id")
        if chat_id is not None:
            return str(chat_id)

    return "misc"


def _handle_webhook(event: dict) -> dict:
    """Process POST /telegram/webhook."""
    # ── 1. Verify shared secret ──────────────────────────────────────────────
    headers: dict = event.get("headers") or {}
    # HTTP API header names are lower-cased by API Gateway
    incoming_token = headers.get("x-telegram-bot-api-secret-token", "")

    if not _WEBHOOK_SECRET:
        logger.error("TELEGRAM_WEBHOOK_SECRET is not configured.")
        return _response(500, {"ok": False, "error": "server misconfiguration"})

    # Use hmac.compare_digest to prevent timing attacks
    token_ok = hmac.compare_digest(
        incoming_token.encode("utf-8"),
        _WEBHOOK_SECRET.encode("utf-8"),
    )
    if not token_ok:
        logger.warning("Rejected webhook request: invalid or missing secret token.")
        return _response(403, {"ok": False, "error": "forbidden"})

    # ── 2. Parse body ────────────────────────────────────────────────────────
    raw_body: str = event.get("body") or ""
    try:
        update: dict = json.loads(raw_body)
        update_id: int = int(update.get("update_id", 0))
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.error("Failed to parse Telegram update body: %s", exc)
        # Still return 200 — do NOT let Telegram retry a malformed body.
        return _response(200, {"ok": True, "note": "body_parse_error"})

    # ── 3. Enqueue to SQS FIFO ───────────────────────────────────────────────
    group_id = _get_chat_id(update)
    dedup_id = str(update_id) if update_id else f"misc-{hash(raw_body) & 0xFFFFFFFF}"

    if not _QUEUE_URL:
        logger.error("UPDATE_QUEUE_URL is not configured.")
        return _response(500, {"ok": False, "error": "queue not configured"})

    try:
        _sqs.send_message(
            QueueUrl=_QUEUE_URL,
            MessageBody=raw_body,
            MessageGroupId=group_id,
            MessageDeduplicationId=dedup_id,
        )
        logger.info(
            "Enqueued update_id=%s group_id=%s dedup_id=%s",
            update_id,
            group_id,
            dedup_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("SQS send_message failed: %s", exc)
        return _response(500, {"ok": False, "error": "queue send failed"})

    return _response(200, {"ok": True})


def _handle_health() -> dict:
    """Process GET /health — no DB access."""
    return _response(200, {"ok": True, "version": _VERSION})


def handler(event: dict, context: object) -> dict:  # noqa: ARG001
    """AWS Lambda entry point for API Gateway HTTP API (payload v2)."""
    route_key: str = event.get("routeKey", "")

    if route_key == "GET /health":
        return _handle_health()

    if route_key == "POST /telegram/webhook":
        return _handle_webhook(event)

    # Fallback: unknown route
    logger.warning("Unhandled routeKey: %s", route_key)
    return _response(404, {"ok": False, "error": "not found"})
