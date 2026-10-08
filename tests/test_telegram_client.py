"""Unit tests for TelegramClient HTTP wrapper and text utilities."""

from __future__ import annotations

import json
import httpx
import pytest

from src.bot.telegram_client import (
    TelegramApiError,
    TelegramClient,
    escape_html,
    escape_markdown_v2,
    split_message_text,
)


def test_telegram_api_error() -> None:
    err = TelegramApiError(status_code=400, description="Bad Request", error_code=400)
    assert "400" in str(err)
    assert err.description == "Bad Request"


# ── Text utilities tests ──────────────────────────────────────────────────────


def test_escape_markdown_v2() -> None:
    raw = "Hello [World]! Cost: 50.0% & profit = +100 - 20 * (2)."
    escaped = escape_markdown_v2(raw)
    assert r"\[World\]\!" in escaped
    assert r"\=" in escaped
    assert r"\+" in escaped
    assert r"\-" in escaped
    assert r"\*" in escaped
    assert r"\(" in escaped
    assert r"\)" in escaped
    assert r"\." in escaped


def test_escape_html() -> None:
    raw = "Cost < 100 & profit > 50"
    escaped = escape_html(raw)
    assert escaped == "Cost &lt; 100 &amp; profit &gt; 50"


def test_split_message_text_short() -> None:
    text = "Short message"
    chunks = split_message_text(text, max_length=100)
    assert chunks == ["Short message"]


def test_split_message_text_long() -> None:
    text = "Line 1\n" + "A" * 3000 + "\nLine 2\n" + "B" * 2000
    chunks = split_message_text(text, max_length=4000)
    assert len(chunks) == 2
    assert all(len(c) <= 4000 for c in chunks)
    assert "Line 1" in chunks[0]
    assert "Line 2" in chunks[0]
    assert "B" * 2000 in chunks[1]


# ── TelegramClient API tests with MockTransport ───────────────────────────────


@pytest.mark.asyncio
async def test_send_message_basic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/botTEST_TOKEN/sendMessage"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["chat_id"] == 12345
        assert payload["text"] == "Namaste"
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        res = await client.sendMessage(chat_id=12345, text="Namaste")
        assert len(res) == 1
        assert res[0]["message_id"] == 99


@pytest.mark.asyncio
async def test_send_message_splitting() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": call_count}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        long_text = ("Hello farmer\n" * 500)  # > 4096 chars
        res = await client.sendMessage(chat_id=12345, text=long_text)
        assert len(res) >= 2
        assert call_count >= 2


@pytest.mark.asyncio
async def test_send_message_parse_mode_fallback() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        payload = json.loads(request.content.decode("utf-8"))
        if attempts == 1:
            assert payload.get("parse_mode") == "MarkdownV2"
            return httpx.Response(
                400,
                json={"ok": False, "error_code": 400, "description": "Bad Request: can't parse entities"},
            )
        # Second attempt should omit parse_mode
        assert "parse_mode" not in payload
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 101}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        res = await client.sendMessage(chat_id=12345, text="Bad [markup", parse_mode="MarkdownV2")
        assert len(res) == 1
        assert res[0]["message_id"] == 101
        assert attempts == 2


@pytest.mark.asyncio
async def test_send_chat_action() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/botTEST_TOKEN/sendChatAction"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["action"] == "typing"
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        res = await client.sendChatAction(chat_id=12345, action="typing")
        assert res is True


@pytest.mark.asyncio
async def test_answer_callback_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/botTEST_TOKEN/answerCallbackQuery"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["callback_query_id"] == "cb_999"
        assert payload["text"] == "Language saved"
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        res = await client.answerCallbackQuery(callback_query_id="cb_999", text="Language saved")
        assert res is True


@pytest.mark.asyncio
async def test_get_file_and_download() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/botTEST_TOKEN/getFile":
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "voice/file_123.oga"}})
        if request.url.path == "/file/botTEST_TOKEN/voice/file_123.oga":
            return httpx.Response(200, content=b"AUDIO_DATA")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        file_meta = await client.getFile("file_123")
        assert file_meta["file_path"] == "voice/file_123.oga"

        content = await client.downloadFile(file_meta["file_path"])
        assert content == b"AUDIO_DATA"


@pytest.mark.asyncio
async def test_set_and_delete_webhook() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/botTEST_TOKEN/setWebhook":
            return httpx.Response(200, json={"ok": True, "result": True})
        if request.url.path == "/botTEST_TOKEN/deleteWebhook":
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        assert await client.setWebhook(url="https://api.example.com/webhook") is True
        assert await client.deleteWebhook() is True


@pytest.mark.asyncio
async def test_rate_limit_429_retry() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 0}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 4290}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = TelegramClient(token="TEST_TOKEN", http_client=http_client)
        res = await client.sendMessage(chat_id=123, text="Retry test")
        assert len(res) == 1
        assert res[0]["message_id"] == 4290
        assert attempts == 2
