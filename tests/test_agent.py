"""Unit tests for Parali Mitra Strands Agent layer.

All tests run fully offline (DB_MODE=local, no live Bedrock calls).
The create_parali_agent() test monkeypatches strands.Agent to avoid
AWS Bedrock client initialization.
"""

from datetime import date, timedelta
import pytest

from src.agent import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    clear_session_history,
    create_booking_request,
    create_parali_agent,
    find_residue_options,
    load_session_history,
    nearby_fire_activity,
    save_farmer_details,
    save_session_history,
)
from src.common.db import get_db_client
from src.common.models import BookingStatus, FarmerSession, Hotspot


@pytest.fixture(autouse=True)
def clean_database():
    """Cleans in-memory database before each test."""
    db = get_db_client("local")
    db.clear_all()
    yield db


# ── save_farmer_details ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_farmer_details_success(clean_database):
    chat_id = 11111
    res = await save_farmer_details(
        chat_id=chat_id,
        acres=8.5,
        sowing_deadline="2026-11-20",
        lat=30.3150,
        lon=76.4120,
        village_text="Rauni Farm, Patiala",
    )
    assert res["status"] == "saved"
    assert res["acres"] == 8.5
    assert res["sowing_deadline"] == "2026-11-20"
    assert res["is_ready_for_options"] is True
    assert len(res["missing_fields"]) == 0

    session = clean_database.get_session(chat_id)
    assert session is not None
    assert session.acres == 8.5
    assert session.sowing_deadline == date(2026, 11, 20)
    assert session.lat == 30.3150
    assert session.lon == 76.4120


@pytest.mark.asyncio
async def test_save_farmer_details_relative_days(clean_database):
    chat_id = 22222
    res = await save_farmer_details(
        chat_id=chat_id,
        acres=5.0,
        sowing_deadline="15 days",
        lat=30.3,
        lon=76.4,
    )
    assert res["status"] == "saved"
    expected_date = (date.today() + timedelta(days=15)).isoformat()
    assert res["sowing_deadline"] == expected_date


# ── find_residue_options ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_residue_options_missing_details(clean_database):
    chat_id = 33333
    res = await find_residue_options(chat_id=chat_id)
    assert res["status"] == "missing_information"
    assert "missing_fields" in res
    assert "farm acreage" in res["missing_fields"]


@pytest.mark.asyncio
async def test_find_residue_options_and_booking_flow(clean_database):
    chat_id = 44444
    # 1. Save valid farmer details near KVK Patiala CHC
    await save_farmer_details(
        chat_id=chat_id,
        acres=6.0,
        sowing_deadline="2026-11-25",
        lat=30.3150,
        lon=76.4120,
        village_text="Rauni Farm, Patiala",
    )

    # 2. Evaluate residue options
    opt_res = await find_residue_options(chat_id=chat_id)
    assert opt_res["status"] == "success"
    assert opt_res["total_feasible"] >= 1
    assert len(opt_res["options"]) >= 1

    top_opt = opt_res["options"][0]
    assert top_opt["option_index"] == 1
    assert top_opt["net_cost_inr"] is not None
    assert top_opt["earliest_date"] is not None
    assert top_opt["distance_km"] >= 0.0

    # Verify session cached last_options
    session = clean_database.get_session(chat_id)
    assert session.last_options is not None
    assert len(session.last_options) >= 1

    # 3. Create booking request for option 1
    bkg_res = create_booking_request(chat_id=chat_id, option_index=1)
    assert bkg_res["status"] == "CONFIRMED_PENDING"
    assert bkg_res["booking_id"].startswith("BKG_")
    assert bkg_res["acres"] == 6.0

    # Verify booking in database
    booking = clean_database.get_booking(bkg_res["booking_id"])
    assert booking is not None
    assert booking.status == BookingStatus.PENDING
    assert booking.farmer_chat_id == chat_id


# ── create_booking_request error paths ───────────────────────────────────────


def test_create_booking_request_invalid_index(clean_database):
    chat_id = 55555
    res = create_booking_request(chat_id=chat_id, option_index=1)
    assert res["status"] == "error"
    assert "No evaluated options found" in res["message"]


# ── nearby_fire_activity ──────────────────────────────────────────────────────


def test_nearby_fire_activity(clean_database):
    chat_id = 66666
    session = FarmerSession(chat_id=chat_id, lat=30.3000, lon=76.4000)
    clean_database.put_session(session)

    from datetime import datetime, timedelta, timezone
    expires = datetime.now(timezone.utc) + timedelta(days=1)
    h1 = Hotspot(
        grid_cell="CELL_1",
        lat=30.3100,
        lon=76.4100,
        acq_date=date.today(),
        frp=25.0,
        confidence="high",
        expires_at=expires,
    )
    h2 = Hotspot(
        grid_cell="CELL_2",
        lat=28.5000,
        lon=77.2000,
        acq_date=date.today(),
        frp=50.0,
        confidence="nominal",
        expires_at=expires,
    )
    clean_database.put_hotspots([h1, h2])

    res = nearby_fire_activity(chat_id=chat_id, radius_km=20.0)
    assert res["status"] == "success"
    assert res["active_hotspot_count"] == 1
    assert res["total_frp_mw"] == 25.0


# ── Memory / session history shim ────────────────────────────────────────────


def test_memory_session_history(clean_database):
    chat_id = 77777
    hist = load_session_history(chat_id=chat_id)
    assert hist == []

    turns = [
        {"role": "user", "content": [{"text": "Hello"}]},
        {"role": "assistant", "content": [{"text": "Sat Sri Akal! How can I help you today?"}]},
    ]
    save_session_history(chat_id=chat_id, messages=turns)

    loaded = load_session_history(chat_id=chat_id)
    assert len(loaded) == 2
    assert loaded[0]["content"][0]["text"] == "Hello"

    clear_session_history(chat_id=chat_id)
    assert load_session_history(chat_id=chat_id) == []


# ── Prompt integrity ──────────────────────────────────────────────────────────


def test_system_prompt_integrity():
    assert PROMPT_VERSION == "1.0.0"
    assert "Parali Mitra" in SYSTEM_PROMPT
    assert "STRICTLY DETERMINISTIC METRICS" in SYSTEM_PROMPT
    assert "ZERO BURNING POLICY" in SYSTEM_PROMPT


# ── Agent initialization (stubbed — no live Bedrock) ─────────────────────────


def test_create_parali_agent_initialization(clean_database, monkeypatch):
    """Verify agent structure without touching AWS Bedrock.

    Monkeypatches strands.Agent.__init__ to record the tools list
    without attempting a real Bedrock client instantiation.
    """
    captured: dict = {}

    def _fake_agent_init(self, model=None, system_prompt=None, tools=None, messages=None, **kwargs):
        captured["tool_names"] = [t.__name__ for t in (tools or [])]
        captured["model"] = model
        # Do NOT set self.tool_names — it's a read-only property on Agent
        self.messages = messages or []

    monkeypatch.setattr("strands.Agent.__init__", _fake_agent_init)

    chat_id = 88888
    agent = create_parali_agent(chat_id=chat_id, model="anthropic.claude-3-5-sonnet-20241022-v2:0")
    assert agent is not None
    assert len(captured["tool_names"]) == 4
    assert "save_farmer_details" in captured["tool_names"]
    assert "find_residue_options" in captured["tool_names"]
    assert "nearby_fire_activity" in captured["tool_names"]
    assert "create_booking_request" in captured["tool_names"]


# ── Location Slot Updating & Ex-Situ Intent Tests ───────────────────────────


@pytest.mark.asyncio
async def test_parse_and_save_details_location_update(clean_database, monkeypatch):
    """Verifies that new location in subsequent messages updates previous location slot."""
    from src.agent.agent import _parse_and_save_details
    from src.connectors.geocode import GeocodeResult

    async def fake_geocode(self, query):
        if "Samrala" in query:
            return GeocodeResult(lat=30.8385, lon=76.1912, display_name="Samrala, Ludhiana, Punjab")
        return GeocodeResult(lat=30.3400, lon=76.3800, display_name="Patiala, Punjab")

    monkeypatch.setattr("src.connectors.geocode.Geocoder.geocode", fake_geocode)

    chat_id = 99901
    # 1. First message sets Patiala
    session1 = await _parse_and_save_details(chat_id, "10 acres in Patiala, sowing in 12 days", clean_database)
    assert session1.acres == 10.0
    assert session1.lat == 30.3400
    assert "Patiala" in session1.village_text

    # 2. Second message updates location to Samrala
    session2 = await _parse_and_save_details(chat_id, "Actually I have 15 acres in Samrala, Ludhiana", clean_database)
    assert session2.acres == 15.0
    assert session2.lat == 30.8385
    assert session2.lon == 76.1912
    assert "Samrala" in session2.village_text


def test_ex_situ_intent_detection():
    """Verifies intent recognition for straw selling and commercial biomass buyers."""
    from src.agent.agent import _is_ex_situ_intent

    assert _is_ex_situ_intent("I want to sell my paddy straw") is True
    assert _is_ex_situ_intent("Can I sell straw to CBG plant?") is True
    assert _is_ex_situ_intent("Show me biomass buyers nearby") is True
    assert _is_ex_situ_intent("Ex-situ baling options") is True
    assert _is_ex_situ_intent("पराली बेचना चाहता हूँ") is True
    assert _is_ex_situ_intent("ਪਰਾਲੀ ਵੇਚਣੀ ਹੈ") is True
    assert _is_ex_situ_intent("Super seeder machine rental") is False

