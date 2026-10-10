"""Unit tests for owner portal passcode verification and rate limiting."""

from datetime import datetime, timedelta, timezone
from src.common.models import ChatFlow
from src.marketplace import services


def test_passcode_success():
    flow = ChatFlow(chat_id=1234, flow="OWNER_PORTAL", step="PASSCODE", attempts=0)
    is_valid, err = services.verify_owner_passcode("secret123", flow, expected_passcode="secret123")
    assert is_valid is True
    assert err is None
    assert flow.attempts == 0


def test_passcode_lockout_after_3_attempts():
    flow = ChatFlow(chat_id=1234, flow="OWNER_PORTAL", step="PASSCODE", attempts=0)

    # Attempt 1
    valid1, err1 = services.verify_owner_passcode("wrong1", flow, expected_passcode="correct")
    assert valid1 is False
    assert err1 == "INVALID_PASSCODE"
    assert flow.attempts == 1

    # Attempt 2
    valid2, err2 = services.verify_owner_passcode("wrong2", flow, expected_passcode="correct")
    assert valid2 is False
    assert err2 == "INVALID_PASSCODE"
    assert flow.attempts == 2

    # Attempt 3 -> Locked out
    valid3, err3 = services.verify_owner_passcode("wrong3", flow, expected_passcode="correct")
    assert valid3 is False
    assert err3.startswith("LOCKED_OUT")
    assert flow.locked_until is not None
    assert flow.locked_until > datetime.now(timezone.utc)

    # Subsequent attempt even with correct password is still rejected during lockout
    valid4, err4 = services.verify_owner_passcode("correct", flow, expected_passcode="correct")
    assert valid4 is False
    assert err4.startswith("LOCKED_OUT")
