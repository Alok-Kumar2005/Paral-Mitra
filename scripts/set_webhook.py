#!/usr/bin/env python3
"""Register or delete the Telegram webhook for Parali Mitra.

Usage:
    python scripts/set_webhook.py --url https://abc.execute-api.ap-south-1.amazonaws.com/telegram/webhook
    python scripts/set_webhook.py --delete

The script reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from:
  1. Environment variables (SECRET_MODE=env)
  2. AWS SSM Parameter Store at /parali/telegram_bot_token and
     /parali/telegram_webhook_secret (SECRET_MODE=ssm)

After setWebhook / deleteWebhook, it always calls getWebhookInfo and prints:
  - url
  - pending_update_count
  - last_error_message

SECURITY: The bot token is NEVER printed to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error


def _get_secret(env_var: str, ssm_name: str) -> str:
    """Read a secret from env var (primary) or SSM (fallback)."""
    val = os.environ.get(env_var, "").strip()
    if val:
        return val

    # SSM fallback (only when running locally with AWS credentials)
    try:
        import boto3
        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_DEFAULT_REGION", "ap-south-1"))
        resp = ssm.get_parameter(Name=ssm_name, WithDecryption=True)
        val = resp["Parameter"]["Value"].strip()
        if val:
            return val
    except Exception as exc:  # noqa: BLE001
        print(f"[SSM] Could not read {ssm_name}: {exc}", file=sys.stderr)

    return ""


def _telegram_call(token: str, method: str, payload: dict | None = None) -> dict:
    """Call a Telegram Bot API method. Returns the JSON response."""
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload or {}).encode("utf-8") if payload else b"{}"
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {body}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register or delete Parali Mitra Telegram webhook."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--url",
        metavar="WEBHOOK_URL",
        help="Full HTTPS URL to register as Telegram webhook.",
    )
    group.add_argument(
        "--delete",
        action="store_true",
        help="Remove the currently registered webhook.",
    )
    args = parser.parse_args()

    # ── Read secrets ──────────────────────────────────────────────────────────
    token = _get_secret("TELEGRAM_BOT_TOKEN", "/parali/telegram_bot_token")
    if not token:
        print(
            "ERROR: TELEGRAM_BOT_TOKEN is not set (env) and SSM read failed.\n"
            "Export it as an environment variable or ensure AWS credentials are configured.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Redact token for display — show only the first 8 chars (bot ID prefix)
    token_prefix = token[:8] + "..." if len(token) > 8 else "***"
    print(f"Using bot token: {token_prefix}")

    # ── setWebhook / deleteWebhook ────────────────────────────────────────────
    if args.delete:
        print("Calling deleteWebhook ...")
        result = _telegram_call(token, "deleteWebhook", {"drop_pending_updates": False})
        print(f"deleteWebhook result: {result}")
    else:
        secret = _get_secret("TELEGRAM_WEBHOOK_SECRET", "/parali/telegram_webhook_secret")
        if not secret:
            print(
                "ERROR: TELEGRAM_WEBHOOK_SECRET is not set.\n"
                "Export it as an environment variable or ensure SSM has /parali/telegram_webhook_secret.",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"Registering webhook: {args.url}")
        payload = {
            "url": args.url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        }
        result = _telegram_call(token, "setWebhook", payload)
        print(f"setWebhook result: ok={result.get('ok')} description={result.get('description')}")

    # ── Always print webhook info ─────────────────────────────────────────────
    print("\nFetching getWebhookInfo ...")
    info_result = _telegram_call(token, "getWebhookInfo")
    info: dict = info_result.get("result", {})

    print("\n── Webhook Info ─────────────────────────────────────────────")
    print(f"  url:                  {info.get('url', '(none)')}")
    print(f"  pending_update_count: {info.get('pending_update_count', 0)}")
    last_error = info.get("last_error_message")
    if last_error:
        print(f"  last_error_message:   {last_error}")
        last_error_date = info.get("last_error_date")
        if last_error_date:
            print(f"  last_error_date:      {last_error_date}")
    else:
        print("  last_error_message:   (none)")
    print("─" * 60)


if __name__ == "__main__":
    main()
