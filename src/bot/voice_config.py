"""Voice input/output configuration constants for Parali Mitra.

All tunable limits, language codes, and Polly voice mappings live here so
they can be changed without touching any business logic.
"""

from __future__ import annotations

# ── Transcription (Amazon Transcribe) ─────────────────────────────────────────

# Language codes supported for batch STT.
# pa-IN is confirmed supported by Amazon Transcribe batch (verified 2026-10-10).
TRANSCRIPTION_LANGUAGES: list[str] = ["en-IN", "hi-IN", "pa-IN"]

# Map short bot language codes (hi / pa / en) → Transcribe language codes
BOT_LANG_TO_TRANSCRIBE: dict[str, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "pa": "pa-IN",
}

MAX_VOICE_DURATION_SECONDS: int = 60       # Reject voice notes longer than 60 s
MAX_VOICE_FILE_SIZE_BYTES: int = 1_048_576  # 1 MiB hard reject before download

TRANSCRIBE_POLL_INTERVAL_SECONDS: float = 2.0
TRANSCRIBE_POLL_TIMEOUT_SECONDS: int = 60

# S3 prefix under which voice audio is staged (deleted after transcription)
S3_VOICE_PREFIX: str = "voice"
# s3://<S3_BUCKET_NAME>/voice/<chat_id>/<uuid>.ogg

# ── Text-to-Speech (Amazon Polly) ─────────────────────────────────────────────

# pa-IN: Amazon Polly has NO Punjabi voice (confirmed 2026-10-10).
# en-IN: Kajal (Neural) — best quality; available in ap-south-1.
# hi-IN: Aditi (Neural) — bilingual, handles Devanagari + Romanised Hindi.
POLLY_VOICES: dict[str, dict[str, str]] = {
    "en": {"VoiceId": "Kajal", "Engine": "neural", "LanguageCode": "en-IN"},
    "hi": {"VoiceId": "Aditi", "Engine": "neural", "LanguageCode": "hi-IN"},
    # "pa" intentionally omitted — no Polly voice for Punjabi
}

# Polly output format for sendVoice.  mp3 is accepted by Telegram sendVoice
# (alongside OGG/Opus and M4A).  No ffmpeg conversion needed.
POLLY_OUTPUT_FORMAT: str = "mp3"
POLLY_VOICE_MIME_TYPE: str = "audio/mpeg"

# Maximum text length Polly will synthesize in one request (AWS hard limit: 3000 chars)
POLLY_MAX_TEXT_LENGTH: int = 1500   # conservative limit; long texts are truncated
