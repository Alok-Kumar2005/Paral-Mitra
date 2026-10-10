"""Deploy helper script for Parali Mitra.

Reads configuration directly from .env and executes `sam deploy` with properly
formatted arguments, avoiding shell quoting and redirection errors in Windows CMD/PowerShell.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"❌ .env not found at {env_path}")
        return 1

    load_dotenv(dotenv_path=env_path)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    db_url = os.getenv("DATABASE_URL")
    firms_key = os.getenv("FIRMS_MAP_KEY")
    model_id = os.getenv("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    region = os.getenv("AWS_REGION", "ap-south-1")

    missing = []
    if not bot_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not webhook_secret:
        missing.append("TELEGRAM_WEBHOOK_SECRET")
    if not db_url:
        missing.append("DATABASE_URL")
    if not firms_key:
        missing.append("FIRMS_MAP_KEY")

    if missing:
        print(f"❌ Missing required environment variables in .env: {', '.join(missing)}")
        return 1

    sam_exe = shutil.which("sam") or shutil.which("sam.cmd")
    if not sam_exe:
        print("❌ 'sam' CLI executable not found in PATH.")
        print("Please ensure AWS SAM CLI is installed (https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)")
        return 1

    # Bedrock region
    bedrock_region = os.getenv("BEDROCK_REGION", region)

    params = [
        "SecretMode=env",
        f"ModelId={model_id}",
        f"BedrockRegion={bedrock_region}",
        f"TelegramBotToken={bot_token}",
        f"TelegramWebhookSecret={webhook_secret}",
        f"DatabaseUrl={db_url}",
        f"FirmsMapKey={firms_key}",
    ]

    cmd = [
        sam_exe,
        "deploy",
        "--template-file",
        str(ROOT / "infra" / "template.yaml"),
        "--stack-name",
        "parali-mitra",
        "--region",
        region,
        "--capabilities",
        "CAPABILITY_IAM",
        "CAPABILITY_NAMED_IAM",
        "--resolve-s3",
        "--parameter-overrides",
        *params,
    ]

    print("🚀 Starting SAM deploy using credentials from .env...")
    print(f"   Stack: parali-mitra | Region: {region}")
    
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
