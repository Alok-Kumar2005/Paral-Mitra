"""Agent layer integrating Strands Agents SDK and Amazon Bedrock for Parali Mitra."""

from __future__ import annotations

from src.agent.agent import create_parali_agent, run_agent_turn, run_agent_turn_sync
from src.agent.memory import clear_session_history, load_session_history, save_session_history
from src.agent.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from src.agent.tools import (
    create_booking_request,
    find_residue_options,
    nearby_fire_activity,
    save_farmer_details,
)

__all__ = [
    "PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "create_booking_request",
    "create_parali_agent",
    "clear_session_history",
    "find_residue_options",
    "load_session_history",
    "nearby_fire_activity",
    "run_agent_turn",
    "run_agent_turn_sync",
    "save_farmer_details",
    "save_session_history",
]
