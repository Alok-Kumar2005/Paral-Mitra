"""Session memory and conversation turn persistence for Parali Mitra agent."""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from src.common.db import DatabaseClient, get_db
from src.common.models import FarmerSession

logger = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES: int = 20  # ~10 conversation turns (user + assistant)


def load_session_history(
    chat_id: int,
    db: DatabaseClient | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> list[dict[str, Any]]:
    """Loads recent message history for a farmer chat session.

    Args:
        chat_id: Telegram user/chat ID.
        db: Database client instance (defaults to get_db()).
        max_messages: Maximum recent messages to retain (default 20 = 10 turns).

    Returns:
        List of message dictionaries suitable for Strands Agent initialization.
    """
    client = db or get_db()
    session = client.get_session(chat_id)
    if not session or not session.history:
        return []
    return session.history[-max_messages:]


def save_session_history(
    chat_id: int,
    messages: list[dict[str, Any]],
    db: DatabaseClient | None = None,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> FarmerSession:
    """Persists updated conversation history into the farmer's session record.

    Args:
        chat_id: Telegram user/chat ID.
        messages: Complete or updated message list.
        db: Database client instance.
        max_messages: Maximum recent messages to keep in storage.

    Returns:
        The updated FarmerSession object.
    """
    client = db or get_db()
    session = client.get_session(chat_id)
    if session is None:
        session = FarmerSession(chat_id=chat_id)

    # Sanitize and truncate messages to last N turns
    session.history = messages[-max_messages:]
    session.updated_at = datetime.now()
    client.put_session(session)
    return session


def clear_session_history(chat_id: int, db: DatabaseClient | None = None) -> None:
    """Clears conversation history and cached options for a given chat_id."""
    client = db or get_db()
    session = client.get_session(chat_id)
    if session:
        session.history = []
        session.last_options = None
        session.updated_at = datetime.now()
        client.put_session(session)
