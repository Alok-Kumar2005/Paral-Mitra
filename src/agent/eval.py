"""Scripted evaluation suite running 6 realistic farmer conversational scenarios through Parali Mitra."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv

from scripts.seed import seed_database
from src.agent.agent import get_default_model_id, run_agent_turn
from src.agent.memory import clear_session_history
from src.common.db import get_db

# Ensure UTF-8 output encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = PROJECT_ROOT / "data" / "seed"


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": 1,
        "name": "English Onboarding, Residue Evaluation & Booking Confirmation",
        "chat_id": 10001,
        "turns": [
            "Hello! I am a farmer with 8 acres in Rauni Farm, Patiala (lat: 30.3150, lon: 76.4120). My wheat sowing deadline is November 20, 2026. What are my options?",
            "Can you tell me more about the first option and create a booking for it?",
            "Yes, please confirm the booking request.",
        ],
    },
    {
        "id": 2,
        "name": "Hindi Conversational Flow (हिंदी संवाद: खेत विवरण, विकल्प एवं बुकिंग)",
        "chat_id": 10002,
        "turns": [
            "नमस्ते, मुझे पराली प्रबंधन के लिए मदद चाहिए।",
            "मेरा खेत 5 एकड़ का है, स्थान पटियाला (Patiala), और गेहूं की बुवाई 2026-11-15 तक करनी है। क्या मशीन उपलब्ध है?",
            "हाँ, पहला विकल्प बुक कर दीजिए।",
        ],
    },
    {
        "id": 3,
        "name": "Missing Information Handling (Incremental details collection)",
        "chat_id": 10003,
        "turns": [
            "Hi, please find me some residue machines.",
            "I have 6 acres in Karnal (lat: 29.6857, lon: 76.9905).",
            "My sowing deadline is 15 days from now.",
        ],
    },
    {
        "id": 4,
        "name": "Impossible Sowing Deadline (Infeasibility explanation)",
        "chat_id": 10004,
        "turns": [
            f"I have 25 acres in Patiala (lat: 30.3150, lon: 76.4120), but my sowing deadline is tomorrow ({(date.today() + timedelta(days=1)).isoformat()}). Can I get a Super Seeder?",
        ],
    },
    {
        "id": 5,
        "name": "User Inquires About Burning (Anti-burning policy & fine comparison)",
        "chat_id": 10005,
        "turns": [
            "Managing straw takes too much time. What happens if I just burn my 10 acres in Patiala?",
            "Okay, if I don't burn, what are the cheapest non-burning alternatives for 10 acres in Patiala by November 25, 2026?",
        ],
    },
    {
        "id": 6,
        "name": "Acreage Modification & Dynamic Re-optimization",
        "chat_id": 10006,
        "turns": [
            "I have 4 acres in Karnal (lat: 29.6857, lon: 76.9905) with deadline 2026-11-20. Show options.",
            "Actually, my brother and I combined our land, so now it is 12 acres. Please recalculate options for 12 acres.",
        ],
    },
]


async def run_scenario(scenario: dict[str, Any], model_id: str | None = None) -> None:
    """Executes a single scripted scenario and prints formatted transcript."""
    db = get_db(mode="local")
    chat_id = scenario["chat_id"]
    clear_session_history(chat_id=chat_id, db=db)

    print("\n" + "=" * 75)
    print(f" SCENARIO {scenario['id']}: {scenario['name']}")
    print(f" Session Chat ID: {chat_id}")
    print("=" * 75)

    for turn_idx, user_msg in enumerate(scenario["turns"], start=1):
        print(f"\n[Turn {turn_idx}]")
        print(f"👨‍🌾 Farmer: {user_msg}")
        try:
            advisor_reply = await run_agent_turn(
                chat_id=chat_id,
                user_message=user_msg,
                model=model_id,
                db=db,
            )
            print(f"🤖 Advisor:\n{advisor_reply}")
        except Exception as exc:
            print(f"❌ Error during turn {turn_idx}: {exc}")

    print("-" * 75)


async def run_all_evals(model_id: str | None = None) -> None:
    """Runs all 6 evaluation scenarios sequentially and prints full transcripts."""
    db = get_db(mode="local")
    seed_database(seed_dir=SEED_DIR, db_mode="local")

    resolved_model = model_id or get_default_model_id()
    print("\n" + "#" * 75)
    print(f" PARALI MITRA - SCRIPTED AGENT EVALUATION SUITE")
    print(f" Model ID : {resolved_model}")
    print(f" Database : Local In-Memory Store")
    print(f" Scenarios: {len(SCENARIOS)}")
    print("#" * 75)

    for sc in SCENARIOS:
        await run_scenario(sc, model_id=resolved_model)

    print("\n" + "#" * 75)
    print(" ALL 6 EVALUATION SCENARIOS COMPLETED")
    print("#" * 75 + "\n")


def main() -> None:
    """CLI runner for evaluation script."""
    model_id = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_all_evals(model_id=model_id))


if __name__ == "__main__":
    main()
