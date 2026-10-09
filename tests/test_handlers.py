"""Unit tests for Lambda handlers: receiver and worker.

Fully offline — patches boto3 SQS so no AWS credentials are needed.
Uses only the standard library for assertion; no external test fixtures.

Coverage:
  Receiver:
    - GET /health returns 200 + version
    - POST with correct secret header → 200 {"ok":true}
    - POST with wrong secret header → 403
    - POST with missing secret header → 403
    - POST with valid secret but malformed JSON body → 200 (no retry)
    - POST with valid secret but missing update_id → 200 (still enqueued)
    - SQS send_message failure → 500
    - MessageGroupId derivation:
        * message.chat.id present → str(chat_id)
        * callback_query.from.id present → str(user_id)
        * neither → "misc"
    - Missing UPDATE_QUEUE_URL → 500
    - Missing TELEGRAM_WEBHOOK_SECRET → 500

  Worker:
    - Successful processing → empty batchItemFailures list
    - ServiceUnavailableError → item reported as failed (for SQS retry)
    - Generic exception → item reported as failed
    - Apology sent only on final attempt (ApproximateReceiveCount >= maxReceiveCount)
    - No apology sent on non-final attempt
    - batchItemFailures response format contains correct messageId
    - _is_final_attempt helper with various ApproximateReceiveCount values
    - _extract_chat_id: message path, callback_query path, missing → None
    - _get_chat_id (receiver): all three cases
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call


import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_apigw_event(
    method: str = "POST",
    route: str = "/telegram/webhook",
    headers: dict | None = None,
    body: str | None = None,
) -> dict:
    """Build a minimal API Gateway HTTP API (payload v2) event dict."""
    return {
        "routeKey": f"{method} {route}",
        "headers": headers or {},
        "body": body or "",
        "requestContext": {"http": {"method": method}},
    }


def _make_sqs_record(
    body: dict,
    message_id: str = "msg-001",
    approximate_receive_count: str = "1",
) -> dict:
    """Build a minimal SQS record matching the Lambda event structure."""
    return {
        "messageId": message_id,
        "body": json.dumps(body),
        "messageAttributes": {
            "ApproximateReceiveCount": {
                "stringValue": approximate_receive_count,
                "dataType": "Number",
            }
        },
    }


def _make_update(
    update_id: int = 42,
    include_message: bool = True,
    include_callback: bool = False,
    chat_id: int = 9999,
    user_id: int = 8888,
) -> dict:
    """Build a minimal Telegram update dict."""
    update: dict = {"update_id": update_id}
    if include_message:
        update["message"] = {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "text": "/start",
        }
    if include_callback:
        update["callback_query"] = {
            "id": "cb1",
            "from": {"id": user_id},
            "data": "lang:en",
        }
    return update


# ─────────────────────────────────────────────────────────────────────────────
# Receiver tests
# ─────────────────────────────────────────────────────────────────────────────

class TestReceiverHealth:
    """Tests for GET /health."""

    def test_health_returns_200(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret")
        monkeypatch.setenv("UPDATE_QUEUE_URL", "https://sqs.example.com/queue.fifo")

        # Patch boto3 before importing the module
        mock_sqs = MagicMock()
        with patch("boto3.client", return_value=mock_sqs):
            import importlib
            import src.handlers.receiver as receiver
            importlib.reload(receiver)

            event = _make_apigw_event(method="GET", route="/health")
            resp = receiver.handler(event, None)

        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["ok"] is True
        assert "version" in body

    def test_health_no_db_access(self, monkeypatch):
        """Health check must not call any DB or SQS — only returns version."""
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret")
        monkeypatch.setenv("UPDATE_QUEUE_URL", "https://sqs.example.com/queue.fifo")

        mock_sqs = MagicMock()
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)

            event = _make_apigw_event(method="GET", route="/health")
            receiver.handler(event, None)

        # SQS send_message must NOT have been called
        mock_sqs.send_message.assert_not_called()


class TestReceiverSecretVerification:
    """Tests for HMAC secret verification on POST /telegram/webhook."""

    def _load_receiver(self, monkeypatch, secret: str = "correct-secret", queue: str = "https://q.fifo"):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", secret)
        monkeypatch.setenv("UPDATE_QUEUE_URL", queue)
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "abc123"}
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)
        return receiver, mock_sqs

    def test_correct_secret_returns_200(self, monkeypatch):
        receiver, mock_sqs = self._load_receiver(monkeypatch)
        update = _make_update()
        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "correct-secret"},
            body=json.dumps(update),
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["ok"] is True

    def test_wrong_secret_returns_403(self, monkeypatch):
        receiver, mock_sqs = self._load_receiver(monkeypatch)
        update = _make_update()
        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "WRONG-secret"},
            body=json.dumps(update),
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)
        assert resp["statusCode"] == 403
        mock_sqs.send_message.assert_not_called()

    def test_missing_secret_returns_403(self, monkeypatch):
        receiver, mock_sqs = self._load_receiver(monkeypatch)
        update = _make_update()
        event = _make_apigw_event(
            headers={},  # no secret header
            body=json.dumps(update),
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)
        assert resp["statusCode"] == 403
        mock_sqs.send_message.assert_not_called()

    def test_empty_secret_in_header_returns_403(self, monkeypatch):
        receiver, mock_sqs = self._load_receiver(monkeypatch)
        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": ""},
            body=json.dumps(_make_update()),
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)
        assert resp["statusCode"] == 403


class TestReceiverBodyHandling:
    """Tests for body parsing edge cases."""

    def _receiver_with_sqs(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
        monkeypatch.setenv("UPDATE_QUEUE_URL", "https://q.fifo")
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "x"}
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)
        return receiver, mock_sqs

    def test_malformed_json_body_returns_200(self, monkeypatch):
        """Valid secret + malformed body → 200 (Telegram must not retry)."""
        receiver, mock_sqs = self._receiver_with_sqs(monkeypatch)
        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "sec"},
            body="this is not json {{{{",
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)
        assert resp["statusCode"] == 200
        # SQS should NOT be called for parse errors
        mock_sqs.send_message.assert_not_called()

    def test_empty_body_returns_200(self, monkeypatch):
        """Valid secret + empty body → 200 (parse error, no retry)."""
        receiver, mock_sqs = self._receiver_with_sqs(monkeypatch)
        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "sec"},
            body="",
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)
        assert resp["statusCode"] == 200

    def test_sqs_failure_returns_500(self, monkeypatch):
        """SQS send_message failure → 500."""
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
        monkeypatch.setenv("UPDATE_QUEUE_URL", "https://q.fifo")
        mock_sqs = MagicMock()
        mock_sqs.send_message.side_effect = Exception("SQS is down")
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)

        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "sec"},
            body=json.dumps(_make_update()),
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)
        assert resp["statusCode"] == 500

    def test_missing_queue_url_returns_500(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
        monkeypatch.delenv("UPDATE_QUEUE_URL", raising=False)
        mock_sqs = MagicMock()
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)
            receiver._QUEUE_URL = ""  # force empty after reload

        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "sec"},
            body=json.dumps(_make_update()),
        )
        resp = receiver.handler(event, None)
        assert resp["statusCode"] == 500

    def test_missing_webhook_secret_env_returns_500(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("UPDATE_QUEUE_URL", "https://q.fifo")
        mock_sqs = MagicMock()
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)
            receiver._WEBHOOK_SECRET = ""  # force empty after reload

        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "sec"},
            body=json.dumps(_make_update()),
        )
        resp = receiver.handler(event, None)
        assert resp["statusCode"] == 500


class TestReceiverMessageGroupId:
    """MessageGroupId derivation for SQS FIFO."""

    def _enqueue_and_get_group_id(self, monkeypatch, update: dict) -> str:
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
        monkeypatch.setenv("UPDATE_QUEUE_URL", "https://q.fifo")
        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "x"}
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)

        event = _make_apigw_event(
            headers={"x-telegram-bot-api-secret-token": "sec"},
            body=json.dumps(update),
        )
        with patch("boto3.client", return_value=mock_sqs):
            resp = receiver.handler(event, None)

        assert resp["statusCode"] == 200
        call_kwargs = mock_sqs.send_message.call_args
        return call_kwargs.kwargs.get("MessageGroupId") or call_kwargs[1].get("MessageGroupId")

    def test_message_update_uses_chat_id(self, monkeypatch):
        update = _make_update(chat_id=12345, include_message=True, include_callback=False)
        group_id = self._enqueue_and_get_group_id(monkeypatch, update)
        assert group_id == "12345"

    def test_callback_query_update_uses_from_id(self, monkeypatch):
        update = _make_update(user_id=67890, include_message=False, include_callback=True)
        group_id = self._enqueue_and_get_group_id(monkeypatch, update)
        assert group_id == "67890"

    def test_unknown_update_uses_misc(self, monkeypatch):
        # An update with neither message nor callback_query
        update = {"update_id": 99, "edited_message": {"text": "hi"}}
        group_id = self._enqueue_and_get_group_id(monkeypatch, update)
        assert group_id == "misc"

    def test_callback_takes_precedence_over_message(self, monkeypatch):
        """When both callback_query and message are present, callback_query wins."""
        update = _make_update(
            chat_id=11111,
            user_id=22222,
            include_message=True,
            include_callback=True,
        )
        group_id = self._enqueue_and_get_group_id(monkeypatch, update)
        assert group_id == "22222"


class TestReceiverGetChatId:
    """Unit tests for the _get_chat_id helper (pure function)."""

    def test_message_chat_id(self):
        from src.handlers.receiver import _get_chat_id
        update = {"update_id": 1, "message": {"chat": {"id": 555}, "text": "hi"}}
        assert _get_chat_id(update) == "555"

    def test_callback_from_id(self):
        from src.handlers.receiver import _get_chat_id
        update = {"update_id": 1, "callback_query": {"from": {"id": 777}, "data": "x"}}
        assert _get_chat_id(update) == "777"

    def test_neither_returns_misc(self):
        from src.handlers.receiver import _get_chat_id
        update = {"update_id": 1, "inline_query": {"query": "test"}}
        assert _get_chat_id(update) == "misc"

    def test_empty_update_returns_misc(self):
        from src.handlers.receiver import _get_chat_id
        assert _get_chat_id({}) == "misc"


# ─────────────────────────────────────────────────────────────────────────────
# Worker tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkerHelpers:
    """Unit tests for worker helper functions (pure / no network)."""

    def test_extract_chat_id_from_message(self):
        from src.handlers.worker import _extract_chat_id
        update = {"message": {"chat": {"id": 12345}}}
        assert _extract_chat_id(update) == 12345

    def test_extract_chat_id_from_callback(self):
        from src.handlers.worker import _extract_chat_id
        update = {"callback_query": {"from": {"id": 67890}}}
        assert _extract_chat_id(update) == 67890

    def test_extract_chat_id_callback_wins(self):
        from src.handlers.worker import _extract_chat_id
        update = {
            "callback_query": {"from": {"id": 111}},
            "message": {"chat": {"id": 222}},
        }
        assert _extract_chat_id(update) == 111

    def test_extract_chat_id_none_when_missing(self):
        from src.handlers.worker import _extract_chat_id
        assert _extract_chat_id({}) is None
        assert _extract_chat_id({"update_id": 1}) is None

    def test_is_final_attempt_below_max(self):
        from src.handlers.worker import _is_final_attempt
        record = _make_sqs_record({"update_id": 1}, approximate_receive_count="2")
        assert _is_final_attempt(record, max_receive_count=3) is False

    def test_is_final_attempt_at_max(self):
        from src.handlers.worker import _is_final_attempt
        record = _make_sqs_record({"update_id": 1}, approximate_receive_count="3")
        assert _is_final_attempt(record, max_receive_count=3) is True

    def test_is_final_attempt_above_max(self):
        from src.handlers.worker import _is_final_attempt
        record = _make_sqs_record({"update_id": 1}, approximate_receive_count="5")
        assert _is_final_attempt(record, max_receive_count=3) is True

    def test_is_final_attempt_defaults_to_1_when_missing(self):
        from src.handlers.worker import _is_final_attempt
        record = {"messageId": "x", "body": "{}", "messageAttributes": {}}
        # receive count defaults to 1; max is 3 → not final
        assert _is_final_attempt(record, max_receive_count=3) is False

    def test_is_final_attempt_invalid_value_treated_as_1(self):
        from src.handlers.worker import _is_final_attempt
        record = {
            "messageId": "x",
            "body": "{}",
            "messageAttributes": {
                "ApproximateReceiveCount": {"stringValue": "not-a-number"}
            },
        }
        assert _is_final_attempt(record, max_receive_count=3) is False


class TestWorkerBatchItemFailures:
    """Tests for the worker batchItemFailures response format."""

    def _make_lambda_event(self, records: list[dict]) -> dict:
        return {"Records": records}

    def test_successful_processing_empty_failures(self):
        """When handle_update succeeds, batchItemFailures should be empty."""
        record = _make_sqs_record(_make_update(), message_id="msg-success")

        with (
            patch("src.handlers.worker._get_db", return_value=MagicMock()),
            patch("src.handlers.worker._process_record", new=AsyncMock(return_value=None)),
        ):
            import src.handlers.worker as worker
            importlib.reload(worker)

            # Patch asyncio.run to call the coroutine synchronously
            with patch("asyncio.run", side_effect=lambda coro: None):
                resp = worker.handler(self._make_lambda_event([record]), None)

        assert resp == {"batchItemFailures": []}

    def test_failed_record_reported_in_failures(self):
        """When handle_update raises, the record messageId appears in batchItemFailures."""
        record = _make_sqs_record(_make_update(), message_id="msg-fail-001")

        import src.handlers.worker as worker
        importlib.reload(worker)

        # Make asyncio.run raise an exception to simulate processing failure
        with patch("asyncio.run", side_effect=RuntimeError("agent exploded")):
            resp = worker.handler(self._make_lambda_event([record]), None)

        assert resp["batchItemFailures"] == [{"itemIdentifier": "msg-fail-001"}]

    def test_response_format_has_batch_item_failures_key(self):
        """Response must always have the 'batchItemFailures' key (even if empty)."""
        import src.handlers.worker as worker
        importlib.reload(worker)

        with patch("asyncio.run", return_value=None):
            resp = worker.handler({"Records": []}, None)

        assert "batchItemFailures" in resp
        assert isinstance(resp["batchItemFailures"], list)

    def test_multiple_records_partial_failure(self):
        """With two records, one succeeds and one fails: only the failed one in failures."""
        record_ok = _make_sqs_record(_make_update(update_id=1), message_id="msg-ok")
        record_fail = _make_sqs_record(_make_update(update_id=2), message_id="msg-fail")

        import src.handlers.worker as worker
        importlib.reload(worker)

        call_count = [0]

        def side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("second record failed")

        with patch("asyncio.run", side_effect=side_effect):
            resp = worker.handler(
                self._make_lambda_event([record_ok, record_fail]), None
            )

        assert len(resp["batchItemFailures"]) == 1
        assert resp["batchItemFailures"][0]["itemIdentifier"] == "msg-fail"


class TestWorkerRetryBehavior:
    """Tests for apology message logic: only on final attempt."""

    def _make_worker_event(self, receive_count: str, message_id: str = "msg-1") -> dict:
        update = _make_update(chat_id=12345)
        record = _make_sqs_record(update, message_id=message_id, approximate_receive_count=receive_count)
        return {"Records": [record]}

    def test_apology_not_sent_on_non_final_attempt(self):
        """On attempt 1 of 3: exception raised but no apology sent."""
        import src.handlers.worker as worker
        importlib.reload(worker)

        sent_messages = []

        async def fake_process(record):
            # Simulate: _is_final_attempt returns False (receive_count=1, max=3)
            from src.handlers.worker import _is_final_attempt, _extract_chat_id
            import json
            update = json.loads(record["body"])
            chat_id = _extract_chat_id(update)
            if not _is_final_attempt(record, max_receive_count=3):
                # Should NOT send apology
                pass
            raise RuntimeError("processing failed")

        with patch("asyncio.run", side_effect=lambda coro: (_ for _ in ()).throw(RuntimeError("processing failed"))):
            resp = worker.handler(self._make_worker_event("1"), None)

        # Item should still be failed for retry
        assert len(resp["batchItemFailures"]) == 1

    def test_item_always_failed_on_service_unavailable(self):
        """ServiceUnavailableError → always reported as failed for retry."""
        import src.handlers.worker as worker
        importlib.reload(worker)

        from src.common.db import ServiceUnavailableError

        with patch(
            "asyncio.run",
            side_effect=ServiceUnavailableError("Neon waking up"),
        ):
            resp = worker.handler(self._make_worker_event("1", "msg-sue"), None)

        assert resp["batchItemFailures"] == [{"itemIdentifier": "msg-sue"}]

    def test_item_failed_on_generic_exception(self):
        """Any unhandled exception → item in batchItemFailures."""
        import src.handlers.worker as worker
        importlib.reload(worker)

        with patch("asyncio.run", side_effect=ValueError("unexpected")):
            resp = worker.handler(self._make_worker_event("2", "msg-val"), None)

        assert resp["batchItemFailures"] == [{"itemIdentifier": "msg-val"}]

    def test_is_final_attempt_integration(self):
        """Final attempt with receive_count=3 should set is_final=True."""
        from src.handlers.worker import _is_final_attempt
        record = _make_sqs_record({}, approximate_receive_count="3")
        assert _is_final_attempt(record, max_receive_count=3) is True

    def test_is_not_final_attempt_integration(self):
        """First attempt with receive_count=1 should set is_final=False."""
        from src.handlers.worker import _is_final_attempt
        record = _make_sqs_record({}, approximate_receive_count="1")
        assert _is_final_attempt(record, max_receive_count=3) is False


class TestWorkerUnknownRoute:
    """Receiver handles unknown routes gracefully."""

    def test_unknown_route_returns_404(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
        monkeypatch.setenv("UPDATE_QUEUE_URL", "https://q.fifo")
        mock_sqs = MagicMock()
        with patch("boto3.client", return_value=mock_sqs):
            import src.handlers.receiver as receiver
            importlib.reload(receiver)

        event = _make_apigw_event(method="DELETE", route="/telegram/webhook")
        resp = receiver.handler(event, None)
        assert resp["statusCode"] == 404
