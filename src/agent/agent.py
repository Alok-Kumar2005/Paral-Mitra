"""Parali Mitra conversational agent orchestration using Strands Agents SDK."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv
from strands import Agent
from strands.models.model import Model

from src.agent.memory import load_session_history, save_session_history
from src.agent.prompt import SYSTEM_PROMPT
from src.agent.tools import (
    _ensure_db_seeded,
    create_booking_request,
    find_residue_options,
    get_agricultural_constants,
    nearby_fire_activity,
    save_farmer_details,
)
from src.common.db import DatabaseClient, get_db
from src.common.models import FarmerSession, OptionType
from src.connectors.geocode import Geocoder
from src.connectors.weather import WeatherClient
from src.engine.recommender import rank_options

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_BEDROCK_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# ── Failure detection patterns (model returns apology/error instead of answer) ──

_FAILURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"temporary.*technical.*issue", re.IGNORECASE),
    re.compile(r"temporary.*system.*delay", re.IGNORECASE),
    re.compile(r"experiencing.*issue", re.IGNORECASE),
    re.compile(r"experiencing.*delay", re.IGNORECASE),
    re.compile(r"experiencing.*problem", re.IGNORECASE),
    re.compile(r"try again.*(?:moment|later|few)", re.IGNORECASE),
    re.compile(r"i(?:'m| am) sorry.*unable", re.IGNORECASE),
    re.compile(r"cannot.*connect.*system", re.IGNORECASE),
    re.compile(r"service.*unavailable", re.IGNORECASE),
    re.compile(r"system.*back.*online", re.IGNORECASE),
    re.compile(r"bear with me", re.IGNORECASE),
    re.compile(r"system.*delay", re.IGNORECASE),
    re.compile(r"patience.*moment", re.IGNORECASE),
    re.compile(r"technical.*difficult", re.IGNORECASE),
]

# ── Indicators that message contains parseable farm details (fast-path eligible) ──

_DETAIL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\d+(?:\.\d+)?\s*acres?", re.IGNORECASE),
    re.compile(r"\d+\s*days?", re.IGNORECASE),
    re.compile(r"village\s+\w+", re.IGNORECASE),
    re.compile(r"district\s+\w+", re.IGNORECASE),
    re.compile(r"\bin\s+[a-zA-Z]{3,}", re.IGNORECASE),
    re.compile(r"\bnear\s+[a-zA-Z]{3,}", re.IGNORECASE),
    re.compile(r"[a-zA-Z]{3,}\s*,\s*[a-zA-Z]{3,}", re.IGNORECASE),
    re.compile(r"sowing", re.IGNORECASE),
    re.compile(r"wheat", re.IGNORECASE),
    re.compile(r"latitude", re.IGNORECASE),
    re.compile(r"gps\s+coord", re.IGNORECASE),
    re.compile(r"sell\s*(?:paddy\s*)?straw", re.IGNORECASE),
    re.compile(r"ex-?situ", re.IGNORECASE),
    re.compile(r"cbg|biomass|buyer|pellet", re.IGNORECASE),
]

# ── Ex-situ / straw selling intent patterns ──

_EX_SITU_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bsell\b", re.IGNORECASE),
    re.compile(r"\bex-?situ\b", re.IGNORECASE),
    re.compile(r"\bcbg\b", re.IGNORECASE),
    re.compile(r"\bbiomass\b", re.IGNORECASE),
    re.compile(r"\bbuyer", re.IGNORECASE),
    re.compile(r"\bpellet\b", re.IGNORECASE),
    re.compile(r"\boff-?take\b", re.IGNORECASE),
    re.compile(r"\bcommercial\b", re.IGNORECASE),
    re.compile(r"\bbale\b", re.IGNORECASE),
    re.compile(r"\bbaling\b", re.IGNORECASE),
    re.compile(r"\bpower\s+plant\b", re.IGNORECASE),
    re.compile(r"बेचना", re.IGNORECASE),
    re.compile(r"बिक्री", re.IGNORECASE),
    re.compile(r"विक्रय", re.IGNORECASE),
    re.compile(r"ਵਿਕਰੀ", re.IGNORECASE),
    re.compile(r"ਵੇਚ", re.IGNORECASE),
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _is_ex_situ_intent(text: str) -> bool:
    """Returns True if the message expresses intent to sell straw or explore ex-situ commercial buyers."""
    return any(p.search(text) for p in _EX_SITU_PATTERNS)


def _contains_farmer_details(text: str) -> bool:
    """Returns True when the message appears to be providing farm details."""
    matches = sum(1 for p in _DETAIL_PATTERNS if p.search(text))
    return matches >= 1


def _is_failure_response(text: str) -> bool:
    """Returns True if the LLM response looks like a failure/apology."""
    if not text or len(text.strip()) < 10:
        return True
    return any(p.search(text) for p in _FAILURE_PATTERNS)


def _extract_location_text(text: str) -> str | None:
    """Extracts village, town, or district text from user message."""
    # 1. "village <V>, district <D>" or "village <V>, <D>"
    m1 = re.search(
        r"village\s+([a-zA-Z\s]+?)(?:,\s*|\s+district\s+|\s+dist\s+)([a-zA-Z\s]+?)(?:\n|$|\.|\d|\b(?:wheat|sow|days?|acres?|paddy|in|for)\b)",
        text,
        re.IGNORECASE,
    )
    if m1:
        v = m1.group(1).strip()
        d = m1.group(2).strip()
        if len(v) >= 2 and len(d) >= 2:
            return f"{v}, {d}"

    # 2. "village <V>"
    m1b = re.search(
        r"village\s+([a-zA-Z\s]+?)(?:\n|$|\.|\d|\b(?:wheat|sow|days?|acres?|paddy|district)\b)",
        text,
        re.IGNORECASE,
    )
    if m1b:
        v = m1b.group(1).strip()
        if len(v) >= 3 and not re.match(r"^(acres?|days?|sowing|wheat|straw)$", v, re.IGNORECASE):
            return v

    # 3. "district <D>"
    m2 = re.search(
        r"district\s+([a-zA-Z\s]+?)(?:\n|$|\.|\d|\b(?:wheat|sow|days?|acres?)\b)",
        text,
        re.IGNORECASE,
    )
    if m2:
        d = m2.group(1).strip()
        if len(d) >= 3 and not re.match(r"^(acres?|days?|sowing|wheat|straw)$", d, re.IGNORECASE):
            return f"District {d}"

    # 4. "in <Loc>, <Dist>" or "near <Loc>, <Dist>" or "at <Loc>, <Dist>"
    m3 = re.search(
        r"\b(?:in|near|at)\s+([a-zA-Z\s]+?)(?:,\s*|\s+district\s+|\s+dist\s+)([a-zA-Z\s]+?)(?:\n|$|\.|\d|\b(?:wheat|sow|days?|acres?)\b)",
        text,
        re.IGNORECASE,
    )
    if m3:
        v = m3.group(1).strip()
        d = m3.group(2).strip()
        if len(v) >= 2 and len(d) >= 2:
            return f"{v}, {d}"

    # 5. "in <Loc>" (e.g. "15 acres in Samrala", "in Patiala", "near Raikot")
    m4 = re.search(
        r"\b(?:in|near|at)\s+([a-zA-Z\s]{3,30}?)(?:\n|$|\.|\d|\b(?:wheat|sow|days?|acres?|straw)\b)",
        text,
        re.IGNORECASE,
    )
    if m4:
        v = m4.group(1).strip()
        if not re.match(r"^(acres?|days?|sowing|wheat|straw|paddy|punjab|haryana)$", v, re.IGNORECASE):
            return v

    # 6. "<Town/Village>, <District>" format (e.g. "Samrala, Ludhiana" or "Kaind, Ludhiana")
    m5 = re.search(r"\b([a-zA-Z]{3,25})\s*,\s*([a-zA-Z]{3,25})\b", text)
    if m5:
        w1, w2 = m5.group(1).strip(), m5.group(2).strip()
        stopwords = {"acres", "days", "wheat", "sowing", "paddy", "straw", "parali", "mitra"}
        if w1.lower() not in stopwords and w2.lower() not in stopwords:
            return f"{w1}, {w2}"

    return None


def _format_missing_fields(session: FarmerSession) -> str:
    """Returns a friendly Telegram prompt listing which session fields are still needed."""
    missing: list[str] = []
    if session.acres is None:
        missing.append("• 🌾 Farm size in *acres* (e.g. '8 acres')")
    if session.lat is None or session.lon is None:
        missing.append("• 📍 *Village & District* name, or tap the button to share GPS pin")
    if session.sowing_deadline is None:
        missing.append("• 📅 *Wheat sowing deadline* (e.g. '12 days' or '2026-11-10')")
    if not missing:
        return ""
    return (
        "🌾 *Parali Mitra*\n\n"
        "To get your personalised residue management plan, please share:\n\n"
        + "\n".join(missing)
    )


def _format_ranking_response(
    ranking: Any,
    session: FarmerSession,
    is_ex_situ_only: bool = False,
) -> str:
    """Formats a RankingResult into a Telegram-ready message string."""
    feasible = list(ranking.feasible)
    deadline_str = session.sowing_deadline.isoformat() if session.sowing_deadline else "N/A"
    location_str = (
        session.village_text
        or (f"{session.lat:.2f}°N, {session.lon:.2f}°E" if session.lat else "Unknown")
    )

    # If farmer specifically asked for ex-situ/selling straw, sort ex-situ options to the top
    if is_ex_situ_only:
        ex_situ_opts = [
            opt for opt in feasible
            if (hasattr(opt.option_type, "value") and opt.option_type.value == OptionType.EX_SITU.value)
            or opt.option_type == OptionType.EX_SITU
            or "EX_SITU" in str(opt.category).upper()
        ]
        if ex_situ_opts:
            feasible = ex_situ_opts
        else:
            # Inform farmer that no commercial buyer was within range, showing in-situ alternatives
            lines_no_buyer = [
                "🌾 *Parali Mitra — Commercial Straw Buyers*",
                f"📊 *Farm:* {session.acres} acres | 📍 _{location_str}_",
                "",
                "⚠️ *No commercial buyers (CBG/Power Plants) found within 50 km of your location.*",
                "Here are the top in-situ machinery options to clear your field before sowing:\n",
            ]
            for i, opt in enumerate(feasible[:3], start=1):
                net = opt.net_cost
                cost_str = (
                    f"💰 *Earns ₹{abs(int(net)):,}* (profit / subsidy)"
                    if net < 0
                    else f"💵 *Costs ₹{int(net):,}* net"
                )
                category = opt.category.replace("_", " ").title()
                lines_no_buyer += [
                    f"🚜 *Option {i}: {category} — {opt.target_name}*",
                    f"  {cost_str}",
                    f"  📍 {opt.distance_km:.1f} km | 📅 Start: {opt.earliest_date} ({opt.slack_days}d slack)",
                    "",
                ]
            lines_no_buyer.append("👇 *Tap a numbered option below to book, or ask me anything!*")
            return "\n".join(lines_no_buyer)

    if not feasible:
        reasons = "\n".join(
            f"  • {inf.infeasible_reasons[0]}"
            for inf in ranking.infeasible[:3]
            if inf.infeasible_reasons
        )
        return (
            "🌾 *Parali Mitra*\n\n"
            f"⚠️ No feasible options found for *{session.acres} acres* near _{location_str}_"
            f" within your *{deadline_str}* sowing deadline.\n\n"
            + (f"*Reasons:*\n{reasons}\n\n" if reasons else "")
            + "Please contact your local CHC or try sharing your GPS pin for better accuracy."
        )

    title = (
        "🌾 *Parali Mitra — Commercial Straw Buyers & Ex-Situ Off-take*"
        if is_ex_situ_only
        else f"🌾 *Parali Mitra — Top {min(3, len(feasible))} Residue Options*"
    )

    lines: list[str] = [
        title,
        f"📊 *Farm:* {session.acres} acres | 📍 _{location_str}_",
        f"📅 *Sow by:* {deadline_str} | {len(feasible)} feasible option(s) found",
        "",
    ]
    emojis = ["🥇", "🥈", "🥉"]
    for i, opt in enumerate(feasible[:3], start=1):
        net = opt.net_cost
        cost_str = (
            f"💰 *Earns ₹{abs(int(net)):,}* (profit / CRM subsidy)"
            if net < 0
            else f"💵 *Costs ₹{int(net):,}* net"
        )
        summary = opt.reasons[0] if opt.reasons else ""
        category = opt.category.replace("_", " ").title()
        lines += [
            f"{emojis[i - 1]} *Option {i}: {category} — {opt.target_name}*",
            f"  {cost_str}",
            f"  📍 {opt.distance_km:.1f} km | 📅 Start: {opt.earliest_date} ({opt.slack_days}d slack)",
            f"  ℹ️ {summary}" if summary else "",
            "",
        ]
    lines.append("👇 *Tap a numbered option below to book, or ask me anything!*")
    return "\n".join(line for line in lines if line is not None)


# ── Fast path: parse + save + run engine (no LLM) ────────────────────────────


async def _parse_and_save_details(
    chat_id: int,
    user_message: str,
    db: DatabaseClient,
) -> FarmerSession:
    """Extracts farm details from raw user message text and persists to session.

    Handles acreage, sowing deadline, GPS coordinates, and village+district geocoding.
    Uses the caller's db instance — avoids opening a second Neon connection.

    Args:
        chat_id: Telegram user/chat ID.
        user_message: Raw user message or router-synthesised GPS message.
        db: Active database client.

    Returns:
        Updated FarmerSession.
    """
    session = db.get_session(chat_id)
    if session is None:
        session = FarmerSession(chat_id=chat_id)

    updated = False

    # 1. Acreage
    acres_match = re.search(r"(\d+(?:\.\d+)?)\s*acres?", user_message, re.IGNORECASE)
    if acres_match:
        val = float(acres_match.group(1))
        if 0 < val <= 5000:
            session.acres = val
            updated = True
            logger.info("[FastPath] Acreage updated: %.1f acres for chat_id=%d", val, chat_id)

    # 2. Sowing deadline
    days_match = re.search(r"(?:in\s+)?(\d+)\s*days?", user_message, re.IGNORECASE)
    if days_match:
        days = int(days_match.group(1))
        if 1 <= days <= 120:
            session.sowing_deadline = date.today() + timedelta(days=days)
            updated = True
            logger.info("[FastPath] Sowing deadline set to %s (%d days) for chat_id=%d", session.sowing_deadline, days, chat_id)
    else:
        # Check explicit ISO date YYYY-MM-DD
        iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", user_message)
        if iso_match:
            try:
                parsed_d = date.fromisoformat(iso_match.group(1))
                if parsed_d >= date.today():
                    session.sowing_deadline = parsed_d
                    updated = True
            except ValueError:
                pass

    # 3. GPS embedded in message (router-synthesised: "Latitude 30.20 Longitude 74.94")
    gps_match = re.search(
        r"(?:latitude|lat)[:\s]+(\d{1,3}\.\d+).*?(?:longitude|lon(?:gitude)?)[:\s]+(\d{1,3}\.\d+)",
        user_message,
        re.IGNORECASE | re.DOTALL,
    )
    if gps_match:
        lat, lon = float(gps_match.group(1)), float(gps_match.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            session.lat, session.lon = lat, lon
            updated = True
            logger.info("[FastPath] GPS from message: (%.6f, %.6f) for chat_id=%d", lat, lon, chat_id)

    # 4. Village + district location extraction and geocoding
    # Geocode whenever location text is found, dynamically updating previous location slots
    loc_text = _extract_location_text(user_message)
    if loc_text:
        logger.info("[FastPath] Extracted location text '%s' for chat_id=%d", loc_text, chat_id)
        session.village_text = loc_text
        updated = True
        try:
            geo_res = await Geocoder().geocode(loc_text)
            if geo_res:
                session.lat, session.lon = geo_res.lat, geo_res.lon
                session.village_text = geo_res.display_name
                logger.info(
                    "[FastPath] Geocoded '%s' -> (%.4f, %.4f)",
                    loc_text, session.lat, session.lon,
                )
        except Exception as exc:
            logger.warning("[FastPath] Geocoding failed for '%s': %s", loc_text, exc)

    if updated:
        session.updated_at = datetime.now()
        db.put_session(session)

    return session


async def _run_engine_and_format(
    chat_id: int,
    session: FarmerSession,
    db: DatabaseClient,
    is_ex_situ_only: bool = False,
) -> str:
    """Runs the deterministic ranking engine with the caller's db client and formats the response.

    Avoids opening a second Neon cold-start connection by using the provided db instance.

    Args:
        chat_id: Telegram user/chat ID.
        session: Complete FarmerSession (acres, lat, lon, sowing_deadline all populated).
        db: Active database client.
        is_ex_situ_only: If True, prioritizes commercial buyers and ex-situ off-take.

    Returns:
        Formatted Telegram message string.
    """
    _ensure_db_seeded(db)

    weather_forecast = None
    try:
        weather_forecast = await WeatherClient().fetch_forecast(
            lat=session.lat, lon=session.lon, forecast_days=10
        )
    except Exception as exc:
        logger.warning("[Engine] Weather fetch failed (%.4f, %.4f): %s", session.lat, session.lon, exc)

    machines = db.list_machines()
    buyers = db.list_buyers()
    constants = get_agricultural_constants()

    logger.info(
        "[Engine] Ranking for chat_id=%d: %.1f acres, deadline=%s, %d machines, %d buyers (ex_situ=%s)",
        chat_id, session.acres, session.sowing_deadline, len(machines), len(buyers), is_ex_situ_only,
    )

    ranking = rank_options(
        farmer=session,
        machines=machines,
        buyers=buyers,
        constants=constants,
        weather=weather_forecast,
        today=date.today(),
    )

    # If ex-situ was specifically requested, reorder feasible options to place ex-situ first
    feasible_list = list(ranking.feasible)
    if is_ex_situ_only:
        ex_situ_opts = [
            opt for opt in feasible_list
            if (hasattr(opt.option_type, "value") and opt.option_type.value == OptionType.EX_SITU.value)
            or opt.option_type == OptionType.EX_SITU
            or "EX_SITU" in str(opt.category).upper()
        ]
        other_opts = [opt for opt in feasible_list if opt not in ex_situ_opts]
        feasible_list = ex_situ_opts + other_opts

    # Cache ranked results in session for the booking flow
    session.last_options = [opt.model_dump(mode="json") for opt in feasible_list]
    session.updated_at = datetime.now()
    db.put_session(session)

    return _format_ranking_response(ranking, session, is_ex_situ_only=is_ex_situ_only)


# ── Strands agent construction ────────────────────────────────────────────────


def get_agent_tools() -> list[Any]:
    """Returns the list of Strands @tool decorated functions for Parali Mitra."""
    return [
        save_farmer_details,
        find_residue_options,
        nearby_fire_activity,
        create_booking_request,
    ]


def get_default_model_id() -> str:
    """Resolves model ID from MODEL_ID environment variable or defaults to Bedrock Claude 3.5 Sonnet."""
    return os.getenv("MODEL_ID", DEFAULT_BEDROCK_MODEL_ID).strip()


def build_agent_system_prompt(chat_id: int, session: FarmerSession | None = None) -> str:
    """Builds a dynamic system prompt injecting the farmer's known session profile."""
    profile_lines = [f"- Farmer Chat ID: {chat_id}"]
    if session:
        profile_lines.append(f"- Preferred Language: {session.language or 'hi'}")
        if session.acres is not None:
            profile_lines.append(f"- Saved Acreage: {session.acres} acres")
        if session.village_text or (session.lat and session.lon):
            loc_str = session.village_text or ""
            if session.lat and session.lon:
                loc_str += f" ({session.lat:.4f}, {session.lon:.4f})"
            profile_lines.append(f"- Saved Location: {loc_str}")
        if session.sowing_deadline is not None:
            profile_lines.append(f"- Saved Sowing Deadline: {session.sowing_deadline}")
        if session.last_options:
            profile_lines.append(f"- Evaluated Options: {len(session.last_options)} options in cache")

    profile_context = "\n".join(profile_lines)
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "# Current Farmer Profile & Session State\n"
        f"{profile_context}\n\n"
        "If the farmer's acreage, location, and sowing deadline are already saved above, "
        f"directly call find_residue_options(chat_id={chat_id}) to evaluate and display the top 3 ranked options "
        "with exact costs and distances without asking for already-saved details."
    )


def create_parali_agent(
    chat_id: int,
    model: str | Model | None = None,
    history: list[dict[str, Any]] | None = None,
    db: DatabaseClient | None = None,
) -> Agent:
    """Constructs a Strands Agent instance preloaded with the farmer's session history.

    Args:
        chat_id: Telegram user/chat ID.
        model: Model ID string or Strands Model instance (defaults to MODEL_ID env var).
        history: Optional preloaded message list (loaded from db if None).
        db: Database client instance.

    Returns:
        Configured Strands Agent instance.
    """
    resolved_model = model or get_default_model_id()
    client = db or get_db()
    session = client.get_session(chat_id)
    message_history = history if history is not None else load_session_history(chat_id=chat_id, db=client)
    system_prompt = build_agent_system_prompt(chat_id=chat_id, session=session)

    return Agent(
        model=resolved_model,
        system_prompt=system_prompt,
        tools=get_agent_tools(),
        messages=message_history,
        callback_handler=None,  # Clean non-streaming callback for serverless
    )


# ── Main agent turn (three-tier processing) ───────────────────────────────────


async def run_agent_turn(
    chat_id: int,
    user_message: str,
    model: str | Model | None = None,
    db: DatabaseClient | None = None,
) -> str:
    """Processes a single conversational turn for a farmer, persisting memory before and after.

    Three-tier processing:
    1. Fast path (no LLM): message has parseable farm details OR session is already complete.
       Parses/updates session, runs deterministic engine, returns formatted options.
    2. LLM path: conversational or ambiguous messages go to the Strands agent.
    3. LLM failure fallback: if LLM returns failure/apology, re-reads the (tool-updated)
       session and runs the engine directly using the passed db client.

    Args:
        chat_id: Telegram user/chat ID.
        user_message: Incoming farmer text message.
        model: Model ID string or custom Model instance.
        db: Database client instance.

    Returns:
        Assistant response text formatted for Telegram.
    """
    client = db or get_db()
    is_ex_situ = _is_ex_situ_intent(user_message)

    # ── TIER 1: FAST PATH (no LLM) ───────────────────────────────────────────
    try:
        session = await _parse_and_save_details(
            chat_id=chat_id, user_message=user_message, db=client
        )
        session_complete = (
            session.acres is not None
            and session.lat is not None
            and session.lon is not None
            and session.sowing_deadline is not None
        )
        if session_complete:
            logger.info(
                "[FastPath] Session complete for chat_id=%d — skipping LLM "
                "(acres=%.1f, lat=%.4f, lon=%.4f, deadline=%s, ex_situ=%s)",
                chat_id, session.acres, session.lat, session.lon, session.sowing_deadline, is_ex_situ,
            )
            return await _run_engine_and_format(
                chat_id=chat_id, session=session, db=client, is_ex_situ_only=is_ex_situ
            )

        # Session incomplete but message had detail keywords -> ask for missing fields
        if _contains_farmer_details(user_message):
            missing_msg = _format_missing_fields(session)
            if missing_msg:
                logger.info(
                    "[FastPath] Partial details for chat_id=%d — asking for missing fields", chat_id
                )
                return missing_msg

    except Exception as exc:
        logger.warning(
            "[FastPath] Error for chat_id=%d — falling through to LLM: %s", chat_id, exc
        )

    # ── TIER 2: LLM PATH ─────────────────────────────────────────────────────
    agent = create_parali_agent(chat_id=chat_id, model=model, db=client)

    logger.info(
        "[LLM] Invoking agent for chat_id=%d, model=%s", chat_id, model or get_default_model_id()
    )
    result = await agent.invoke_async(user_message)

    stop_reason = getattr(result, "stop_reason", "unknown")
    logger.info("[LLM] stop_reason=%s for chat_id=%d", stop_reason, chat_id)

    response_text = str(result).strip()

    # ── TIER 3: LLM FAILURE FALLBACK ─────────────────────────────────────────
    if _is_failure_response(response_text):
        logger.warning(
            "[Fallback] LLM failure for chat_id=%d (stop_reason=%s). Output: %.300s",
            chat_id, stop_reason, response_text,
        )
        # Re-read session — LLM may have called tools and populated fields before failing
        refreshed = client.get_session(chat_id)
        if (
            refreshed
            and refreshed.acres is not None
            and refreshed.lat is not None
            and refreshed.lon is not None
            and refreshed.sowing_deadline is not None
        ):
            try:
                response_text = await _run_engine_and_format(
                    chat_id=chat_id, session=refreshed, db=client, is_ex_situ_only=is_ex_situ
                )
            except Exception as eng_exc:
                logger.error("[Fallback] Engine also failed: %s", eng_exc)
                response_text = _format_missing_fields(refreshed) or (
                    "🌾 *Parali Mitra*\n\n"
                    "I'm having trouble connecting to our data services right now. "
                    "Please try again in a minute, or share your GPS pin using the button below."
                )
        else:
            fallback_session = refreshed or FarmerSession(chat_id=chat_id)
            response_text = _format_missing_fields(fallback_session) or (
                "🌾 *Parali Mitra*\n\n"
                "Please share your farm size (acres), village & district, and wheat sowing deadline "
                "to receive your personalised residue management plan."
            )

    # Persist updated conversation history
    save_session_history(chat_id=chat_id, messages=agent.messages, db=client)

    return response_text


def run_agent_turn_sync(
    chat_id: int,
    user_message: str,
    model: str | Model | None = None,
    db: DatabaseClient | None = None,
) -> str:
    """Synchronous convenience wrapper around run_agent_turn."""
    import asyncio
    return asyncio.run(run_agent_turn(chat_id=chat_id, user_message=user_message, model=model, db=db))