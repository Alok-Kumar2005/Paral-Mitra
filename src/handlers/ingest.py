"""Scheduled Lambda handler for NASA FIRMS fire ingestion and DB maintenance.

Triggered by EventBridge Scheduler at rate(3 hours).
Runs:
  1. ingest_active_fires() — fetch VIIRS hotspots from NASA FIRMS API.
  2. db.prune_expired()    — remove expired hotspot rows from Postgres.

Returns a count dict for CloudWatch logs. Re-raises on error so EventBridge
can trigger a CloudWatch alarm.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Module-level DB singleton (reused across warm invocations).
_db = None


def _get_db():
    """Lazy-initialise the module-level DatabaseClient singleton."""
    global _db
    if _db is None:
        from src.common.db import get_db_client
        _db = get_db_client()
    return _db


def handler(event: Any, context: Any) -> dict:  # noqa: ARG001
    """EventBridge-triggered Lambda handler for fire ingestion."""
    from src.connectors.ingest_fires import ingest_active_fires

    db = _get_db()

    logger.info("Starting scheduled fire ingestion run.")

    # ── 1. Ingest active fires ────────────────────────────────────────────────
    try:
        ingested_count: int = asyncio.run(ingest_active_fires(db=db))
        logger.info("Ingested %d hotspot records.", ingested_count)
    except Exception as exc:
        logger.exception("FIRMS ingestion failed: %s", exc)
        raise

    # ── 2. Prune expired rows ─────────────────────────────────────────────────
    try:
        db.prune_expired()
        logger.info("prune_expired() completed successfully.")
    except Exception as exc:
        logger.exception("prune_expired() failed: %s", exc)
        raise

    result = {
        "ok": True,
        "ingested": ingested_count,
        "pruned": "ok",
    }
    logger.info("Ingest handler completed: %s", result)
    return result
