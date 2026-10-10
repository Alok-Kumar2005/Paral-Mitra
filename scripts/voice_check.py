"""Voice check script — integration smoke-test for the S3 + Transcribe pipeline.

Usage:
    python scripts/voice_check.py <path/to/file.ogg> <language-code>

    e.g.  python scripts/voice_check.py sample.ogg hi-IN
          python scripts/voice_check.py my_note.ogg pa-IN

Requires:
    - AWS credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY or IAM role)
    - S3_BUCKET_NAME environment variable set to the Parali Mitra bucket
    - The bucket must exist and the credentials must have:
        s3:PutObject, s3:GetObject, s3:DeleteObject  (on voice/* prefix)
        transcribe:StartTranscriptionJob, GetTranscriptionJob, DeleteTranscriptionJob

Steps performed:
    1. Upload <file.ogg> to s3://<S3_BUCKET_NAME>/voice/<uuid>.ogg
    2. Start Amazon Transcribe batch job
    3. Poll every 2 s until COMPLETED or timeout (60 s)
    4. Download and parse the presigned TranscriptFileUri
    5. Print the transcript and total wall-clock latency
    6. Delete the S3 object and Transcribe job (cleanup)

Exit codes:
    0 — success (transcript printed)
    1 — transcription failed, timeout, or error
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.bot.voice_config import TRANSCRIPTION_LANGUAGES, TRANSCRIBE_POLL_TIMEOUT_SECONDS
from src.bot.voice_handler import (
    _delete_s3_object,
    _delete_transcribe_job,
    _fetch_transcript_text,
    _make_job_name,
    _make_s3_key,
    _poll_transcribe_job,
    _start_transcription_job,
    _upload_to_s3,
    TranscriptionError,
)


class _DummyTelegramClient:
    """Minimal stub so _poll_transcribe_job can call send_chat_action without crashing."""

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        print(f"  [action] {action}", flush=True)


async def run_check(ogg_path: str, language_code: str) -> int:
    """Runs the full S3 + Transcribe pipeline and prints the transcript."""
    bucket = os.environ.get("S3_BUCKET_NAME", "")
    if not bucket:
        print("ERROR: S3_BUCKET_NAME environment variable is not set.", file=sys.stderr)
        return 1

    if language_code not in TRANSCRIPTION_LANGUAGES:
        print(
            f"ERROR: language '{language_code}' is not in TRANSCRIPTION_LANGUAGES: "
            f"{TRANSCRIPTION_LANGUAGES}",
            file=sys.stderr,
        )
        return 1

    file_bytes = Path(ogg_path).read_bytes()
    file_size_kb = len(file_bytes) / 1024
    print(f"\n🎙️  Voice Check")
    print(f"   File    : {ogg_path} ({file_size_kb:.1f} KB)")
    print(f"   Language: {language_code}")
    print(f"   Bucket  : {bucket}")

    run_id = str(uuid.uuid4()).replace("-", "")[:16]
    chat_id = 0  # dummy for naming
    s3_key = _make_s3_key(chat_id, run_id)
    job_name = _make_job_name(chat_id, run_id)
    tg_stub = _DummyTelegramClient()

    s3_uploaded = False
    job_started = False
    t0 = time.monotonic()

    try:
        print("\n→ Uploading to S3...")
        await _upload_to_s3(file_bytes, bucket, s3_key)
        s3_uploaded = True

        print("→ Starting Transcribe job...")
        await _start_transcription_job(job_name, bucket, s3_key, language_code)
        job_started = True

        print(f"→ Polling (timeout={TRANSCRIBE_POLL_TIMEOUT_SECONDS}s)...")
        presigned_uri = await _poll_transcribe_job(job_name, tg_stub, chat_id)  # type: ignore[arg-type]

        print("→ Fetching transcript...")
        transcript = await _fetch_transcript_text(presigned_uri)

        elapsed = time.monotonic() - t0
        print(f"\n✅ Transcript ({elapsed:.1f}s):\n   {transcript}\n")
        return 0

    except TranscriptionError as exc:
        elapsed = time.monotonic() - t0
        print(f"\n❌ Transcription error ({elapsed:.1f}s): {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"\n❌ Unexpected error ({elapsed:.1f}s): {exc}", file=sys.stderr)
        return 1
    finally:
        if s3_uploaded:
            print("→ Deleting S3 object (cleanup)...")
            await _delete_s3_object(bucket, s3_key)
        if job_started:
            print("→ Deleting Transcribe job (cleanup)...")
            await _delete_transcribe_job(job_name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test the S3 + Amazon Transcribe voice pipeline against real AWS."
    )
    parser.add_argument("ogg_file", help="Path to a local .ogg audio file")
    parser.add_argument("language_code", help=f"Transcribe language code, one of: {TRANSCRIPTION_LANGUAGES}")
    args = parser.parse_args()

    if not Path(args.ogg_file).exists():
        print(f"ERROR: file not found: {args.ogg_file}", file=sys.stderr)
        sys.exit(1)

    exit_code = asyncio.run(run_check(args.ogg_file, args.language_code))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
