"""Officer Dashboard API handler for Parali Mitra.

Served via API Gateway HTTP API (payload format 2.0).
Routes:
  GET /dashboard      — returns single-page front end HTML
  GET /api/summary    — high-level officer metrics & 7-day sparkline
  GET /api/gaps       — machinery coverage gaps via compute_gap()
  GET /api/machines   — sanitized public machinery listings (ZERO PII)
  GET /api/fires      — active fire detections aggregated by 0.1-deg grid

Features:
  - Cache-Control: public, max-age=300 and 5-minute container in-memory cache.
  - Optional DASHBOARD_TOKEN authorization (constant-time check).
  - Strictly zero farmer PII; sanitized public machine views only.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.common.constants import get_constants
from src.common.db import DatabaseClient, get_db
from src.common.models import BookingStatus
from src.engine.geo import get_grid_cell_id
from src.engine.hotspots import compute_gap

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# In-memory container cache: key -> (timestamp, body_str, content_type)
_CACHE: dict[str, tuple[float, str, str]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes

_DASHBOARD_HTML_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "index.html"


def clear_cache() -> None:
    """Clear container in-memory cache (useful for testing)."""
    _CACHE.clear()


def _json_response(status: int, body: Any, cache_ttl: int = _CACHE_TTL_SECONDS) -> dict[str, Any]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
    }
    if status == 200 and cache_ttl > 0:
        headers["Cache-Control"] = f"public, max-age={cache_ttl}"
    else:
        headers["Cache-Control"] = "no-store"

    return {
        "statusCode": status,
        "headers": headers,
        "body": json.dumps(body, default=str),
    }


def _html_response(status: int, html_content: str, cache_ttl: int = _CACHE_TTL_SECONDS) -> dict[str, Any]:
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
    }
    if status == 200 and cache_ttl > 0:
        headers["Cache-Control"] = f"public, max-age={cache_ttl}"
    else:
        headers["Cache-Control"] = "no-store"

    return {
        "statusCode": status,
        "headers": headers,
        "body": html_content,
    }


def _verify_token(event: dict[str, Any]) -> bool:
    """Check DASHBOARD_TOKEN if configured via environment variable."""
    expected_token = os.environ.get("DASHBOARD_TOKEN", "").strip()
    if not expected_token:
        return True  # Open access when no token is configured

    query_params = event.get("queryStringParameters") or {}
    incoming_token = str(query_params.get("token") or "").strip()

    if not incoming_token:
        # Check rawQueryString as fallback
        raw_query = event.get("rawQueryString", "")
        for part in raw_query.split("&"):
            if part.startswith("token="):
                incoming_token = part.split("=", 1)[1].strip()
                break

    return hmac.compare_digest(incoming_token.encode("utf-8"), expected_token.encode("utf-8"))


def _parse_days(event: dict[str, Any], default: int = 7) -> int:
    query_params = event.get("queryStringParameters") or {}
    days_val = query_params.get("days")
    if days_val is not None:
        try:
            days = int(days_val)
            return max(1, min(days, 30))
        except (ValueError, TypeError):
            pass
    return default


def _get_hotspots_in_window(db: DatabaseClient, days: int) -> list[Any]:
    all_hotspots = db.list_hotspots()
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    return [h for h in all_hotspots if h.acq_date >= cutoff_date]


# ── Route Handlers ────────────────────────────────────────────────────────────


def handle_dashboard(event: dict[str, Any]) -> dict[str, Any]:
    """GET /dashboard — Serves single-page HTML application."""
    if not _DASHBOARD_HTML_PATH.exists():
        logger.error("Dashboard HTML template not found at %s", _DASHBOARD_HTML_PATH)
        return _json_response(500, {"error": "Dashboard template missing on server."})

    try:
        html = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        return _html_response(200, html)
    except Exception as exc:
        logger.exception("Failed to load dashboard HTML: %s", exc)
        return _json_response(500, {"error": "Failed to read dashboard template."})


def handle_api_fires(event: dict[str, Any], db: DatabaseClient | None = None) -> dict[str, Any]:
    """GET /api/fires?days=7 — Aggregated hotspots by 0.1-degree grid cell."""
    days = _parse_days(event, default=7)
    database = db or get_db()
    hotspots = _get_hotspots_in_window(database, days)

    clusters: dict[str, list[Any]] = defaultdict(list)
    for h in hotspots:
        cell_id = get_grid_cell_id(h.lat, h.lon, grid_size=0.1)
        clusters[cell_id].append(h)

    cells = []
    for cell_id, items in clusters.items():
        count = len(items)
        avg_lat = round(sum(i.lat for i in items) / count, 4)
        avg_lon = round(sum(i.lon for i in items) / count, 4)
        max_frp = round(max(i.frp for i in items), 2)
        total_frp = round(sum(i.frp for i in items), 2)
        cells.append({
            "grid_cell": cell_id,
            "lat": avg_lat,
            "lon": avg_lon,
            "fire_count": count,
            "max_frp": max_frp,
            "total_frp": total_frp,
        })

    # Sort descending by fire count
    cells.sort(key=lambda c: (-c["fire_count"], -c["total_frp"]))
    return _json_response(200, {
        "window_days": days,
        "total_hotspots": len(hotspots),
        "cell_count": len(cells),
        "cells": cells,
    })


def handle_api_gaps(event: dict[str, Any], db: DatabaseClient | None = None) -> dict[str, Any]:
    """GET /api/gaps?days=7 — Coverage gap analysis using engine compute_gap()."""
    days = _parse_days(event, default=7)
    database = db or get_db()
    hotspots = _get_hotspots_in_window(database, days)
    machines = database.list_bookable_machines()

    # Reuse engine compute_gap deterministically
    gap_records = compute_gap(hotspots, machines, grid_size=0.1, radius_km=15.0)

    # Machine district mapping for reporting
    machine_district_map = {m.machine_id: m.district for m in machines}

    gaps = []
    for g in gap_records:
        gaps.append({
            "grid_cell": g.grid_cell,
            "lat": g.lat,
            "lon": g.lon,
            "fire_count": g.fire_count,
            "total_frp": g.total_frp,
            "max_frp": g.max_frp,
            "nearest_machine_id": g.nearest_machine_id,
            "nearest_machine_distance_km": g.nearest_machine_distance_km,
            "nearest_machine_district": machine_district_map.get(g.nearest_machine_id or ""),
            "is_gap": g.is_gap,
        })

    flagged_count = sum(1 for g in gaps if g["is_gap"])
    return _json_response(200, {
        "window_days": days,
        "total_cells": len(gaps),
        "flagged_gaps": flagged_count,
        "gaps": gaps,
    })


def handle_api_machines(event: dict[str, Any], db: DatabaseClient | None = None) -> dict[str, Any]:
    """GET /api/machines — Sanitized public machinery listings (NO PII, NO RATES)."""
    database = db or get_db()
    machines = database.list_bookable_machines()
    providers = {p.provider_id: p for p in database.list_providers()}

    public_machines = []
    for m in machines:
        provider = providers.get(m.provider_id or "")
        is_directory = bool(
            (provider and provider.is_directory_listing)
            or m.source in ("SEED", "CHC_PORTAL", "DIRECTORY")
            or not m.provider_id
        )

        machine_type_str = (
            m.machine_type.value
            if hasattr(m.machine_type, "value")
            else str(m.machine_type)
        )

        public_machines.append({
            "machine_id": m.machine_id,
            "machine_type": machine_type_str,
            "village": m.village,
            "district": m.district,
            "lat": m.lat,
            "lon": m.lon,
            "is_directory_listing": is_directory,
            "is_synthetic": m.is_synthetic,
        })

    return _json_response(200, {
        "total_machines": len(public_machines),
        "machines": public_machines,
    })


def handle_api_summary(event: dict[str, Any], db: DatabaseClient | None = None) -> dict[str, Any]:
    """GET /api/summary — High level officer statistics, 7-day sparkline, and top underserved areas."""
    days = _parse_days(event, default=7)
    database = db or get_db()
    hotspots = _get_hotspots_in_window(database, days)
    machines = database.list_bookable_machines()
    buyers = database.list_bookable_buyers()
    all_bookings = database.list_all_bookings()

    # 1. 7-day daily counts for sparkline
    today = datetime.now(timezone.utc).date()
    day_counts: dict[date, int] = defaultdict(int)
    for h in hotspots:
        day_counts[h.acq_date] += 1

    daily_series = []
    for offset in range(6, -1, -1):
        d = today - timedelta(days=offset)
        daily_series.append({
            "date": d.isoformat(),
            "count": day_counts.get(d, 0),
        })

    # 2. Coverage gaps
    gap_records = compute_gap(hotspots, machines, grid_size=0.1, radius_km=15.0)
    machine_district_map = {m.machine_id: m.district for m in machines}
    flagged_cells = sum(1 for g in gap_records if g.is_gap)

    # Top 5 underserved areas (prioritize is_gap=True, then highest fire_count)
    top_underserved = []
    for g in gap_records[:5]:
        top_underserved.append({
            "grid_cell": g.grid_cell,
            "lat": g.lat,
            "lon": g.lon,
            "fire_count": g.fire_count,
            "nearest_machine_distance_km": g.nearest_machine_distance_km,
            "nearest_machine_district": machine_district_map.get(g.nearest_machine_id or ""),
            "is_gap": g.is_gap,
        })

    # 3. Bookings and estimated tonnes
    confirmed_bookings = [b for b in all_bookings if b.status == BookingStatus.CONFIRMED]
    completed_bookings = [b for b in all_bookings if b.status == BookingStatus.COMPLETED]
    total_handled_acres = sum(b.acres for b in confirmed_bookings) + sum(b.acres for b in completed_bookings)

    constants = get_constants()
    tonnes_per_acre = constants.residue_tonnes_per_acre
    estimated_tonnes = round(total_handled_acres * tonnes_per_acre, 2)

    return _json_response(200, {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "total_hotspots": len(hotspots),
        "daily_counts": daily_series,
        "flagged_cells": flagged_cells,
        "total_gap_cells": len(gap_records),
        "verified_machines": len(machines),
        "verified_buyers": len(buyers),
        "bookings": {
            "confirmed": len(confirmed_bookings),
            "completed": len(completed_bookings),
            "total_active_or_done": len(confirmed_bookings) + len(completed_bookings),
        },
        "estimated_residue_tonnes_handled": estimated_tonnes,
        "residue_tonnes_label": "estimated",
        "tonnes_per_acre_rate": tonnes_per_acre,
        "top_underserved_areas": top_underserved,
    })


# ── Lambda Entry Point ────────────────────────────────────────────────────────


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """AWS Lambda entry point for HTTP API (payload v2)."""
    raw_path = event.get("rawPath") or ""
    route_key = event.get("routeKey") or ""

    # Normalize method and path
    if " " in route_key:
        method, path = route_key.split(" ", 1)
    else:
        http_ctx = (event.get("requestContext") or {}).get("http") or {}
        method = http_ctx.get("method", "GET")
        path = raw_path or http_ctx.get("path", "/")

    if method == "OPTIONS":
        return _json_response(200, {"ok": True}, cache_ttl=0)

    if method != "GET":
        return _json_response(405, {"error": "Method Not Allowed"}, cache_ttl=0)

    # 1. Authorization check
    if not _verify_token(event):
        logger.warning("Unauthorized dashboard request to %s", path)
        return _json_response(401, {"error": "Unauthorized. Invalid or missing token."}, cache_ttl=0)

    # 2. Check in-memory container cache
    query_str = event.get("rawQueryString", "")
    cache_key = f"{path}?{query_str}"
    now = time.time()

    if cache_key in _CACHE:
        cached_time, cached_body, content_type = _CACHE[cache_key]
        if now - cached_time < _CACHE_TTL_SECONDS:
            headers = {
                "Content-Type": content_type,
                "Cache-Control": f"public, max-age={int(_CACHE_TTL_SECONDS - (now - cached_time))}",
                "Access-Control-Allow-Origin": "*",
                "X-Cache": "HIT",
            }
            return {
                "statusCode": 200,
                "headers": headers,
                "body": cached_body,
            }

    # 3. Route dispatch
    response: dict[str, Any]
    if path == "/dashboard":
        response = handle_dashboard(event)
    elif path == "/api/fires":
        response = handle_api_fires(event)
    elif path == "/api/gaps":
        response = handle_api_gaps(event)
    elif path == "/api/machines":
        response = handle_api_machines(event)
    elif path == "/api/summary":
        response = handle_api_summary(event)
    else:
        return _json_response(404, {"error": f"Route {path} not found."}, cache_ttl=0)

    # 4. Update in-memory container cache on 200 OK
    if response.get("statusCode") == 200 and path != "/dashboard":
        ct = response.get("headers", {}).get("Content-Type", "application/json")
        _CACHE[cache_key] = (now, response.get("body", ""), ct)

    return response
