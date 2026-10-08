"""pytest configuration for Parali Mitra test suite.

OFFLINE-FIRST DESIGN:
  - Sets DB_MODE=local and DATABASE_MODE=local BEFORE any app module import.
  - Patches boto3.client to raise unless a test is marked @pytest.mark.aws.
  - Patches httpx real network calls to raise unless marked @pytest.mark.aws
    or @pytest.mark.pg (pg tests may need Nominatim for geocoding).
  - All unit tests run 100% offline with zero credentials.

Markers:
  aws  -- tests that need real AWS credentials (Bedrock, SSM, S3)
  pg   -- tests that need a live Postgres database (TEST_DATABASE_URL)
"""

from __future__ import annotations

import os

# ── Set env vars BEFORE any src.* import ─────────────────────────────────────
os.environ.setdefault("DB_MODE", "local")
os.environ.setdefault("DATABASE_MODE", "local")
os.environ.setdefault("DB_ENV", "test")  # allows clear_all() in tests

import pytest


# ── Marker registration ───────────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "aws: mark test as requiring real AWS credentials")
    config.addinivalue_line(
        "markers",
        "pg: mark test as requiring a live Postgres database (TEST_DATABASE_URL)",
    )


# ── boto3 network guard ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _block_boto3(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real boto3 calls unless the test is marked @pytest.mark.aws."""
    if request.node.get_closest_marker("aws"):
        return  # allow real AWS calls

    def _fake_boto3_client(*args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "boto3.client() called in a unit test without @pytest.mark.aws. "
            "Mark the test with @pytest.mark.aws or use a mock."
        )

    def _fake_boto3_resource(*args: object, **kwargs: object) -> None:
        raise RuntimeError(
            "boto3.resource() called in a unit test without @pytest.mark.aws. "
            "Mark the test with @pytest.mark.aws or use a mock."
        )

    try:
        import boto3
        monkeypatch.setattr(boto3, "client", _fake_boto3_client)
        monkeypatch.setattr(boto3, "resource", _fake_boto3_resource)
    except ImportError:
        pass  # boto3 not installed in minimal test env


# ── httpx network guard ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _block_httpx_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Block live httpx requests unless marked @pytest.mark.aws or @pytest.mark.pg.

    Tests that supply their own httpx.MockTransport are NOT blocked — only calls
    that would use the real AsyncHTTPTransport (real network) are intercepted.
    """
    if request.node.get_closest_marker("aws") or request.node.get_closest_marker("pg"):
        return  # allow network for integration tests

    try:
        import httpx

        original_async_send = httpx.AsyncClient.send

        async def _guarded_async_send(self: httpx.AsyncClient, *args: object, **kwargs: object):
            # Allow if the client is using a mock or custom transport (not real network)
            transport = getattr(self, "_transport", None)
            if transport is not None and not isinstance(transport, httpx.AsyncHTTPTransport):
                return await original_async_send(self, *args, **kwargs)
            raise RuntimeError(
                "httpx.AsyncClient made a real network request in a unit test without "
                "@pytest.mark.aws or @pytest.mark.pg. Use httpx.MockTransport or mark "
                "the test appropriately."
            )

        monkeypatch.setattr(httpx.AsyncClient, "send", _guarded_async_send)
    except ImportError:
        pass



# ── Shared in-memory DB fixture ───────────────────────────────────────────────


@pytest.fixture
def local_db():
    """Fresh InMemoryDatabase for each test."""
    from src.common.db import InMemoryDatabase
    db = InMemoryDatabase()
    db.clear_all()
    return db
