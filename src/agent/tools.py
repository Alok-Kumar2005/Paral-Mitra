"""Strands Agent Tools for Parali Mitra.

Provides deterministic tool implementations with @tool decorator for:
- save_farmer_details
- find_residue_options
- nearby_fire_activity
- create_booking_request
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import re
import time
from typing import Any

from strands import tool

from src.common.constants import AgriculturalConstants
from src.common.db import DatabaseClient, get_db
from src.common.models import Booking, BookingStatus, FarmerSession
from src.connectors.geocode import Geocoder
from src.connectors.weather import WeatherClient
from src.engine.geo import haversine_distance
from src.engine.recommender import rank_options

logger = logging.getLogger(__name__)

# Constants and Seed Paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = PROJECT_ROOT / "data" / "seed"
CONSTANTS_PATH = SEED_DIR / "constants.csv"

_constants_cache: AgriculturalConstants | None = None


def get_agricultural_constants() -> AgriculturalConstants:
    """Loads and caches agricultural constants from seed directory."""
    global _constants_cache
    if _constants_cache is None:
        if CONSTANTS_PATH.exists():
            _constants_cache = AgriculturalConstants.load_from_csv(CONSTANTS_PATH)
        else:
            raise FileNotFoundError(f"Constants CSV not found at {CONSTANTS_PATH}")
    return _constants_cache


def _ensure_db_seeded(db: DatabaseClient) -> None:
    """Ensures database has machinery and buyer registries populated."""
    try:
        if len(db.list_machines()) == 0 or len(db.list_buyers()) == 0:
            if SEED_DIR.exists():
                try:
                    from scripts.seed import seed_database
                    seed_database(seed_dir=SEED_DIR, db=db)
                except ImportError:
                    pass
    except Exception as exc:
        logger.warning("[DB] _ensure_db_seeded skipped: %s", exc)


def _parse_date_input(val: str | None) -> date | None:
    """Parses date string or relative day offset into a date object."""
    if not val or not str(val).strip():
        return None
    val_str = str(val).strip()

    # Relative days (e.g. "15 days", "+10", "12")
    rel_match = re.search(r"^\+?(\d+)\s*(days?)?$", val_str, re.IGNORECASE)
    if rel_match:
        days_ahead = int(rel_match.group(1))
        # If it's a small number like 1-90, treat as relative days
        if days_ahead <= 90:
            return date.today() + timedelta(days=days_ahead)

    # ISO YYYY-MM-DD
    try:
        return date.fromisoformat(val_str)
    except ValueError:
        pass

    # DD-MM-YYYY or DD/MM/YYYY
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            pass

    return None


@tool
async def save_farmer_details(
    chat_id: int,
    acres: float | None = None,
    sowing_deadline: str | None = None,
    village_text: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """Saves or updates the farmer profile (land size, sowing deadline, location coordinates or village name).

    Args:
        chat_id: Telegram user/chat ID of the farmer.
        acres: Land acreage to clear (e.g. 5.0, 10.5).
        sowing_deadline: Target date for wheat sowing in YYYY-MM-DD format or days remaining (e.g. '2026-11-10' or '15 days').
        village_text: Village and district name (e.g. 'Raikot, Ludhiana' or 'Nabha, Patiala').
        lat: Exact farm latitude from GPS/pin (-90 to 90).
        lon: Exact farm longitude from GPS/pin (-180 to 180).

    Returns:
        Compact status dictionary detailing saved fields and any remaining missing fields.
    """
    db = get_db()
    session = db.get_session(chat_id)
    if session is None:
        session = FarmerSession(chat_id=chat_id)

    # 1. Update Acres
    if acres is not None and acres > 0:
        session.acres = float(acres)

    # 2. Update Sowing Deadline
    if sowing_deadline is not None:
        parsed_d = _parse_date_input(sowing_deadline)
        if parsed_d:
            session.sowing_deadline = parsed_d

    # 3. Update Coordinates / Location
    if lat is not None and lon is not None:
        session.lat = float(lat)
        session.lon = float(lon)
        if village_text:
            session.village_text = village_text
    elif village_text is not None and village_text.strip():
        clean_village = village_text.strip()
        session.village_text = clean_village
        # Attempt async geocoding if lat/lon not set
        try:
            geocoder = Geocoder()
            geo_res = await geocoder.geocode(clean_village)
            if geo_res:
                session.lat = geo_res.lat
                session.lon = geo_res.lon
                session.village_text = geo_res.display_name
        except Exception as exc:
            logger.warning("Geocoding failed for %s: %s", clean_village, exc)

    session.updated_at = datetime.now()
    db.put_session(session)

    # Check remaining missing fields
    missing: list[str] = []
    if session.acres is None:
        missing.append("acres")
    if session.lat is None or session.lon is None:
        missing.append("location (village + district or GPS pin)")
    if session.sowing_deadline is None:
        missing.append("sowing deadline")

    return {
        "status": "saved",
        "chat_id": chat_id,
        "acres": session.acres,
        "village": session.village_text,
        "coordinates": f"({session.lat:.4f}, {session.lon:.4f})" if session.lat and session.lon else None,
        "sowing_deadline": session.sowing_deadline.isoformat() if session.sowing_deadline else None,
        "is_ready_for_options": len(missing) == 0,
        "missing_fields": missing,
    }


@tool
async def find_residue_options(chat_id: int) -> dict[str, Any]:
    """Deterministically evaluates and ranks in-situ machinery and ex-situ biomass off-take options for the farmer.

    Loads the farmer's session, fetches real-time Open-Meteo weather forecasts, loads verified CHC machinery
    and commercial buyers from the database, and runs the deterministic ranking engine.

    Args:
        chat_id: Telegram user/chat ID of the farmer.

    Returns:
        Structured dictionary containing at most 3 ranked feasible options with net cost/profit, distance,
        earliest start date, and clear operational summary.
    """
    db = get_db()
    _ensure_db_seeded(db)

    session = db.get_session(chat_id)
    if not session or session.acres is None or session.lat is None or session.lon is None or session.sowing_deadline is None:
        missing: list[str] = []
        if not session or session.acres is None:
            missing.append("farm acreage")
        if not session or session.lat is None or session.lon is None:
            missing.append("farm location / village")
        if not session or session.sowing_deadline is None:
            missing.append("target sowing deadline")
        return {
            "status": "missing_information",
            "message": f"Required farmer details missing: {', '.join(missing)}. Please ask the farmer for these details first.",
            "missing_fields": missing,
        }

    # Fetch weather forecast
    weather_forecast = None
    try:
        weather_client = WeatherClient()
        weather_forecast = await weather_client.fetch_forecast(lat=session.lat, lon=session.lon, forecast_days=10)
    except Exception as exc:
        logger.warning("Weather fetch failed for (%s, %s): %s", session.lat, session.lon, exc)

    # Load verified and active resources
    machines = db.list_bookable_machines(lat=session.lat, lon=session.lon, radius_km=50.0)
    buyers = db.list_bookable_buyers(lat=session.lat, lon=session.lon, radius_km=50.0)
    constants = get_agricultural_constants()

    # Deterministic Optimization
    today = date.today()
    ranking = rank_options(
        farmer=session,
        machines=machines,
        buyers=buyers,
        constants=constants,
        weather=weather_forecast,
        today=today,
    )

    # Cache evaluated options in session
    session.last_options = [opt.model_dump(mode="json") for opt in ranking.feasible]
    session.updated_at = datetime.now()
    db.put_session(session)

    # Prepare compact top 3 feasible options
    top_feasible = []
    for idx, opt in enumerate(ranking.feasible[:3], start=1):
        top_feasible.append({
            "option_index": idx,
            "type": str(opt.option_type.value if hasattr(opt.option_type, "value") else opt.option_type),
            "category": opt.category.replace("_", " ").title(),
            "target_name": opt.target_name,
            "location": opt.village,
            "distance_km": round(opt.distance_km, 1),
            "net_cost_inr": round(opt.net_cost, 0),
            "is_profit": opt.net_cost < 0,
            "earliest_date": opt.earliest_date.isoformat(),
            "completion_date": opt.completion_date.isoformat(),
            "slack_days": opt.slack_days,
            "summary": opt.reasons[0] if opt.reasons else "",
        })

    # Infeasible summary if no feasible options found
    infeasible_reasons = []
    if not top_feasible and ranking.infeasible:
        for inf in ranking.infeasible[:3]:
            if inf.infeasible_reasons:
                infeasible_reasons.append(f"{inf.target_name}: {inf.infeasible_reasons[0]}")

    return {
        "status": "success",
        "farmer_acres": session.acres,
        "sowing_deadline": session.sowing_deadline.isoformat(),
        "total_feasible": len(ranking.feasible),
        "options": top_feasible,
        "infeasible_reasons": infeasible_reasons,
    }


@tool
def list_nearby_machines(chat_id: int, radius_km: float = 50.0) -> dict[str, Any]:
    """Lists verified active agricultural machinery registered near the farmer's location.

    Args:
        chat_id: Telegram user/chat ID of the farmer.
        radius_km: Operational search radius in kilometers (default 50 km).

    Returns:
        List of available machinery with rates, service radius, provider name, and ratings.
    """
    from src.marketplace import services

    db = get_db()
    session = db.get_session(chat_id)
    lat = session.lat if session and session.lat is not None else 30.3753
    lon = session.lon if session and session.lon is not None else 76.1517

    views = services.list_nearby_machines(db, lat=lat, lon=lon, radius_km=radius_km)
    results = []
    for v in views[:10]:
        results.append({
            "machine_id": v.machine_id,
            "type": str(v.machine_type.value if hasattr(v.machine_type, "value") else v.machine_type),
            "provider_name": v.provider_name,
            "location": f"{v.village}, {v.district}",
            "distance_km": v.distance_km,
            "rate_per_acre_inr": v.rate_per_acre,
            "rating_avg": v.rating_avg,
            "rating_count": v.rating_count,
        })
    return {
        "status": "success",
        "count": len(results),
        "machines": results,
    }


@tool
def nearby_fire_activity(chat_id: int, radius_km: float = 25.0) -> dict[str, Any]:
    """Checks for active satellite fire detections (FIRMS hotspots) within a given radius of the farmer's location.

    Args:
        chat_id: Telegram user/chat ID of the farmer.
        radius_km: Search radius in kilometers (default 25.0 km).

    Returns:
        Compact summary of active hotspot detections nearby.
    """
    db = get_db()
    session = db.get_session(chat_id)
    if not session or session.lat is None or session.lon is None:
        return {
            "status": "missing_location",
            "message": "Farmer location is required to check nearby active fire events.",
        }

    hotspots = db.list_hotspots()
    nearby = []
    for h in hotspots:
        dist = haversine_distance(session.lat, session.lon, h.lat, h.lon)
        if dist <= radius_km:
            nearby.append(h)

    total_frp = sum(h.frp for h in nearby)
    return {
        "status": "success",
        "radius_km": radius_km,
        "active_hotspot_count": len(nearby),
        "total_frp_mw": round(total_frp, 1),
        "summary": f"{len(nearby)} active satellite fire detections found within {radius_km:.0f} km.",
    }


@tool
def create_booking_request(chat_id: int, option_index: int) -> dict[str, Any]:
    """Creates a PENDING booking request for the specified residue management option index.

    MUST ONLY be called after the farmer explicitly confirms their choice.

    Args:
        chat_id: Telegram user/chat ID of the farmer.
        option_index: Selected option number from find_residue_options (1, 2, or 3).

    Returns:
        Booking confirmation details including canonical booking_id (BK-XXXXXXXX) and status.
    """
    from src.marketplace import services

    db = get_db()
    session = db.get_session(chat_id)
    if not session or not session.last_options:
        return {
            "status": "error",
            "message": "No evaluated options found. Please search for options with find_residue_options first.",
        }

    # Normalize index: 1-indexed (1, 2, 3) or 0-indexed (0, 1, 2)
    idx = option_index - 1 if option_index >= 1 else option_index
    if idx < 0 or idx >= len(session.last_options):
        return {
            "status": "error",
            "message": f"Invalid option index {option_index}. Available options: 1 to {len(session.last_options)}.",
        }

    chosen = session.last_options[idx]
    target_id = chosen.get("target_id") or chosen.get("machine_id") or chosen.get("buyer_id") or f"TGT_{idx}"
    opt_type = chosen.get("option_type", "IN_SITU")
    req_date = date.fromisoformat(chosen["earliest_date"]) if "earliest_date" in chosen else date.today()
    acres = session.acres or 10.0

    try:
        booking, _ = services.create_booking(
            db=db,
            farmer_chat_id=chat_id,
            target_id=target_id,
            acres=acres,
            requested_date=req_date,
            option_type=opt_type,
        )
        return {
            "status": "PENDING",
            "booking_id": booking.booking_id,
            "target_name": chosen.get("target_name"),
            "acres": booking.acres,
            "requested_date": booking.requested_date.isoformat(),
            "estimated_net_cost_inr": chosen.get("net_cost"),
            "message": f"Booking #{booking.booking_id} created in PENDING status. Operator notified for confirmation.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Failed to create booking: {exc}",
        }
