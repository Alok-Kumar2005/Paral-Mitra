from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from src.common.db import DatabaseClient, get_db
from src.common.models import ChatMessage, FarmerSession

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
    if session is not None and session.history is not None:
        return session.history[-max_messages:]

    return []


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

    # Persist last turn into chat_messages table if supported
    try:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=7)
        for msg in messages[-2:]:
            role = msg.get("role")
            if role in ("user", "assistant"):
                content = msg.get("content", "")
                if isinstance(content, list):
                    text = "".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
                else:
                    text = str(content)
                if text.strip():
                    client.append_chat_message(
                        ChatMessage(
                            chat_id=chat_id,
                            role=role,
                            text=text,
                            expires_at=expires,
                        )
                    )
    except Exception as exc:
        logger.debug("Could not append chat message to database: %s", exc)

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

    if hasattr(client, "_chat_messages") and isinstance(client._chat_messages, list):
        client._chat_messages = [m for m in client._chat_messages if m.get("chat_id") != chat_id]

