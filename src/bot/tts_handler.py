"""Text-to-Speech handler — Amazon Polly synthesis for Parali Mitra.

Synthesizes the last assistant message using Amazon Polly and sends it as a
voice note via Telegram sendVoice.

Language support:
  en-IN → Kajal (Neural engine)
  hi-IN → Aditi (Neural engine)
  pa-IN → NOT supported; UnsupportedTTSLanguageError raised → friendly reply

Output format: mp3 (Polly → MP3 bytes → sendVoice with MIME audio/mpeg).
Telegram sendVoice accepts OGG/Opus, MP3, and M4A as native voice notes.
No ffmpeg conversion is required.

Privacy: Polly text is cleaned (no raw IDs, URLs, or markdown) before synthesis.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any

import boto3

from src.bot.voice_config import (
    POLLY_MAX_TEXT_LENGTH,
    POLLY_OUTPUT_FORMAT,
    POLLY_VOICE_MIME_TYPE,
    POLLY_VOICES,
)

if TYPE_CHECKING:
    from src.bot.telegram_client import TelegramClient
    from src.common.models import FarmerSession

logger = logging.getLogger(__name__)


class UnsupportedTTSLanguageError(Exception):
    """Raised when the farmer's language has no Polly voice mapping."""


# ── Localised user-facing messages ────────────────────────────────────────────

_TTS_UNAVAILABLE: dict[str, str] = {
    "en": "🔇 Audio reply is not available in Punjabi. Please read the text above.",
    "hi": "🔇 ऑडियो रिप्लाई इस भाषा में उपलब्ध नहीं है। कृपया ऊपर का टेक्स्ट पढ़ें।",
    "pa": "🔇 ਆਡੀਓ ਜਵਾਬ ਪੰਜਾਬੀ ਵਿੱਚ ਉਪਲਬਧ ਨਹੀਂ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਉੱਪਰ ਦਾ ਟੈਕਸਟ ਪੜ੍ਹੋ।",
}

_TTS_ERROR: dict[str, str] = {
    "en": "🔇 Couldn't generate audio right now. Please read the text above.",
    "hi": "🔇 अभी ऑडियो नहीं बना सका। कृपया ऊपर का टेक्स्ट पढ़ें।",
    "pa": "🔇 ਹੁਣੇ ਆਡੀਓ ਨਹੀਂ ਬਣਾ ਸਕਿਆ। ਕਿਰਪਾ ਕਰਕੇ ਉੱਪਰ ਦਾ ਟੈਕਸਟ ਪੜ੍ਹੋ।",
}


def _msg(strings: dict[str, str], lang: str) -> str:
    return strings.get(lang) or strings["en"]


def _clean_text_for_tts(text: str) -> str:
    """Strips markdown, URLs, machine IDs, and code-like tokens before speaking.

    Polly should never speak raw machine IDs (MCH_001), booking IDs (BK-…),
    Telegram markup symbols, or URLs.
    """
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove machine / booking / provider IDs
    text = re.sub(r"\b(MCH|BYR|BK|PRV)[-_]\w+\b", "", text, flags=re.IGNORECASE)
    # Remove markdown bold / italic / code markers
    text = re.sub(r"[*_`#~|]", "", text)
    # Remove emoji-heavy lines that don't translate well to speech
    text = re.sub(r"([^\x00-\x7F]{2,})\s*", r"\1 ", text)
    # Collapse extra whitespace and trim
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _truncate_for_polly(text: str) -> str:
    """Truncates text to POLLY_MAX_TEXT_LENGTH at a sentence boundary."""
    if len(text) <= POLLY_MAX_TEXT_LENGTH:
        return text
    # Try to cut at last sentence end within limit
    cutoff = text.rfind("।", 0, POLLY_MAX_TEXT_LENGTH)  # Devanagari danda
    if cutoff == -1:
        cutoff = text.rfind(".", 0, POLLY_MAX_TEXT_LENGTH)
    if cutoff == -1:
        cutoff = POLLY_MAX_TEXT_LENGTH
    return text[: cutoff + 1].strip()


async def polly_synthesize(text: str, lang: str) -> bytes:
    """Synthesizes text to MP3 bytes using Amazon Polly.

    Args:
        text: The text to synthesize (will be cleaned before sending to Polly).
        lang: Bot language code ('en', 'hi', 'pa').

    Returns:
        Raw MP3 audio bytes.

    Raises:
        UnsupportedTTSLanguageError: if lang has no Polly voice (e.g. 'pa').
        RuntimeError: for Polly API errors.
    """
    voice_cfg = POLLY_VOICES.get(lang)
    if not voice_cfg:
        raise UnsupportedTTSLanguageError(
            f"Amazon Polly has no voice for language '{lang}'. "
            "Punjabi (pa-IN) is not supported by Polly."
        )

    clean = _clean_text_for_tts(text)
    clean = _truncate_for_polly(clean)

    if not clean:
        raise RuntimeError("Text is empty after cleaning — nothing to synthesize.")

    polly = boto3.client("polly", region_name=os.environ.get("AWS_REGION", "ap-south-1"))

    import asyncio

    def _synth() -> bytes:
        resp = polly.synthesize_speech(
            Text=clean,
            OutputFormat=POLLY_OUTPUT_FORMAT,
            VoiceId=voice_cfg["VoiceId"],
            Engine=voice_cfg["Engine"],
            LanguageCode=voice_cfg["LanguageCode"],
        )
        return resp["AudioStream"].read()

    loop = asyncio.get_event_loop()
    audio_bytes: bytes = await loop.run_in_executor(None, _synth)
    logger.info(
        "[TTS] Polly synthesized %d bytes (voice=%s, lang=%s)",
        len(audio_bytes),
        voice_cfg["VoiceId"],
        lang,
    )
    return audio_bytes


# ── TTS callback handler ───────────────────────────────────────────────────────


async def handle_tts_callback(
    data: str,
    chat_id: int,
    session: "FarmerSession",
    telegram_client: "TelegramClient",
) -> None:
    """Handles a 'tts:<ref>' inline button callback.

    Retrieves the cached last assistant response from session.data, synthesizes
    it with Polly, and sends it as a voice note.

    data format: "tts:<anything>" — we ignore the ref and use session.data.
    """
    lang: str = session.language or "hi"

    # Retrieve last response from session data blob (no DB migration required)
    session_data: dict[str, Any] = {}
    if hasattr(session, "last_options") and isinstance(session.last_options, list):
        # last_options is a standard field; last_response lives in a side channel
        pass
    # We store last_response in session._voice_cache (in-process only for local)
    # or via the last_response key in the session data dict (for Postgres).
    # The router sets session._voice_last_response before the TTS button appears.
    last_response: str = getattr(session, "_voice_last_response", "") or ""

    if not last_response:
        await telegram_client.send_message(
            chat_id,
            _msg(_TTS_ERROR, lang),
        )
        return

    await telegram_client.send_chat_action(chat_id, "record_voice")

    try:
        audio_bytes = await polly_synthesize(last_response, lang)
        await telegram_client.send_voice(
            chat_id=chat_id,
            voice_bytes=audio_bytes,
            filename="reply.mp3",
            mime_type=POLLY_VOICE_MIME_TYPE,
        )
    except UnsupportedTTSLanguageError:
        await telegram_client.send_message(chat_id, _msg(_TTS_UNAVAILABLE, lang))
    except Exception as exc:
        logger.error("[TTS] Polly synthesis error for chat %s: %s", chat_id, exc)
        await telegram_client.send_message(chat_id, _msg(_TTS_ERROR, lang))
