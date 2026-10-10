"""Voice input handler — Amazon Transcribe STT pipeline for Parali Mitra.

Flow:
  1. Validate duration ≤ 60 s and file_size ≤ 1 MB.
  2. Download raw OGG/Opus bytes via Telegram getFile/downloadFile.
  3. Upload to S3 under voice/<chat_id>/<uuid>.ogg.
  4. Start Amazon Transcribe batch job (no OutputBucketName → presigned URI).
  5. Poll every 2 s (send sendChatAction "record_voice" each round).
  6. On COMPLETED: fetch presigned URI with httpx, parse transcript text.
  7. In finally block: delete S3 object and Transcribe job.
  8. Send "🎙️ I heard: <text>" to farmer, then return transcript for agent turn.

Privacy:
  - Transcript text is logged at DEBUG only (never INFO).
  - Audio bytes are never stored in the database.
  - S3 object is deleted in the finally block regardless of success or failure.

If ffmpeg conversion is required for OGG Opus compatibility, this module will
surface a TranscriptionError so the farmer is asked to type instead — no
silent heavy binary is bundled into the Lambda package.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from typing import TYPE_CHECKING, Any

import boto3
import httpx

from src.bot.voice_config import (
    BOT_LANG_TO_TRANSCRIBE,
    MAX_VOICE_DURATION_SECONDS,
    MAX_VOICE_FILE_SIZE_BYTES,
    S3_VOICE_PREFIX,
    TRANSCRIBE_POLL_INTERVAL_SECONDS,
    TRANSCRIBE_POLL_TIMEOUT_SECONDS,
    TRANSCRIPTION_LANGUAGES,
)

if TYPE_CHECKING:
    from src.bot.telegram_client import TelegramClient
    from src.common.models import FarmerSession

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when transcription fails, times out, or is unsupported."""


class UnsupportedLanguageError(TranscriptionError):
    """Raised when the farmer's language is not supported for transcription."""


# ── Localised user-facing messages ────────────────────────────────────────────

_VOICE_TOO_LONG: dict[str, str] = {
    "en": "🎙️ Voice note is too long (max 60 seconds). Please send a shorter message or type your request.",
    "hi": "🎙️ वॉयस नोट बहुत लंबी है (अधिकतम 60 सेकंड)। कृपया छोटा संदेश भेजें या टाइप करें।",
    "pa": "🎙️ ਵੌਇਸ ਨੋਟ ਬਹੁਤ ਲੰਮੀ ਹੈ (ਵੱਧ ਤੋਂ ਵੱਧ 60 ਸਕਿੰਟ)। ਛੋਟਾ ਸੁਨੇਹਾ ਭੇਜੋ ਜਾਂ ਟਾਈਪ ਕਰੋ।",
}

_VOICE_TOO_LARGE: dict[str, str] = {
    "en": "🎙️ Voice file is too large (max 1 MB). Please send a shorter note or type your request.",
    "hi": "🎙️ ऑडियो फ़ाइल बहुत बड़ी है (अधिकतम 1 MB)। कृपया छोटा नोट भेजें या टाइप करें।",
    "pa": "🎙️ ਆਡੀਓ ਫਾਈਲ ਬਹੁਤ ਵੱਡੀ ਹੈ (ਵੱਧ ਤੋਂ ਵੱਧ 1 MB)। ਛੋਟਾ ਨੋਟ ਭੇਜੋ ਜਾਂ ਟਾਈਪ ਕਰੋ।",
}

_VOICE_FAIL: dict[str, str] = {
    "en": "🎙️ Couldn't understand the audio. Please type your message (e.g. \"I have 9 acres in Ludhiana\") or resend the voice note.",
    "hi": "🎙️ ऑडियो समझ नहीं आई। कृपया अपना संदेश टाइप करें (जैसे \"मेरे पास लुधियाना में 9 एकड़ धान है\") या वॉयस नोट दोबारा भेजें।",
    "pa": "🎙️ ਆਡੀਓ ਸਮਝ ਨਹੀਂ ਆਈ। ਕਿਰਪਾ ਕਰਕੇ ਸੁਨੇਹਾ ਟਾਈਪ ਕਰੋ (ਜਿਵੇਂ \"ਮੇਰੇ ਕੋਲ ਲੁਧਿਆਣਾ ਵਿੱਚ 9 ਏਕੜ ਝੋਨਾ ਹੈ\") ਜਾਂ ਵੌਇਸ ਨੋਟ ਦੁਬਾਰਾ ਭੇਜੋ।",
}

_VOICE_UNSUPPORTED_LANG: dict[str, str] = {
    "en": "🎙️ Voice input is not supported for your current language. Please type your message.",
    "hi": "🎙️ आपकी भाषा में वॉयस इनपुट उपलब्ध नहीं है। कृपया अपना संदेश टाइप करें।",
    "pa": "🎙️ ਤੁਹਾਡੀ ਭਾਸ਼ਾ ਵਿੱਚ ਵੌਇਸ ਇਨਪੁੱਟ ਉਪਲਬਧ ਨਹੀਂ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਸੁਨੇਹਾ ਟਾਈਪ ਕਰੋ।",
}

_VOICE_HEARD_PREFIX: dict[str, str] = {
    "en": "🎙️ I heard: ",
    "hi": "🎙️ मैंने सुना: ",
    "pa": "🎙️ ਮੈਂ ਸੁਣਿਆ: ",
}

_VOICE_PROCESSING: dict[str, str] = {
    "en": "🎙️ Processing your voice note...",
    "hi": "🎙️ आपकी वॉयस नोट प्रोसेस हो रही है...",
    "pa": "🎙️ ਤੁਹਾਡਾ ਵੌਇਸ ਨੋਟ ਪ੍ਰੋਸੈੱਸ ਹੋ ਰਿਹਾ ਹੈ...",
}

_PRIVACY_NOTICE: dict[str, str] = {
    "en": "🔒 Your audio is transcribed and immediately deleted from our servers.",
    "hi": "🔒 आपका ऑडियो ट्रांसक्राइब होते ही हमारे सर्वर से हटा दिया जाता है।",
    "pa": "🔒 ਤੁਹਾਡਾ ਆਡੀਓ ਟ੍ਰਾਂਸਕ੍ਰਾਈਬ ਹੋਣ ਤੋਂ ਤੁਰੰਤ ਬਾਅਦ ਸਾਡੇ ਸਰਵਰ ਤੋਂ ਹਟਾ ਦਿੱਤਾ ਜਾਂਦਾ ਹੈ।",
}


def _msg(strings: dict[str, str], lang: str) -> str:
    return strings.get(lang) or strings["en"]


# ── Core STT pipeline ──────────────────────────────────────────────────────────


def _make_job_name(chat_id: int, run_id: str) -> str:
    """Generates a unique, Transcribe-safe job name (≤200 chars, alphanumeric/-/_)."""
    return f"parali-{chat_id}-{run_id}"


def _make_s3_key(chat_id: int, run_id: str) -> str:
    return f"{S3_VOICE_PREFIX}/{chat_id}/{run_id}.ogg"


async def _upload_to_s3(
    audio_bytes: bytes,
    bucket: str,
    s3_key: str,
) -> None:
    """Uploads raw OGG bytes to S3 asynchronously via a thread executor."""
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-south-1"))

    def _put() -> None:
        s3.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=audio_bytes,
            ContentType="audio/ogg",
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _put)
    logger.info("[Voice] Uploaded %d bytes to s3://%s/%s", len(audio_bytes), bucket, s3_key)


async def _delete_s3_object(bucket: str, s3_key: str) -> None:
    """Deletes the S3 voice object (best-effort; errors are logged only)."""
    s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-south-1"))

    def _delete() -> None:
        s3.delete_object(Bucket=bucket, Key=s3_key)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _delete)
        logger.info("[Voice] Deleted S3 object s3://%s/%s", bucket, s3_key)
    except Exception as exc:
        logger.warning("[Voice] Failed to delete S3 object %s: %s", s3_key, exc)


async def _start_transcription_job(
    job_name: str,
    bucket: str,
    s3_key: str,
    language_code: str,
) -> None:
    """Starts an Amazon Transcribe batch job. No OutputBucketName → presigned URI."""
    tc = boto3.client("transcribe", region_name=os.environ.get("AWS_REGION", "ap-south-1"))
    s3_uri = f"s3://{bucket}/{s3_key}"

    def _start() -> None:
        tc.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={"MediaFileUri": s3_uri},
            MediaFormat="ogg",
            LanguageCode=language_code,
        )

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _start)
    logger.info("[Voice] Started Transcribe job %s (lang=%s)", job_name, language_code)


async def _delete_transcribe_job(job_name: str) -> None:
    """Deletes the Transcribe job (best-effort)."""
    tc = boto3.client("transcribe", region_name=os.environ.get("AWS_REGION", "ap-south-1"))

    def _delete() -> None:
        tc.delete_transcription_job(TranscriptionJobName=job_name)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _delete)
        logger.info("[Voice] Deleted Transcribe job %s", job_name)
    except Exception as exc:
        logger.warning("[Voice] Failed to delete Transcribe job %s: %s", job_name, exc)


async def _poll_transcribe_job(
    job_name: str,
    telegram_client: "TelegramClient",
    chat_id: int,
) -> str:
    """Polls Transcribe until COMPLETED or FAILED, then returns the presigned URI.

    Sends sendChatAction('record_voice') on each poll iteration to keep the
    'recording audio…' indicator alive in Telegram.

    Raises TranscriptionError on timeout or failure.
    """
    tc = boto3.client("transcribe", region_name=os.environ.get("AWS_REGION", "ap-south-1"))
    loop = asyncio.get_event_loop()

    elapsed = 0.0
    while elapsed < TRANSCRIBE_POLL_TIMEOUT_SECONDS:
        # Show 'record_voice' action each poll cycle (best-effort)
        try:
            await telegram_client.send_chat_action(chat_id, "record_voice")
        except Exception:
            pass

        def _get_job() -> dict[str, Any]:
            return tc.get_transcription_job(TranscriptionJobName=job_name)

        resp = await loop.run_in_executor(None, _get_job)
        job = resp["TranscriptionJob"]
        status = job["TranscriptionJobStatus"]

        if status == "COMPLETED":
            uri: str = job["Transcript"]["TranscriptFileUri"]
            logger.info("[Voice] Transcribe job %s COMPLETED", job_name)
            return uri
        elif status == "FAILED":
            reason = job.get("FailureReason", "Unknown reason")
            logger.warning("[Voice] Transcribe job %s FAILED: %s", job_name, reason)
            raise TranscriptionError(f"Transcription failed: {reason}")

        await asyncio.sleep(TRANSCRIBE_POLL_INTERVAL_SECONDS)
        elapsed += TRANSCRIBE_POLL_INTERVAL_SECONDS

    raise TranscriptionError(
        f"Transcription timed out after {TRANSCRIBE_POLL_TIMEOUT_SECONDS}s (job={job_name})"
    )


async def _fetch_transcript_text(presigned_uri: str) -> str:
    """Downloads the Transcribe JSON result and extracts the transcript text."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(presigned_uri)
        resp.raise_for_status()
        data = resp.json()

    # Transcribe JSON structure: results.transcripts[].transcript
    transcripts: list[dict[str, Any]] = data.get("results", {}).get("transcripts", [])
    if not transcripts:
        raise TranscriptionError("Transcribe returned empty transcript list")

    text = transcripts[0].get("transcript", "").strip()
    logger.debug("[Voice] Transcript text length=%d", len(text))  # DEBUG only — no text at INFO
    return text


def _clean_text_for_tts(text: str) -> str:
    """Strips markdown symbols, URLs, and machine IDs from text before speaking."""
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove markdown bold/italic markers
    text = re.sub(r"[*_`#]", "", text)
    # Remove machine IDs like MCH_001, BK-20241010-abc
    text = re.sub(r"\b(MCH|BYR|BK|PRV)[-_]\w+\b", "", text)
    # Collapse extra whitespace
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


# ── Public handler ─────────────────────────────────────────────────────────────


async def handle_voice_message(
    msg: dict[str, Any],
    session: "FarmerSession",
    db: Any,
    telegram_client: "TelegramClient",
) -> str | None:
    """Full voice-input STT pipeline.

    Returns the transcript string on success (caller runs agent turn).
    Returns None when the message was handled as an error (farmer already notified).
    """
    chat_id: int = msg["chat"]["id"]
    lang: str = session.language or "hi"

    # Extract voice or audio metadata from Telegram message
    voice_info: dict[str, Any] = msg.get("voice") or msg.get("audio") or {}
    duration: int = voice_info.get("duration", 0)
    file_size: int = voice_info.get("file_size", 0)
    file_id: str = voice_info.get("file_id", "")

    # 1. Duration guard (before any download)
    if duration > MAX_VOICE_DURATION_SECONDS:
        await telegram_client.send_message(chat_id, _msg(_VOICE_TOO_LONG, lang))
        return None

    # 2. File size guard (before download; file_size may be 0 if unknown)
    if file_size and file_size > MAX_VOICE_FILE_SIZE_BYTES:
        await telegram_client.send_message(chat_id, _msg(_VOICE_TOO_LARGE, lang))
        return None

    # 3. Language support check
    transcribe_lang = BOT_LANG_TO_TRANSCRIBE.get(lang)
    if not transcribe_lang or transcribe_lang not in TRANSCRIPTION_LANGUAGES:
        await telegram_client.send_message(chat_id, _msg(_VOICE_UNSUPPORTED_LANG, lang))
        return None

    # Notify farmer that processing has started + privacy notice
    await telegram_client.send_chat_action(chat_id, "record_voice")
    await telegram_client.send_message(
        chat_id,
        _msg(_VOICE_PROCESSING, lang) + "\n\n" + _msg(_PRIVACY_NOTICE, lang),
    )

    bucket = os.environ.get("S3_BUCKET_NAME", "")
    if not bucket:
        logger.error("[Voice] S3_BUCKET_NAME env var not set")
        await telegram_client.send_message(chat_id, _msg(_VOICE_FAIL, lang))
        return None

    run_id = str(uuid.uuid4()).replace("-", "")[:16]
    s3_key = _make_s3_key(chat_id, run_id)
    job_name = _make_job_name(chat_id, run_id)

    audio_bytes: bytes = b""
    s3_uploaded = False
    job_started = False

    try:
        # 4. Download audio
        file_meta = await telegram_client.get_file(file_id)
        file_path: str = file_meta.get("file_path", "")
        if not file_path:
            raise TranscriptionError("Empty file_path from Telegram getFile")

        audio_bytes = await telegram_client.download_file(file_path)

        # Post-download size check (catches cases where file_size was 0 above)
        if len(audio_bytes) > MAX_VOICE_FILE_SIZE_BYTES:
            await telegram_client.send_message(chat_id, _msg(_VOICE_TOO_LARGE, lang))
            return None

        # 5. Upload to S3
        await _upload_to_s3(audio_bytes, bucket, s3_key)
        s3_uploaded = True

        # 6. Start Transcribe job
        await _start_transcription_job(job_name, bucket, s3_key, transcribe_lang)
        job_started = True

        # 7. Poll
        presigned_uri = await _poll_transcribe_job(job_name, telegram_client, chat_id)

        # 8. Fetch transcript
        transcript = await _fetch_transcript_text(presigned_uri)

        if not transcript:
            raise TranscriptionError("Empty transcript returned")

        # 9. Confirm to farmer
        heard_msg = _msg(_VOICE_HEARD_PREFIX, lang) + transcript
        await telegram_client.send_message(chat_id, heard_msg)

        return transcript

    except TranscriptionError as exc:
        logger.warning("[Voice] Transcription error for chat %s: %s", chat_id, exc)
        await telegram_client.send_message(chat_id, _msg(_VOICE_FAIL, lang))
        return None
    except Exception as exc:
        logger.error("[Voice] Unexpected error in voice pipeline for chat %s: %s", chat_id, exc)
        await telegram_client.send_message(chat_id, _msg(_VOICE_FAIL, lang))
        return None
    finally:
        # Always clean up — even on success
        if s3_uploaded:
            await _delete_s3_object(bucket, s3_key)
        if job_started:
            await _delete_transcribe_job(job_name)
