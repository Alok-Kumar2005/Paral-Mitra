#!/usr/bin/env python3
"""Smoke test for the deployed Parali Mitra webhook.

Tests three scenarios against the live deployed API:
  a) GET /health          — expect 200, ok=True
  b) POST /telegram/webhook WITHOUT secret header — expect 403
  c) POST /telegram/webhook WITH correct secret + fake update body — expect 200

Usage:
    python scripts/smoke_test.py --url https://abc.execute-api.ap-south-1.amazonaws.com

The webhook secret is read from TELEGRAM_WEBHOOK_SECRET env var or from SSM
/parali/telegram_webhook_secret if the env var is not set.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error


def _get_secret(env_var: str, ssm_name: str) -> str:
    """Read a secret from env var (primary) or SSM (fallback)."""
    val = os.environ.get(env_var, "").strip()
    if val:
        return val
    try:
        import boto3
        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-south-1"))
        resp = ssm.get_parameter(Name=ssm_name, WithDecryption=True)
        return resp["Parameter"]["Value"].strip()
    except Exception:  # noqa: BLE001
        return ""


def _http(method: str, url: str, headers: dict | None = None, body: bytes | None = None) -> tuple[int, dict]:
    """Simple HTTP request; returns (status_code, json_body)."""
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def _assert(condition: bool, test_name: str, detail: str = "") -> None:
    if condition:
        print(f"  ✅  {test_name}")
    else:
        print(f"  ❌  {test_name}{': ' + detail if detail else ''}")
        sys.exit(1)


def _fake_update(update_id: int = 999999) -> bytes:
    """Generate a minimal fake Telegram update payload."""
    payload = {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "chat": {"id": 123456789, "type": "private"},
            "from": {"id": 123456789, "is_bot": False, "first_name": "SmokeTest"},
            "date": int(time.time()),
            "text": "/start",
        },
    }
    return json.dumps(payload).encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test the deployed Parali Mitra webhook.")
    parser.add_argument(
        "--url",
        required=True,
        metavar="BASE_URL",
        help="Base URL of the deployed API (without trailing slash), e.g. https://abc.execute-api.ap-south-1.amazonaws.com",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    health_url = f"{base_url}/health"
    webhook_url = f"{base_url}/telegram/webhook"

    print(f"\nSmoke testing: {base_url}")
    print("=" * 60)

    # ── Test (a): GET /health ─────────────────────────────────────────────────
    print("\nTest a) GET /health")
    status, body = _http("GET", health_url)
    _assert(status == 200, f"Status 200 (got {status})")
    _assert(body.get("ok") is True, "ok=True in response", str(body))
    print(f"         Response: {body}")

    # ── Test (b): POST /telegram/webhook WITHOUT secret ───────────────────────
    print("\nTest b) POST /telegram/webhook WITHOUT secret header → expect 403")
    status, body = _http(
        "POST",
        webhook_url,
        headers={"Content-Type": "application/json"},
        body=_fake_update(111111),
    )
    _assert(status == 403, f"Status 403 (got {status})", str(body))
    print(f"         Response: {body}")

    # ── Test (c): POST /telegram/webhook WITH correct secret ─────────────────
    print("\nTest c) POST /telegram/webhook WITH correct secret → expect 200")
    secret = _get_secret("TELEGRAM_WEBHOOK_SECRET", "/parali/telegram_webhook_secret")
    if not secret:
        print(
            "  ⚠️  TELEGRAM_WEBHOOK_SECRET not set — skipping authenticated POST test.\n"
            "     Export TELEGRAM_WEBHOOK_SECRET to run the full suite.",
            file=sys.stderr,
        )
        sys.exit(0)

    status, body = _http(
        "POST",
        webhook_url,
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": secret,
        },
        body=_fake_update(222222),
    )
    _assert(status == 200, f"Status 200 (got {status})", str(body))
    _assert(body.get("ok") is True, "ok=True in response", str(body))
    print(f"         Response: {body}")

    print("\n" + "=" * 60)
    print("✅  All smoke tests passed.")


if __name__ == "__main__":
    main()
