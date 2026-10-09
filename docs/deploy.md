# Deploying Parali Mitra to AWS — Step-by-Step

> **⚠️ WARNING: NEVER run local polling (`src/bot/local_polling.py`) with your
> production bot token.** Telegram only allows one active receiver at a time.
> Running local polling while the webhook is registered will cause your webhook
> to stop receiving messages silently. Always use a separate bot token for local
> development.

---

## Prerequisites

- AWS CLI v2 installed and configured (`aws configure`)
- AWS SAM CLI installed (`sam --version`)
- Python 3.12 on your local machine
- A Neon PostgreSQL database created and migrations applied (`python scripts/migrate.py`)
- A NASA FIRMS MAP_KEY (free at https://firms.modaps.eosdis.nasa.gov/api/area/)
- A Telegram bot token from @BotFather

---

## Step 0: Build the Lambda Package

Run the build script first. It cross-compiles arm64 wheels — no Docker needed.

```powershell
# From the project root
python scripts/build_lambda.py
```

This creates `build/lambda/` with all runtime dependencies and source code.
The unzipped size is printed; it must be < 240 MB.

---

## Step 1: Deploy the Stack

Use **single quotes** around values containing special characters (`&`, `?`, `=`).
PowerShell requires single quotes to prevent shell interpretation of `&`.

```powershell
sam deploy `
    --template-file infra/template.yaml `
    --stack-name parali-mitra `
    --region ap-south-1 `
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM `
    --resolve-s3 `
    --parameter-overrides `
        SecretMode=env `
        ModelId='anthropic.claude-3-5-sonnet-20241022-v2:0' `
        BedrockRegion='ap-south-1' `
        TelegramBotToken='<your-bot-token>' `
        TelegramWebhookSecret='<your-32-char-random-secret>' `
        'DatabaseUrl=postgresql://user:pass@host.neon.tech/db?sslmode=require' `
        FirmsMapKey='<your-firms-key>'
```

> **Note:** The `DatabaseUrl` parameter is wrapped in single quotes to protect
> the `?` and `&` characters in the Neon connection string.

On the first deploy, SAM may ask for an S3 bucket to store deployment artifacts.
`--resolve-s3` creates one automatically.

---

## Step 2: Register the Telegram Webhook

After a successful deploy, copy the `WebhookUrl` from the stack outputs, then:

```powershell
# Get the webhook URL from CloudFormation outputs
$WebhookUrl = (aws cloudformation describe-stacks `
    --stack-name parali-mitra `
    --region ap-south-1 `
    --query 'Stacks[0].Outputs[?OutputKey==`WebhookUrl`].OutputValue' `
    --output text)

Write-Host "Webhook URL: $WebhookUrl"

# Register it with Telegram (reads TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET from env)
$env:TELEGRAM_BOT_TOKEN = '<your-bot-token>'
$env:TELEGRAM_WEBHOOK_SECRET = '<your-32-char-random-secret>'

python scripts/set_webhook.py --url $WebhookUrl
```

---

## Step 3: Verify Deployment

```powershell
# Smoke test — also reads TELEGRAM_WEBHOOK_SECRET from env
$HealthUrl = (aws cloudformation describe-stacks `
    --stack-name parali-mitra `
    --region ap-south-1 `
    --query 'Stacks[0].Outputs[?OutputKey==`HealthUrl`].OutputValue' `
    --output text)

# Extract base URL (remove the /health suffix)
$BaseUrl = $HealthUrl -replace '/health$', ''

python scripts/smoke_test.py --url $BaseUrl
```

---

## Viewing Logs

```powershell
# Tail the webhook receiver logs (live)
sam logs --tail --stack-name parali-mitra --name ReceiverFunction --region ap-south-1

# Tail the worker (agent) logs (live)
sam logs --tail --stack-name parali-mitra --name WorkerFunction --region ap-south-1

# Tail the ingest scheduler logs
sam logs --tail --stack-name parali-mitra --name IngestFunction --region ap-south-1

# Filter for errors only
sam logs --stack-name parali-mitra --name WorkerFunction --region ap-south-1 `
    --filter-pattern 'ERROR'
```

---

## Checking the Dead-Letter Queue (DLQ)

Messages that fail all 3 delivery attempts land in the DLQ.

```powershell
# Get the DLQ URL from stack outputs
$DlqUrl = (aws cloudformation describe-stacks `
    --stack-name parali-mitra `
    --region ap-south-1 `
    --query 'Stacks[0].Outputs[?OutputKey==`DlqUrl`].OutputValue' `
    --output text)

# Check how many messages are in the DLQ
aws sqs get-queue-attributes `
    --queue-url $DlqUrl `
    --attribute-names ApproximateNumberOfMessages `
    --region ap-south-1

# Peek at DLQ messages (does NOT delete them)
aws sqs receive-message `
    --queue-url $DlqUrl `
    --max-number-of-messages 5 `
    --region ap-south-1
```

A CloudWatch alarm (`parali-mitra-dlq-depth`) fires when the DLQ depth > 0.

---

## Rolling Back

### Option A: Roll back to the previous CloudFormation version

```powershell
# If the deploy just failed, SAM/CloudFormation will auto-rollback.
# To manually trigger rollback to last stable version:
aws cloudformation rollback-stack `
    --stack-name parali-mitra `
    --region ap-south-1
```

### Option B: Delete the stack entirely (destructive)

```powershell
# WARNING: This deletes all Lambda functions, queues, and log groups.
# It does NOT affect Neon PostgreSQL data (external database).
sam delete --stack-name parali-mitra --region ap-south-1
```

### Option C: Re-deploy a previous build

```powershell
# Re-run the deploy command with the same or older build/lambda/ directory.
# The Lambda code version is what you copied into build/lambda/.
```

---

## Updating Secrets

If you need to rotate the bot token or webhook secret:

```powershell
# Re-deploy with updated parameters (only secrets change; no code rebuild needed)
sam deploy `
    --template-file infra/template.yaml `
    --stack-name parali-mitra `
    --region ap-south-1 `
    --capabilities CAPABILITY_IAM `
    --no-confirm-changeset `
    --parameter-overrides `
        SecretMode=env `
        TelegramBotToken='<new-token>' `
        TelegramWebhookSecret='<new-secret>' `
        'DatabaseUrl=postgresql://user:pass@host.neon.tech/db?sslmode=require' `
        FirmsMapKey='<firms-key>'

# Re-register the webhook with the new secret
python scripts/set_webhook.py --url $WebhookUrl
```

---

## SSM-Mode Alternative (More Secure)

If you switch to `SecretMode=ssm`, store secrets in SSM Parameter Store first:

```powershell
# Store secrets (SecureString encrypted with AWS managed key)
aws ssm put-parameter --name '/parali/telegram_bot_token' `
    --value '<token>' --type SecureString --region ap-south-1

aws ssm put-parameter --name '/parali/telegram_webhook_secret' `
    --value '<secret>' --type SecureString --region ap-south-1

aws ssm put-parameter --name '/parali/database_url' `
    --value 'postgresql://user:pass@host.neon.tech/db?sslmode=require' `
    --type SecureString --region ap-south-1

aws ssm put-parameter --name '/parali/firms_map_key' `
    --value '<key>' --type SecureString --region ap-south-1

# Then deploy with SecretMode=ssm (no secret values in CLI args)
sam deploy --no-build --template-file infra/template.yaml `
    --stack-name parali-mitra --region ap-south-1 `
    --capabilities CAPABILITY_IAM `
    --parameter-overrides SecretMode=ssm
```

---

## ⚠️ Safety Rules

1. **Never run local polling with the production bot token.** If you do, the
   webhook will stop working. Use a separate `@TestParaliMitraBot` for local dev.

2. **Never commit `.env` to git.** The `.gitignore` excludes it, but double-check.

3. **The DLQ is FIFO** — messages are preserved in order. A DLQ alarm means
   real farmer messages were dropped; investigate promptly.

4. **Neon database** is external to AWS. Stack deletion does NOT delete farmer data.
   Migrations must be applied manually via `python scripts/migrate.py`.
