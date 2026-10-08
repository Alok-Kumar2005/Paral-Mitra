"""Parali Mitra conversational agent orchestration using Strands Agents SDK."""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from strands import Agent
from strands.models.model import Model

from src.agent.memory import load_session_history, save_session_history
from src.agent.prompt import SYSTEM_PROMPT
from src.agent.tools import (
    create_booking_request,
    find_residue_options,
    nearby_fire_activity,
    save_farmer_details,
)
from src.common.db import DatabaseClient, get_db

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_BEDROCK_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"


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
    message_history = history if history is not None else load_session_history(chat_id=chat_id, db=db)

    return Agent(
        model=resolved_model,
        system_prompt=SYSTEM_PROMPT,
        tools=get_agent_tools(),
        messages=message_history,
        callback_handler=None,  # Clean non-streaming callback for serverless
    )


async def run_agent_turn(
    chat_id: int,
    user_message: str,
    model: str | Model | None = None,
    db: DatabaseClient | None = None,
) -> str:
    """Processes a single conversational turn for a farmer, persisting memory before and after.

    Args:
        chat_id: Telegram user/chat ID.
        user_message: Incoming farmer text message.
        model: Model ID string or custom Model instance.
        db: Database client instance.

    Returns:
        Assistant response text formatted for Telegram.
    """
    client = db or get_db()
    agent = create_parali_agent(chat_id=chat_id, model=model, db=client)

    logger.info("Invoking agent for chat_id=%d, model=%s", chat_id, model or get_default_model_id())
    result = await agent.invoke_async(user_message)
    response_text = str(result).strip()

    # Persist updated turn history into database
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
