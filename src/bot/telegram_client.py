"""Telegram Bot API asynchronous HTTP client using httpx.

Features:
- Pure httpx async client (no heavy bot frameworks for AWS Lambda / ARM64).
- Safe parse_mode formatting and fallbacks.
- Auto-splitting of messages exceeding Telegram's 4096-character limit.
- Resilient 429 Too Many Requests rate limit handling with retry_after backoff.
- Support for sendMessage, sendChatAction, answerCallbackQuery, getFile/download,
  setWebhook, deleteWebhook, and getUpdates (long polling).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE: str = "https://api.telegram.org"
TELEGRAM_MAX_MESSAGE_LENGTH: int = 4096


class TelegramApiError(Exception):
    """Raised when Telegram Bot API returns an error response."""

    def __init__(
        self,
        status_code: int,
        description: str,
        error_code: int | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"Telegram API error {status_code} ({error_code}): {description}")
        self.status_code = status_code
        self.description = description
        self.error_code = error_code
        self.parameters = parameters or {}


def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for Telegram MarkdownV2 parse mode."""
    # Characters that must be escaped in MarkdownV2 outside code blocks:
    # _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def escape_html(text: str) -> str:
    """Escapes HTML special characters for Telegram HTML parse mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def split_message_text(text: str, max_length: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    """Splits a long message into chunks of at most `max_length` characters.

    Attempts to split at newlines or spaces to avoid breaking sentences/words.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text.strip()

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Try to find a newline within limit
        split_idx = remaining.rfind("\n", 0, max_length)
        if split_idx == -1 or split_idx < max_length // 3:
            # Try to find a space within limit
            split_idx = remaining.rfind(" ", 0, max_length)

        if split_idx == -1 or split_idx < max_length // 4:
            # Fall back to hard split
            split_idx = max_length

        chunk = remaining[:split_idx].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_idx:].strip()

    return chunks if chunks else [text]


class TelegramClient:
    """Asynchronous HTTP client for Telegram Bot API."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str = TELEGRAM_API_BASE,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._external_client = http_client is not None
        self._client = http_client or httpx.AsyncClient(timeout=timeout)

    @property
    def bot_url(self) -> str:
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required but not set.")
        return f"{self.base_url}/bot{self.token}"

    @property
    def file_url(self) -> str:
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required but not set.")
        return f"{self.base_url}/file/bot{self.token}"

    async def close(self) -> None:
        """Closes internal HTTP client if owned."""
        if not self._external_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> TelegramClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def _request(
        self,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Performs a POST request to Telegram Bot API with 429 rate limit backoff."""
        url = f"{self.bot_url}/{endpoint}"
        retries = 0

        while True:
            try:
                response = await self._client.post(url, json=json_data)
            except httpx.RequestError as exc:
                logger.error("HTTP request error contacting Telegram %s: %s", endpoint, exc)
                raise TelegramApiError(500, f"Request failed: {exc}") from exc

            # Handle rate limiting (429)
            if response.status_code == 429:
                retries += 1
                if retries > max_retries:
                    logger.error("Exceeded max retries on 429 for endpoint %s", endpoint)
                    raise TelegramApiError(429, "Too Many Requests (max retries exceeded)")

                try:
                    err_json = response.json()
                    retry_after = err_json.get("parameters", {}).get("retry_after", 1)
                except Exception:
                    retry_after = int(response.headers.get("Retry-After", 1))

                logger.warning(
                    "Telegram 429 rate limit hit on %s. Retrying after %s seconds (attempt %d/%d)",
                    endpoint,
                    retry_after,
                    retries,
                    max_retries,
                )
                await asyncio.sleep(retry_after)
                continue

            try:
                data = response.json()
            except Exception as exc:
                logger.error("Failed to parse Telegram JSON response: %s", response.text)
                raise TelegramApiError(
                    response.status_code,
                    f"Non-JSON response: {response.text[:200]}",
                ) from exc

            if not response.is_success or not data.get("ok"):
                description = data.get("description", "Unknown Telegram error")
                error_code = data.get("error_code", response.status_code)
                parameters = data.get("parameters", {})
                logger.error(
                    "Telegram API returned error %s for %s: %s",
                    error_code,
                    endpoint,
                    description,
                )
                raise TelegramApiError(
                    status_code=response.status_code,
                    description=description,
                    error_code=error_code,
                    parameters=parameters,
                )

            return data.get("result", {})

    async def sendMessage(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict[str, Any] | None = None,
        disable_web_page_preview: bool = True,
    ) -> list[dict[str, Any]]:
        """Sends one or more messages to a chat, splitting cleanly if text > 4096 chars.

        If parse_mode causes a Bad Request (e.g. invalid entities), falls back to plain text.
        """
        chunks = split_message_text(text, max_length=TELEGRAM_MAX_MESSAGE_LENGTH)
        results: list[dict[str, Any]] = []

        for idx, chunk in enumerate(chunks):
            # Only attach reply_markup to the final message chunk
            is_last = (idx == len(chunks) - 1)
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": disable_web_page_preview,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if is_last and reply_markup:
                payload["reply_markup"] = reply_markup

            try:
                res = await self._request("sendMessage", payload)
                results.append(res)
            except TelegramApiError as exc:
                # If markup parsing failed, retry once without parse_mode
                if parse_mode and "can't parse entities" in exc.description.lower():
                    logger.warning("Telegram parse error on %s; retrying as plain text", parse_mode)
                    payload.pop("parse_mode", None)
                    res = await self._request("sendMessage", payload)
                    results.append(res)
                else:
                    raise

        return results


    async def sendChatAction(
        self,
        chat_id: int | str,
        action: str = "typing",
    ) -> dict[str, Any]:
        """Broadcasts a chat action indicator (e.g. 'typing')."""
        payload = {
            "chat_id": chat_id,
            "action": action,
        }
        return await self._request("sendChatAction", payload)

    async def answerCallbackQuery(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
        url: str | None = None,
        cache_time: int = 0,
    ) -> dict[str, Any]:
        """Acknowledges an incoming inline button callback query."""
        payload: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
            "cache_time": cache_time,
        }
        if text:
            payload["text"] = text
        if url:
            payload["url"] = url
        return await self._request("answerCallbackQuery", payload)

    async def getFile(self, file_id: str) -> dict[str, Any]:
        """Fetches metadata for a file, including file_path for download."""
        payload = {"file_id": file_id}
        return await self._request("getFile", payload)

    async def downloadFile(self, file_path: str) -> bytes:
        """Downloads raw binary file contents using the file_path from getFile."""
        url = f"{self.file_url}/{file_path}"
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.content
        except httpx.RequestError as exc:
            logger.error("Failed to download file from %s: %s", url, exc)
            raise TelegramApiError(500, f"File download failed: {exc}") from exc

    async def setWebhook(
        self,
        url: str,
        secret_token: str | None = None,
        allowed_updates: list[str] | None = None,
        drop_pending_updates: bool = False,
    ) -> dict[str, Any]:
        """Configures Telegram webhook endpoint URL."""
        payload: dict[str, Any] = {
            "url": url,
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates
        return await self._request("setWebhook", payload)

    async def deleteWebhook(
        self,
        drop_pending_updates: bool = False,
    ) -> dict[str, Any]:
        """Removes webhook integration, allowing long-polling getUpdates."""
        payload = {"drop_pending_updates": drop_pending_updates}
        return await self._request("deleteWebhook", payload)

    async def getUpdates(
        self,
        offset: int | None = None,
        limit: int = 100,
        timeout: int = 30,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Long-polling update retrieval for local development and runners."""
        payload: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if offset is not None:
            payload["offset"] = offset
        if allowed_updates is not None:
            payload["allowed_updates"] = allowed_updates

        url = f"{self.bot_url}/getUpdates"
        try:
            # Using timeout + 5 for HTTP client timeout to allow Telegram server long-polling
            resp = await self._client.post(url, json=payload, timeout=timeout + 5)
            data = resp.json()
            if not data.get("ok"):
                raise TelegramApiError(
                    resp.status_code,
                    data.get("description", "getUpdates failed"),
                    data.get("error_code"),
                )
            return data.get("result", [])
        except httpx.TimeoutException:
            # Long poll timeout returned empty list
            return []
        except httpx.RequestError as exc:
            logger.error("getUpdates request error: %s", exc)
            raise TelegramApiError(500, f"getUpdates failed: {exc}") from exc

    # ── Method aliases for snake_case and camelCase compatibility ───────────
    send_message = sendMessage
    send_chat_action = sendChatAction
    answer_callback_query = answerCallbackQuery
    get_file = getFile
    download_file = downloadFile
    set_webhook = setWebhook
    delete_webhook = deleteWebhook
    get_updates = getUpdates

