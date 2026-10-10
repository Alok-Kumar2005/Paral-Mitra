"""Tests for the voice input/output pipeline.

All tests are offline-only: boto3 and httpx are mocked via unittest.mock.
No real AWS credentials, S3, Transcribe, or Polly calls are made.

Test cases:
  1.  success_path           — full STT pipeline; agent turn runs; cleanup verified.
  2.  long_audio_rejected    — duration > 60 → friendly message, no AWS calls.
  3.  oversized_file_rejected— file_size > 1MB → friendly message, no AWS calls.
  4.  transcription_failed   — Transcribe job FAILED → fallback message to farmer.
  5.  polling_timeout        — job stays IN_PROGRESS for > timeout → timeout error.
  6.  cleanup_always_runs    — exception during transcript fetch; S3+job delete still called.
  7.  unsupported_language   — session.language = 'fr' → ask to type.
  8.  tts_unavailable_lang   — Polly synthesis for 'pa' → UnsupportedTTSLanguageError.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot import voice_handler, tts_handler
from src.bot.voice_handler import TranscriptionError, UnsupportedLanguageError
from src.bot.tts_handler import UnsupportedTTSLanguageError
from src.common.models import FarmerSession


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_session(lang: str = "hi") -> FarmerSession:
    return FarmerSession(chat_id=999, language=lang)


def _make_voice_msg(duration: int = 30, file_size: int = 50_000, file_id: str = "FID123") -> dict[str, Any]:
    return {
        "chat": {"id": 999},
        "voice": {
            "duration": duration,
            "file_size": file_size,
            "file_id": file_id,
        },
    }


def _mock_transcribe_client(status: str = "COMPLETED", failure_reason: str | None = None) -> MagicMock:
    """Returns a boto3 Transcribe client mock with a configurable job status."""
    tc = MagicMock()
    tc.start_transcription_job.return_value = {}
    tc.delete_transcription_job.return_value = {}

    job_data: dict[str, Any] = {"TranscriptionJobStatus": status}
    if status == "COMPLETED":
        job_data["Transcript"] = {"TranscriptFileUri": "https://aws.example.com/result.json"}
    if failure_reason:
        job_data["FailureReason"] = failure_reason

    tc.get_transcription_job.return_value = {"TranscriptionJob": job_data}
    return tc


def _mock_s3_client() -> MagicMock:
    s3 = MagicMock()
    s3.put_object.return_value = {}
    s3.delete_object.return_value = {}
    return s3


def _mock_telegram_client() -> AsyncMock:
    tg = AsyncMock()
    tg.get_file.return_value = {"file_path": "voice/FID123.oga"}
    tg.download_file.return_value = b"\x00" * 1000  # 1 KB of fake audio
    tg.send_message.return_value = [{}]
    tg.send_chat_action.return_value = {}
    tg.send_voice.return_value = {}
    return tg


# ── Test 1: Success path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_path() -> None:
    """Full STT pipeline succeeds: S3 upload, Transcribe, fetch, cleanup called."""
    session = _make_session("hi")
    tg = _mock_telegram_client()
    db = MagicMock()

    transcript_json = '{"results": {"transcripts": [{"transcript": "मेरे पास 9 एकड़ धान है"}]}}'
    http_resp = MagicMock()
    http_resp.json.return_value = {
        "results": {"transcripts": [{"transcript": "मेरे पास 9 एकड़ धान है"}]}
    }
    http_resp.raise_for_status.return_value = None

    s3_mock = _mock_s3_client()
    tc_mock = _mock_transcribe_client("COMPLETED")

    with (
        patch("src.bot.voice_handler.boto3") as mock_boto3,
        patch("src.bot.voice_handler.httpx.AsyncClient") as mock_httpx,
        patch.dict("os.environ", {"S3_BUCKET_NAME": "test-bucket", "AWS_REGION": "ap-south-1"}),
    ):
        mock_boto3.client.side_effect = lambda svc, **kw: s3_mock if svc == "s3" else tc_mock
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_ctx.get = AsyncMock(return_value=http_resp)
        mock_httpx.return_value = mock_ctx

        result = await voice_handler.handle_voice_message(
            msg=_make_voice_msg(),
            session=session,
            db=db,
            telegram_client=tg,
        )

    assert result == "मेरे पास 9 एकड़ धान है"
    # Verify S3 put and delete were called
    s3_mock.put_object.assert_called_once()
    s3_mock.delete_object.assert_called_once()
    # Verify Transcribe start and delete were called
    tc_mock.start_transcription_job.assert_called_once()
    tc_mock.delete_transcription_job.assert_called_once()
    # Confirm "I heard" message was sent
    heard_call_args = [str(c) for c in tg.send_message.call_args_list]
    assert any("मैंने सुना" in str(c) for c in heard_call_args)


# ── Test 2: Long audio rejected ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_long_audio_rejected() -> None:
    """Voice note longer than 60 s is rejected before any AWS call."""
    session = _make_session("en")
    tg = _mock_telegram_client()
    db = MagicMock()

    with patch("src.bot.voice_handler.boto3") as mock_boto3:
        result = await voice_handler.handle_voice_message(
            msg=_make_voice_msg(duration=90),
            session=session,
            db=db,
            telegram_client=tg,
        )
        mock_boto3.client.assert_not_called()  # no AWS calls

    assert result is None
    sent_text = tg.send_message.call_args[0][1]
    assert "60" in sent_text  # friendly duration message


# ── Test 3: Oversized file rejected ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_oversized_file_rejected() -> None:
    """Voice file larger than 1 MB is rejected before download."""
    session = _make_session("pa")
    tg = _mock_telegram_client()
    db = MagicMock()

    with patch("src.bot.voice_handler.boto3") as mock_boto3:
        result = await voice_handler.handle_voice_message(
            msg=_make_voice_msg(duration=10, file_size=2_000_000),
            session=session,
            db=db,
            telegram_client=tg,
        )
        mock_boto3.client.assert_not_called()

    assert result is None
    sent_text = tg.send_message.call_args[0][1]
    assert "MB" in sent_text or "ਵੱਡੀ" in sent_text


# ── Test 4: Transcription FAILED ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_transcription_failed() -> None:
    """Transcribe job returns FAILED status → farmer gets fallback message."""
    session = _make_session("hi")
    tg = _mock_telegram_client()
    db = MagicMock()
    s3_mock = _mock_s3_client()
    tc_mock = _mock_transcribe_client("FAILED", failure_reason="Language not supported")

    with (
        patch("src.bot.voice_handler.boto3") as mock_boto3,
        patch.dict("os.environ", {"S3_BUCKET_NAME": "test-bucket", "AWS_REGION": "ap-south-1"}),
    ):
        mock_boto3.client.side_effect = lambda svc, **kw: s3_mock if svc == "s3" else tc_mock

        result = await voice_handler.handle_voice_message(
            msg=_make_voice_msg(),
            session=session,
            db=db,
            telegram_client=tg,
        )

    assert result is None
    # Cleanup must still have been attempted
    s3_mock.delete_object.assert_called_once()
    tc_mock.delete_transcription_job.assert_called_once()
    # Farmer gets fallback message
    sent_texts = [str(c) for c in tg.send_message.call_args_list]
    assert any("टाइप" in t or "resend" in t.lower() for t in sent_texts)


# ── Test 5: Polling timeout ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_polling_timeout() -> None:
    """Job stays IN_PROGRESS past timeout → TranscriptionError → fallback."""
    session = _make_session("en")
    tg = _mock_telegram_client()
    db = MagicMock()
    s3_mock = _mock_s3_client()

    # Always returns IN_PROGRESS
    tc_mock = MagicMock()
    tc_mock.start_transcription_job.return_value = {}
    tc_mock.delete_transcription_job.return_value = {}
    tc_mock.get_transcription_job.return_value = {
        "TranscriptionJob": {"TranscriptionJobStatus": "IN_PROGRESS"}
    }

    with (
        patch("src.bot.voice_handler.boto3") as mock_boto3,
        patch("src.bot.voice_handler.TRANSCRIBE_POLL_TIMEOUT_SECONDS", 4),  # small timeout for test
        patch("src.bot.voice_handler.TRANSCRIBE_POLL_INTERVAL_SECONDS", 1.0),
        patch.dict("os.environ", {"S3_BUCKET_NAME": "test-bucket", "AWS_REGION": "ap-south-1"}),
    ):
        mock_boto3.client.side_effect = lambda svc, **kw: s3_mock if svc == "s3" else tc_mock

        result = await voice_handler.handle_voice_message(
            msg=_make_voice_msg(),
            session=session,
            db=db,
            telegram_client=tg,
        )

    assert result is None
    # Cleanup still runs on timeout
    s3_mock.delete_object.assert_called_once()
    tc_mock.delete_transcription_job.assert_called_once()


# ── Test 6: Cleanup always runs ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_always_runs_on_exception() -> None:
    """If an unexpected exception fires after upload, S3 + Transcribe still get cleaned up."""
    session = _make_session("en")
    tg = _mock_telegram_client()
    db = MagicMock()
    s3_mock = _mock_s3_client()

    tc_mock = MagicMock()
    tc_mock.start_transcription_job.return_value = {}
    tc_mock.delete_transcription_job.return_value = {}
    # Inject error on get_transcription_job
    tc_mock.get_transcription_job.side_effect = RuntimeError("Unexpected AWS error")

    with (
        patch("src.bot.voice_handler.boto3") as mock_boto3,
        patch.dict("os.environ", {"S3_BUCKET_NAME": "test-bucket", "AWS_REGION": "ap-south-1"}),
    ):
        mock_boto3.client.side_effect = lambda svc, **kw: s3_mock if svc == "s3" else tc_mock

        result = await voice_handler.handle_voice_message(
            msg=_make_voice_msg(),
            session=session,
            db=db,
            telegram_client=tg,
        )

    assert result is None
    # Both cleanup calls must have been made despite the exception
    s3_mock.delete_object.assert_called_once()
    tc_mock.delete_transcription_job.assert_called_once()


# ── Test 7: Unsupported language ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unsupported_language() -> None:
    """A farmer with an unsupported language (e.g. 'fr') is asked to type instead."""
    session = _make_session("fr")  # French — not in BOT_LANG_TO_TRANSCRIBE
    tg = _mock_telegram_client()
    db = MagicMock()

    with patch("src.bot.voice_handler.boto3") as mock_boto3:
        result = await voice_handler.handle_voice_message(
            msg=_make_voice_msg(),
            session=session,
            db=db,
            telegram_client=tg,
        )
        mock_boto3.client.assert_not_called()

    assert result is None
    # Fallback to English unsupported-lang message
    sent_text = tg.send_message.call_args[0][1]
    assert "type" in sent_text.lower() or "Voice input" in sent_text


# ── Test 8: TTS unavailable language ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_tts_unavailable_for_punjabi() -> None:
    """polly_synthesize raises UnsupportedTTSLanguageError for 'pa' (no Polly voice)."""
    with pytest.raises(UnsupportedTTSLanguageError):
        await tts_handler.polly_synthesize("ਮੇਰੇ ਕੋਲ 9 ਏਕੜ ਝੋਨਾ ਹੈ", lang="pa")


@pytest.mark.asyncio
async def test_tts_callback_sends_unavailable_message_for_punjabi() -> None:
    """handle_tts_callback for a Punjabi farmer sends the 'audio unavailable' message."""
    session = _make_session("pa")
    session._voice_last_response = "ਤੁਹਾਡੇ ਵਿਕਲਪ ਇਹ ਹਨ"  # type: ignore[attr-defined]
    tg = _mock_telegram_client()

    await tts_handler.handle_tts_callback("tts:last", chat_id=999, session=session, telegram_client=tg)

    sent_text = tg.send_message.call_args[0][1]
    assert "ਪੰਜਾਬੀ" in sent_text or "Punjabi" in sent_text or "unavailable" in sent_text.lower()
