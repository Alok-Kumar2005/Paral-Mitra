"""Local long-polling Telegram runner for Parali Mitra.

Enables local development and debugging without setting up public HTTPS webhooks.
Deletes webhook on startup, fetches updates via getUpdates, and routes them to router.handle_update.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv

from scripts.seed import seed_database
from src.bot.router import handle_update
from src.bot.telegram_client import TelegramClient
from src.common.db import DatabaseClient, get_db_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("parali_mitra.local_polling")


class LocalPoller:
    """Manages the long-polling event loop."""

    def __init__(
        self,
        token: str | None = None,
        db: DatabaseClient | None = None,
        poll_timeout: int = 30,
    ) -> None:
        self.client = TelegramClient(token=token)
        self.db = db or get_db_client()
        self.poll_timeout = poll_timeout
        self.running = True
        self.offset: int | None = None

    async def start(self) -> None:
        """Starts the polling loop after removing any active webhook."""
        logger.info("Initializing Parali Mitra local polling runner...")

        # Ensure seed data is present in database for local test runs
        try:
            seed_database(db=self.db)
            logger.info("Seed data verified in database backend.")
        except Exception as exc:
            logger.warning("Seed initialization skipped or failed: %s", exc)

        # Remove existing webhook to allow getUpdates
        try:
            logger.info("Deleting active Telegram webhook...")
            await self.client.deleteWebhook(drop_pending_updates=False)
            logger.info("Webhook successfully deleted. Listening for updates...")
        except Exception as exc:
            logger.warning("Could not delete webhook: %s", exc)

        logger.info("🤖 Parali Mitra bot is now live in polling mode! Press Ctrl+C to stop.")

        while self.running:
            try:
                updates = await self.client.getUpdates(
                    offset=self.offset,
                    timeout=self.poll_timeout,
                )

                for update in updates:
                    update_id = update.get("update_id")
                    if update_id is not None:
                        self.offset = update_id + 1

                    try:
                        await handle_update(update, client=self.client, db=self.db)
                    except Exception as exc:
                        logger.exception("Error processing update %s: %s", update_id, exc)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in getUpdates polling loop: %s", exc)
                await asyncio.sleep(2.0)

    async def stop(self) -> None:
        """Stops the poller and closes HTTP client connections."""
        logger.info("Stopping Parali Mitra polling runner...")
        self.running = False
        await self.client.close()
        logger.info("Polling runner stopped.")


async def main_async() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set in environment or .env file!\n"
            "Please add TELEGRAM_BOT_TOKEN=<your_bot_token> to .env to run local polling."
        )
        sys.exit(1)

    poller = LocalPoller(token=token)

    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Received termination signal.")
        poller.running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows does not support add_signal_handler for all signals
            pass

    try:
        await poller.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        await poller.stop()


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Exited.")


if __name__ == "__main__":
    main()
