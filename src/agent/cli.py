"""Interactive Terminal CLI for Parali Mitra Strands Agent."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

from scripts.seed import seed_database
from src.agent.agent import get_default_model_id, run_agent_turn
from src.agent.memory import clear_session_history
from src.common.db import get_db

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = PROJECT_ROOT / "data" / "seed"


async def async_cli_loop(chat_id: int = 99999) -> None:
    """Runs the asynchronous interactive terminal chat loop."""
    db = get_db(mode="local")

    # Ensure catalog seed data is loaded
    if len(db.list_machines()) == 0 or len(db.list_buyers()) == 0:
        seed_database(seed_dir=SEED_DIR, db_mode="local")

    model_id = get_default_model_id()

    print("\n" + "=" * 65)
    print("      🌾 PARALI MITRA (पराली मित्र) - LOCAL CLI ADVISOR 🌾")
    print("=" * 65)
    print(f" Model ID    : {model_id}")
    print(" Database    : Local In-Memory Store")
    print(" Session ID  : chat_id=" + str(chat_id))
    print(" Commands    : 'clear' to reset chat, 'exit'/'quit' to leave")
    print("=" * 65 + "\n")
    print("Advisor: Sat Sri Akal / Namaste! I am Parali Mitra. How can I assist you with your paddy harvest?")

    while True:
        try:
            user_input = input("\nYou > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting Parali Mitra. Goodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "q"):
            print("\nThank you for using Parali Mitra. Kisaan Ekta Zindabad!")
            break

        if user_input.lower() in ("clear", "reset"):
            clear_session_history(chat_id=chat_id, db=db)
            print("\n[System] Conversation history cleared. Session reset.")
            continue

        print("\nAdvisor > Thinking...", end="\r", flush=True)
        try:
            response = await run_agent_turn(chat_id=chat_id, user_message=user_input, db=db)
            print(f"Advisor > {response}\n")
        except Exception as exc:
            print(f"\n[Error] Failed to process message: {exc}\n")


def main() -> None:
    """Main entrypoint for CLI."""
    asyncio.run(async_cli_loop())


if __name__ == "__main__":
    main()
