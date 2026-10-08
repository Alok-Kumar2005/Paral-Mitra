"""Ingestion service for active fire detections from NASA FIRMS.

Fetches real-time hotspot records, assigns 10-day TTL expiry, and persists them into
the database (DynamoDB or local InMemoryDatabase) for spatial gap analysis and monitoring.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Sequence
from dotenv import load_dotenv

load_dotenv()

from src.common.db import DatabaseClient, get_db
from src.connectors.firms import FirmsClient, DEFAULT_VIIRS_SOURCE, DEFAULT_PUNJAB_HARYANA_BBOX

logger = logging.getLogger(__name__)


async def ingest_active_fires(
    db: DatabaseClient | None = None,
    firms_client: FirmsClient | None = None,
    days: int = 2,
    source: str = DEFAULT_VIIRS_SOURCE,
    area_bbox: tuple[float, float, float, float] = DEFAULT_PUNJAB_HARYANA_BBOX,
    min_confidence: str = "nominal",
    ttl_days: int = 10,
) -> int:
    """Fetches NASA FIRMS active fire detections, assigns TTL, and saves to database.
    
    Args:
        db: Database client instance (defaults to resolved get_db()).
        firms_client: FirmsClient instance (defaults to new instance using FIRMS_MAP_KEY env).
        days: Historical days lookback (1 to 10, default 2).
        source: VIIRS/MODIS sensor product.
        area_bbox: Bounding box (west, south, east, north).
        min_confidence: Minimum detection confidence threshold ("low", "nominal", "high").
        ttl_days: DynamoDB TTL duration in days (default 10 days).
        
    Returns:
        Total number of active fire hotspots ingested and persisted.
    """
    database = db or get_db()
    client = firms_client or FirmsClient()

    logger.info(
        "Starting active fire ingestion: days=%d, source=%s, min_confidence=%s, ttl_days=%d",
        days,
        source,
        min_confidence,
        ttl_days,
    )

    hotspots = await client.fetch_active_fires(
        days=days,
        source=source,
        area_bbox=area_bbox,
        min_confidence=min_confidence,
    )

    if not hotspots:
        logger.info("No active fire hotspots found matching criteria.")
        return 0

    now_epoch = int(time.time())
    ttl_epoch = now_epoch + (ttl_days * 86400)

    # Set 10-day TTL for every hotspot
    for h in hotspots:
        h.ttl = ttl_epoch

    count = database.put_hotspots(hotspots)
    logger.info("Successfully ingested %d active fire hotspots with TTL %d", count, ttl_epoch)
    return count


async def main(args: Sequence[str] | None = None) -> None:
    """CLI runner for testing active fire ingestion workflow."""
    parser = argparse.ArgumentParser(description="Ingest NASA FIRMS active fire hotspots into database.")
    parser.add_argument("--days", type=int, default=2, help="Days lookback (1-10, default 2)")
    parser.add_argument("--source", type=str, default=DEFAULT_VIIRS_SOURCE, help="VIIRS sensor source")
    parser.add_argument("--min-confidence", type=str, default="nominal", choices=["low", "nominal", "high"])
    parser.add_argument("--ttl-days", type=int, default=10, help="DynamoDB TTL retention in days (default 10)")
    parser.add_argument("--key", type=str, default=None, help="NASA FIRMS MAP_KEY")
    parsed = parser.parse_args(args)

    client = FirmsClient(map_key=parsed.key) if parsed.key else None
    db = get_db()

    print(f"Ingesting active fire hotspots for past {parsed.days} days...")
    try:
        count = await ingest_active_fires(
            db=db,
            firms_client=client,
            days=parsed.days,
            source=parsed.source,
            min_confidence=parsed.min_confidence,
            ttl_days=parsed.ttl_days,
        )
        print(f"Successfully ingested {count} active fire records into {type(db).__name__}.")
    except Exception as exc:
        print(f"Active fire ingestion failed: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
