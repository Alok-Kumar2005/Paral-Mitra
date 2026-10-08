"""Database access layer for Parali Mitra.

Backends:
  - PostgresClient  (DB_MODE=postgres | neon) — Neon serverless Postgres via psycopg 3
  - InMemoryDatabase (DB_MODE=local)          — fully offline, no credentials needed

Golden rules:
  - NO DynamoDB. DynamoDB is blocked by org SCP.
  - S3 is for binary blobs (voice audio) ONLY via a separate BlobStore. Never here.
  - No automatic cross-backend fallback: a Postgres connection failure raises
    ServiceUnavailableError and the bot shows a friendly "Service is waking up" message.
  - Parameterized queries only — no string interpolation in SQL.
  - DSN is never logged.
"""

from __future__ import annotations

import logging
import math
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from src.common.models import (
    Booking,
    BookingStatus,
    Buyer,
    ChatMessage,
    ChatState,
    FarmerSession,
    Hotspot,
    Machine,
    Provider,
    ProviderStatus,
)

logger = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────


class ServiceUnavailableError(RuntimeError):
    """Raised when the Postgres backend is unreachable (e.g. Neon scale-to-zero wake)."""


# ── Abstract interface ────────────────────────────────────────────────────────


class DatabaseClient(ABC):
    """Abstract interface for all Parali Mitra database operations."""

    # ── Farmer profiles ───────────────────────────────────────────────────────

    @abstractmethod
    def put_session(self, session: FarmerSession) -> None: ...

    @abstractmethod
    def get_session(self, chat_id: int) -> FarmerSession | None: ...

    @abstractmethod
    def forget_farmer(self, chat_id: int) -> None:
        """Delete farmer profile and all associated data (GDPR /forget_me)."""
        ...

    # ── Conversation memory ───────────────────────────────────────────────────

    @abstractmethod
    def append_chat_message(self, msg: ChatMessage) -> ChatMessage:
        """Persist a single message; returns the message with id set."""
        ...

    @abstractmethod
    def load_chat_messages(
        self,
        chat_id: int,
        limit: int = 20,
    ) -> list[ChatMessage]:
        """Return the most recent `limit` messages for the farmer, oldest first."""
        ...

    @abstractmethod
    def get_chat_state(self, chat_id: int) -> ChatState | None: ...

    @abstractmethod
    def put_chat_state(self, state: ChatState) -> None: ...

    # ── Providers ─────────────────────────────────────────────────────────────

    @abstractmethod
    def put_provider(self, provider: Provider) -> None: ...

    @abstractmethod
    def get_provider(self, provider_id: str) -> Provider | None: ...

    @abstractmethod
    def update_provider_status(
        self,
        provider_id: str,
        status: ProviderStatus,
        verified_by: str | None = None,
    ) -> Provider | None: ...

    # ── Machines ──────────────────────────────────────────────────────────────

    @abstractmethod
    def put_machine(self, machine: Machine) -> None: ...

    @abstractmethod
    def get_machine(self, machine_id: str) -> Machine | None: ...

    @abstractmethod
    def list_machines(self, district: str | None = None) -> list[Machine]: ...

    @abstractmethod
    def list_machines_nearby(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50.0,
    ) -> list[Machine]:
        """Return ACTIVE machines whose providers are VERIFIED within radius_km."""
        ...

    # ── Buyers ────────────────────────────────────────────────────────────────

    @abstractmethod
    def put_buyer(self, buyer: Buyer) -> None: ...

    @abstractmethod
    def get_buyer(self, buyer_id: str) -> Buyer | None: ...

    @abstractmethod
    def list_buyers(self) -> list[Buyer]: ...

    # ── Bookings ──────────────────────────────────────────────────────────────

    @abstractmethod
    def put_booking(self, booking: Booking) -> None: ...

    @abstractmethod
    def get_booking(self, booking_id: str) -> Booking | None: ...

    @abstractmethod
    def list_bookings_by_farmer(self, farmer_chat_id: int) -> list[Booking]: ...

    @abstractmethod
    def update_booking_status(
        self, booking_id: str, status: BookingStatus
    ) -> Booking | None: ...

    # ── Hotspots ──────────────────────────────────────────────────────────────

    @abstractmethod
    def put_hotspots(self, hotspots: list[Hotspot]) -> int:
        """Upsert hotspots; returns count of rows written."""
        ...

    @abstractmethod
    def list_hotspots(self) -> list[Hotspot]:
        """Return all non-expired hotspots."""
        ...

    # ── Idempotency guard ─────────────────────────────────────────────────────

    @abstractmethod
    def is_update_processed(self, update_id: str | int) -> bool: ...

    @abstractmethod
    def mark_update_processed(
        self, update_id: str | int, ttl_seconds: int = 86400
    ) -> None: ...

    # ── Geocode cache ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_geocode_cache(self, query_key: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def set_geocode_cache(
        self,
        query_key: str,
        lat: float,
        lon: float,
        payload: dict[str, Any],
        ttl_seconds: int = 604800,  # 7 days
    ) -> None: ...

    # ── Maintenance ───────────────────────────────────────────────────────────

    @abstractmethod
    def prune_expired(self) -> None:
        """Delete expired rows from chat_messages, hotspots, processed_updates, geocode_cache."""
        ...

    @abstractmethod
    def clear_all(self) -> None:
        """Wipe all data. Only permitted when DB_ENV=dev."""
        ...


# ── Geo helpers ───────────────────────────────────────────────────────────────

def _lat_lon_bbox(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    """Return (lat_min, lat_max, lon_min, lon_max) for a bounding box.

    Uses flat-earth approximation (good for <200 km).
    111 km per degree of latitude; longitude degrees shrink with cos(lat).
    """
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Exact haversine distance in kilometres between two lat/lon points."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ── In-memory backend ─────────────────────────────────────────────────────────


class InMemoryDatabase(DatabaseClient):
    """Local in-memory storage for tests and offline development.

    All data lives in plain dicts/lists and is lost when the process exits.
    """

    def __init__(self) -> None:
        self._machines: dict[str, dict[str, Any]] = {}
        self._buyers: dict[str, dict[str, Any]] = {}
        self._bookings: dict[str, dict[str, Any]] = {}
        self._sessions: dict[int, dict[str, Any]] = {}
        self._hotspots: dict[str, dict[str, Any]] = {}
        self._processed_updates: dict[str, float] = {}  # update_id -> expiry epoch
        self._providers: dict[str, dict[str, Any]] = {}
        self._chat_messages: list[dict[str, Any]] = []
        self._chat_states: dict[int, dict[str, Any]] = {}
        self._geocode_cache: dict[str, dict[str, Any]] = {}
        self._msg_seq: int = 0

    def clear_all(self) -> None:
        if os.getenv("DB_ENV", "dev").strip().lower() not in ("dev", "test"):
            raise RuntimeError("clear_all() is only allowed when DB_ENV=dev or DB_ENV=test")
        self._machines.clear()
        self._buyers.clear()
        self._bookings.clear()
        self._sessions.clear()
        self._hotspots.clear()
        self._processed_updates.clear()
        self._providers.clear()
        self._chat_messages.clear()
        self._chat_states.clear()
        self._geocode_cache.clear()
        self._msg_seq = 0

    # ── Farmer profiles ───────────────────────────────────────────────────────

    def put_session(self, session: FarmerSession) -> None:
        self._sessions[session.chat_id] = session.model_dump(mode="json")

    def get_session(self, chat_id: int) -> FarmerSession | None:
        data = self._sessions.get(chat_id)
        return FarmerSession.model_validate(data) if data else None

    def forget_farmer(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)
        self._chat_states.pop(chat_id, None)
        self._chat_messages = [m for m in self._chat_messages if m.get("chat_id") != chat_id]
        # Bookings are kept for audit purposes (farmer_chat_id FK set to NULL in real DB)

    # ── Conversation memory ───────────────────────────────────────────────────

    def append_chat_message(self, msg: ChatMessage) -> ChatMessage:
        self._msg_seq += 1
        row = msg.model_dump(mode="json")
        row["id"] = self._msg_seq
        self._chat_messages.append(row)
        return ChatMessage.model_validate(row)

    def load_chat_messages(self, chat_id: int, limit: int = 20) -> list[ChatMessage]:
        now = datetime.now(timezone.utc)
        rows = [
            m for m in self._chat_messages
            if m.get("chat_id") == chat_id
            and datetime.fromisoformat(m["expires_at"]) > now
        ]
        rows = rows[-limit:]
        return [ChatMessage.model_validate(r) for r in rows]

    def get_chat_state(self, chat_id: int) -> ChatState | None:
        data = self._chat_states.get(chat_id)
        return ChatState.model_validate(data) if data else None

    def put_chat_state(self, state: ChatState) -> None:
        self._chat_states[state.chat_id] = state.model_dump(mode="json")

    # ── Providers ─────────────────────────────────────────────────────────────

    def put_provider(self, provider: Provider) -> None:
        self._providers[provider.provider_id] = provider.model_dump(mode="json")

    def get_provider(self, provider_id: str) -> Provider | None:
        data = self._providers.get(provider_id)
        return Provider.model_validate(data) if data else None

    def update_provider_status(
        self,
        provider_id: str,
        status: ProviderStatus,
        verified_by: str | None = None,
    ) -> Provider | None:
        data = self._providers.get(provider_id)
        if not data:
            return None
        data["status"] = status.value
        if verified_by:
            data["verified_by"] = verified_by
        if status == ProviderStatus.VERIFIED:
            data["verified_at"] = _utc_now_iso()
        provider = Provider.model_validate(data)
        self._providers[provider_id] = provider.model_dump(mode="json")
        return provider

    # ── Machines ──────────────────────────────────────────────────────────────

    def put_machine(self, machine: Machine) -> None:
        self._machines[machine.machine_id] = machine.model_dump(mode="json")

    def get_machine(self, machine_id: str) -> Machine | None:
        data = self._machines.get(machine_id)
        return Machine.model_validate(data) if data else None

    def list_machines(self, district: str | None = None) -> list[Machine]:
        res = [Machine.model_validate(d) for d in self._machines.values()]
        if district:
            res = [m for m in res if m.district.strip().lower() == district.strip().lower()]
        return res

    def list_machines_nearby(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50.0,
    ) -> list[Machine]:
        """Return ACTIVE machines within radius_km. Provider VERIFIED check is advisory
        in the in-memory backend (no provider table join required for tests)."""
        result = []
        for machine in self.list_machines():
            if machine.status != "ACTIVE":
                continue
            dist = _haversine_km(lat, lon, machine.lat, machine.lon)
            if dist <= radius_km:
                result.append(machine)
        return result

    # ── Buyers ────────────────────────────────────────────────────────────────

    def put_buyer(self, buyer: Buyer) -> None:
        self._buyers[buyer.buyer_id] = buyer.model_dump(mode="json")

    def get_buyer(self, buyer_id: str) -> Buyer | None:
        data = self._buyers.get(buyer_id)
        return Buyer.model_validate(data) if data else None

    def list_buyers(self) -> list[Buyer]:
        return [Buyer.model_validate(d) for d in self._buyers.values()]

    # ── Bookings ──────────────────────────────────────────────────────────────

    def put_booking(self, booking: Booking) -> None:
        self._bookings[booking.booking_id] = booking.model_dump(mode="json")

    def get_booking(self, booking_id: str) -> Booking | None:
        data = self._bookings.get(booking_id)
        return Booking.model_validate(data) if data else None

    def list_bookings_by_farmer(self, farmer_chat_id: int) -> list[Booking]:
        return [
            Booking.model_validate(d)
            for d in self._bookings.values()
            if d.get("farmer_chat_id") == farmer_chat_id
        ]

    def update_booking_status(
        self, booking_id: str, status: BookingStatus
    ) -> Booking | None:
        data = self._bookings.get(booking_id)
        if not data:
            return None
        data["status"] = status.value
        data["updated_at"] = _utc_now_iso()
        booking = Booking.model_validate(data)
        self._bookings[booking_id] = booking.model_dump(mode="json")
        return booking

    # ── Hotspots ──────────────────────────────────────────────────────────────

    def put_hotspots(self, hotspots: list[Hotspot]) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for h in hotspots:
            if h.expires_at is None:
                # Default 72-hour expiry if not set
                expires = now + timedelta(hours=72)
                object.__setattr__(h, "expires_at", expires)
            key = f"{h.grid_cell}#{h.acq_date.isoformat()}"
            self._hotspots[key] = h.model_dump(mode="json")
            count += 1
        return count

    def list_hotspots(self) -> list[Hotspot]:
        now = datetime.now(timezone.utc)
        active = []
        for d in self._hotspots.values():
            expires_raw = d.get("expires_at")
            if expires_raw:
                exp = datetime.fromisoformat(expires_raw)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp > now:
                    active.append(Hotspot.model_validate(d))
        return active

    # ── Idempotency ───────────────────────────────────────────────────────────

    def is_update_processed(self, update_id: str | int) -> bool:
        uid = str(update_id)
        expiry = self._processed_updates.get(uid)
        if expiry is None:
            return False
        if time.time() > expiry:
            del self._processed_updates[uid]
            return False
        return True

    def mark_update_processed(
        self, update_id: str | int, ttl_seconds: int = 86400
    ) -> None:
        uid = str(update_id)
        self._processed_updates[uid] = time.time() + ttl_seconds

    # ── Geocode cache ─────────────────────────────────────────────────────────

    def get_geocode_cache(self, query_key: str) -> dict[str, Any] | None:
        row = self._geocode_cache.get(query_key)
        if not row:
            return None
        exp_raw = row.get("expires_at", "")
        if exp_raw:
            exp = datetime.fromisoformat(exp_raw)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                del self._geocode_cache[query_key]
                return None
        return row

    def set_geocode_cache(
        self,
        query_key: str,
        lat: float,
        lon: float,
        payload: dict[str, Any],
        ttl_seconds: int = 604800,
    ) -> None:
        expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        self._geocode_cache[query_key] = {
            "query_key": query_key,
            "lat": lat,
            "lon": lon,
            "payload": payload,
            "expires_at": expires.isoformat(),
        }

    # ── Maintenance ───────────────────────────────────────────────────────────

    def prune_expired(self) -> None:
        now = datetime.now(timezone.utc)
        # chat_messages
        self._chat_messages = [
            m for m in self._chat_messages
            if _parse_dt(m.get("expires_at")) > now
        ]
        # hotspots
        self._hotspots = {
            k: v for k, v in self._hotspots.items()
            if _parse_dt(v.get("expires_at")) > now
        }
        # geocode_cache
        self._geocode_cache = {
            k: v for k, v in self._geocode_cache.items()
            if _parse_dt(v.get("expires_at")) > now
        }
        # processed_updates (epoch-based)
        now_ts = time.time()
        self._processed_updates = {
            k: v for k, v in self._processed_updates.items() if v > now_ts
        }


# ── PostgreSQL backend ────────────────────────────────────────────────────────


class PostgresClient(DatabaseClient):
    """Production Postgres storage via psycopg 3 (psycopg[binary]).

    Lambda-friendly design:
    - One module-level connection reused across invocations (no pool).
    - Health-check ping before each use; reconnect on OperationalError.
    - 3 retries with 0.5 / 1.0 / 2.0 s backoff for Neon scale-to-zero wakes.
    - sslmode=require, connect_timeout=10, statement_timeout=30 000 ms.
    - DSN is read from DATABASE_URL env locally; from SSM /parali/database_url in Lambda.
    - DSN is NEVER logged.
    """

    _RETRY_DELAYS = (0.5, 1.0, 2.0)

    def __init__(self) -> None:
        self._conn: Any = None  # psycopg.Connection
        self._dsn: str = self._resolve_dsn()
        logger.info("[DB] mode=postgres (Neon serverless)")

    # ── Connection management ─────────────────────────────────────────────────

    @staticmethod
    def _resolve_dsn() -> str:
        """Read DSN from env or SSM. Never log it."""
        dsn = os.getenv("DATABASE_URL", "").strip()
        if not dsn:
            # Try SSM (Lambda production path)
            try:
                import boto3
                ssm = boto3.client("ssm", region_name=os.getenv("AWS_REGION", "ap-south-1"))
                resp = ssm.get_parameter(Name="/parali/database_url", WithDecryption=True)
                dsn = resp["Parameter"]["Value"].strip()
            except Exception as exc:
                raise ServiceUnavailableError(
                    "DATABASE_URL is not set and SSM /parali/database_url could not be read. "
                    f"Cause: {exc}"
                ) from exc
        if not dsn:
            raise ServiceUnavailableError(
                "DATABASE_URL environment variable is empty. "
                "Set it to a valid Neon PostgreSQL DSN."
            )
        return dsn

    def _connect(self) -> Any:
        """Establish a new psycopg connection with Neon-safe parameters."""
        try:
            import psycopg
        except ImportError as exc:
            raise ServiceUnavailableError(
                "psycopg[binary] is not installed. Run: pip install psycopg[binary]"
            ) from exc

        connect_kwargs: dict[str, Any] = {
            "conninfo": self._dsn,
            "connect_timeout": 10,
            "sslmode": "require",
            "autocommit": False,
        }
        try:
            parsed_opts = psycopg.conninfo.conninfo_to_dict(self._dsn)
            existing_opts = parsed_opts.get("options", "")
            if "statement_timeout" not in existing_opts:
                connect_kwargs["options"] = f"{existing_opts} -c statement_timeout=30000".strip()
        except Exception:
            connect_kwargs["options"] = "-c statement_timeout=30000"

        return psycopg.connect(**connect_kwargs)

    def _get_conn(self) -> Any:
        """Return healthy connection, reconnecting with retry if needed."""
        import psycopg

        for attempt, delay in enumerate((*self._RETRY_DELAYS, None), start=1):
            try:
                if self._conn is not None:
                    try:
                        self._conn.execute("SELECT 1")
                        return self._conn
                    except Exception:
                        try:
                            self._conn.close()
                        except Exception:
                            pass
                        self._conn = None

                self._conn = self._connect()
                return self._conn

            except psycopg.OperationalError as exc:
                if delay is None:
                    raise ServiceUnavailableError(
                        "Postgres connection failed after 3 retries. "
                        "The service may be waking up — please try again in a minute."
                    ) from exc
                logger.warning(
                    "[DB] Postgres connection attempt %d failed (%s). Retrying in %.1fs...",
                    attempt,
                    exc,
                    delay,
                )
                time.sleep(delay)
                self._conn = None

        # unreachable, but satisfies type checkers
        raise ServiceUnavailableError("Postgres connection failed.")  # pragma: no cover

    # ── Farmer profiles ───────────────────────────────────────────────────────

    def put_session(self, session: FarmerSession) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO farmers (
                    chat_id, language, lat, lon, village_text, district, state,
                    acres, crop, sowing_deadline, consent_given_at, created_at, last_seen_at
                ) VALUES (
                    %(chat_id)s, %(language)s, %(lat)s, %(lon)s, %(village_text)s,
                    %(district)s, %(state)s, %(acres)s, %(crop)s, %(sowing_deadline)s,
                    %(consent_given_at)s, %(created_at)s, %(last_seen_at)s
                )
                ON CONFLICT (chat_id) DO UPDATE SET
                    language         = EXCLUDED.language,
                    lat              = EXCLUDED.lat,
                    lon              = EXCLUDED.lon,
                    village_text     = EXCLUDED.village_text,
                    district         = EXCLUDED.district,
                    state            = EXCLUDED.state,
                    acres            = EXCLUDED.acres,
                    crop             = EXCLUDED.crop,
                    sowing_deadline  = EXCLUDED.sowing_deadline,
                    consent_given_at = EXCLUDED.consent_given_at,
                    last_seen_at     = now()
                """,
                {
                    "chat_id": str(session.chat_id),
                    "language": session.language,
                    "lat": session.lat,
                    "lon": session.lon,
                    "village_text": session.village_text,
                    "district": session.district,
                    "state": session.state,
                    "acres": session.acres,
                    "crop": session.crop,
                    "sowing_deadline": session.sowing_deadline,
                    "consent_given_at": session.consent_given_at,
                    "created_at": session.created_at,
                    "last_seen_at": session.last_seen_at,
                },
            )

    def get_session(self, chat_id: int) -> FarmerSession | None:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM farmers WHERE chat_id = %s",
            (str(chat_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc.name for desc in cur.description]
        d = dict(zip(cols, row))
        session = _farmer_from_row(d)
        try:
            msgs = self.load_chat_messages(chat_id=chat_id, limit=20)
            session.history = [
                {"role": m.role, "content": [{"type": "text", "text": m.text}]}
                for m in msgs
            ]
        except Exception:
            pass
        return session

    def forget_farmer(self, chat_id: int) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute("DELETE FROM farmers WHERE chat_id = %s", (str(chat_id),))

    # ── Conversation memory ───────────────────────────────────────────────────

    def append_chat_message(self, msg: ChatMessage) -> ChatMessage:
        conn = self._get_conn()
        with conn.transaction():
            # Advisory lock scoped to this transaction prevents concurrent writes
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (str(msg.chat_id),),
            )
            cur = conn.execute(
                """
                INSERT INTO chat_messages (chat_id, role, text, created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    str(msg.chat_id),
                    msg.role,
                    msg.text,
                    msg.created_at,
                    msg.expires_at,
                ),
            )
            row = cur.fetchone()
            return ChatMessage(
                id=row[0],
                chat_id=msg.chat_id,
                role=msg.role,
                text=msg.text,
                created_at=row[1],
                expires_at=msg.expires_at,
            )

    def load_chat_messages(self, chat_id: int, limit: int = 20) -> list[ChatMessage]:
        conn = self._get_conn()
        # Subquery fetches newest N; outer ORDER BY returns oldest first
        cur = conn.execute(
            """
            SELECT id, chat_id, role, text, created_at, expires_at
            FROM (
                SELECT id, chat_id, role, text, created_at, expires_at
                FROM chat_messages
                WHERE chat_id = %s AND expires_at > now()
                ORDER BY id DESC
                LIMIT %s
            ) sub
            ORDER BY id ASC
            """,
            (str(chat_id), limit),
        )
        rows = cur.fetchall()
        cols = [desc.name for desc in cur.description]
        return [
            ChatMessage.model_validate(dict(zip(cols, r)))
            for r in rows
        ]

    def get_chat_state(self, chat_id: int) -> ChatState | None:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT chat_id, summary, summarized_upto, version, updated_at "
            "FROM chat_state WHERE chat_id = %s",
            (str(chat_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc.name for desc in cur.description]
        d = dict(zip(cols, row))
        d["chat_id"] = int(d["chat_id"])
        return ChatState.model_validate(d)

    def put_chat_state(self, state: ChatState) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (str(state.chat_id),),
            )
            conn.execute(
                """
                INSERT INTO chat_state (chat_id, summary, summarized_upto, version, updated_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (chat_id) DO UPDATE SET
                    summary         = EXCLUDED.summary,
                    summarized_upto = EXCLUDED.summarized_upto,
                    version         = chat_state.version + 1,
                    updated_at      = now()
                """,
                (
                    str(state.chat_id),
                    state.summary,
                    state.summarized_upto,
                    state.version,
                ),
            )

    # ── Providers ─────────────────────────────────────────────────────────────

    def put_provider(self, provider: Provider) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO providers (
                    provider_id, provider_type, name, contact_phone, telegram_chat_id,
                    district, state, lat, lon, status, verified_by, verified_at,
                    is_directory_listing, created_at
                ) VALUES (
                    %(provider_id)s, %(provider_type)s, %(name)s, %(contact_phone)s,
                    %(telegram_chat_id)s, %(district)s, %(state)s, %(lat)s, %(lon)s,
                    %(status)s, %(verified_by)s, %(verified_at)s,
                    %(is_directory_listing)s, %(created_at)s
                )
                ON CONFLICT (provider_id) DO UPDATE SET
                    name                 = EXCLUDED.name,
                    contact_phone        = EXCLUDED.contact_phone,
                    telegram_chat_id     = EXCLUDED.telegram_chat_id,
                    district             = EXCLUDED.district,
                    state                = EXCLUDED.state,
                    lat                  = EXCLUDED.lat,
                    lon                  = EXCLUDED.lon,
                    status               = EXCLUDED.status,
                    is_directory_listing = EXCLUDED.is_directory_listing
                """,
                {
                    "provider_id": provider.provider_id,
                    "provider_type": str(provider.provider_type.value
                                        if hasattr(provider.provider_type, "value")
                                        else provider.provider_type),
                    "name": provider.name,
                    "contact_phone": provider.contact_phone,
                    "telegram_chat_id": provider.telegram_chat_id,
                    "district": provider.district,
                    "state": provider.state,
                    "lat": provider.lat,
                    "lon": provider.lon,
                    "status": provider.status.value,
                    "verified_by": provider.verified_by,
                    "verified_at": provider.verified_at,
                    "is_directory_listing": provider.is_directory_listing,
                    "created_at": provider.created_at,
                },
            )

    def get_provider(self, provider_id: str) -> Provider | None:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM providers WHERE provider_id = %s", (provider_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc.name for desc in cur.description]
        return Provider.model_validate(dict(zip(cols, row)))

    def update_provider_status(
        self,
        provider_id: str,
        status: ProviderStatus,
        verified_by: str | None = None,
    ) -> Provider | None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                """
                UPDATE providers SET
                    status      = %s,
                    verified_by = COALESCE(%s, verified_by),
                    verified_at = CASE WHEN %s = 'VERIFIED' THEN now() ELSE verified_at END
                WHERE provider_id = %s
                """,
                (status.value, verified_by, status.value, provider_id),
            )
        return self.get_provider(provider_id)

    # ── Machines ──────────────────────────────────────────────────────────────

    def put_machine(self, machine: Machine) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO machines (
                    machine_id, provider_id, machine_type, village, district,
                    lat, lon, rate_per_acre, travel_charge_per_km, service_radius_km,
                    available_from, blocked_dates, status, rating_avg, rating_count,
                    source, is_synthetic
                ) VALUES (
                    %(machine_id)s, %(provider_id)s, %(machine_type)s, %(village)s, %(district)s,
                    %(lat)s, %(lon)s, %(rate_per_acre)s, %(travel_charge_per_km)s, %(service_radius_km)s,
                    %(available_from)s, %(blocked_dates)s, %(status)s, %(rating_avg)s, %(rating_count)s,
                    %(source)s, %(is_synthetic)s
                )
                ON CONFLICT (machine_id) DO UPDATE SET
                    provider_id          = EXCLUDED.provider_id,
                    machine_type         = EXCLUDED.machine_type,
                    village              = EXCLUDED.village,
                    district             = EXCLUDED.district,
                    lat                  = EXCLUDED.lat,
                    lon                  = EXCLUDED.lon,
                    rate_per_acre        = EXCLUDED.rate_per_acre,
                    travel_charge_per_km = EXCLUDED.travel_charge_per_km,
                    service_radius_km    = EXCLUDED.service_radius_km,
                    available_from       = EXCLUDED.available_from,
                    blocked_dates        = EXCLUDED.blocked_dates,
                    status               = EXCLUDED.status,
                    source               = EXCLUDED.source,
                    is_synthetic         = EXCLUDED.is_synthetic
                """,
                {
                    "machine_id": machine.machine_id,
                    "provider_id": machine.provider_id,
                    "machine_type": str(machine.machine_type.value
                                       if hasattr(machine.machine_type, "value")
                                       else machine.machine_type),
                    "village": machine.village,
                    "district": machine.district,
                    "lat": machine.lat,
                    "lon": machine.lon,
                    "rate_per_acre": machine.rate_per_acre,
                    "travel_charge_per_km": machine.travel_charge_per_km,
                    "service_radius_km": machine.service_radius_km,
                    "available_from": machine.available_from,
                    "blocked_dates": [d.isoformat() for d in machine.blocked_dates],
                    "status": machine.status,
                    "rating_avg": machine.rating_avg,
                    "rating_count": machine.rating_count,
                    "source": machine.source,
                    "is_synthetic": machine.is_synthetic,
                },
            )

    def get_machine(self, machine_id: str) -> Machine | None:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM machines WHERE machine_id = %s", (machine_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc.name for desc in cur.description]
        return _machine_from_row(dict(zip(cols, row)))

    def list_machines(self, district: str | None = None) -> list[Machine]:
        conn = self._get_conn()
        if district:
            cur = conn.execute(
                "SELECT * FROM machines WHERE lower(district) = lower(%s)", (district,)
            )
        else:
            cur = conn.execute("SELECT * FROM machines")
        cols = [desc.name for desc in cur.description]
        return [_machine_from_row(dict(zip(cols, r))) for r in cur.fetchall()]

    def list_machines_nearby(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50.0,
    ) -> list[Machine]:
        """Bounding-box pre-filter in SQL (no PostGIS), exact haversine in Python.
        Only returns machines whose provider status = VERIFIED and machine status = ACTIVE.
        """
        lat_min, lat_max, lon_min, lon_max = _lat_lon_bbox(lat, lon, radius_km)
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT m.*
            FROM machines m
            JOIN providers p ON p.provider_id = m.provider_id
            WHERE m.status = 'ACTIVE'
              AND p.status = 'VERIFIED'
              AND m.lat BETWEEN %s AND %s
              AND m.lon BETWEEN %s AND %s
            """,
            (lat_min, lat_max, lon_min, lon_max),
        )
        cols = [desc.name for desc in cur.description]
        candidates = [_machine_from_row(dict(zip(cols, r))) for r in cur.fetchall()]
        return [m for m in candidates if _haversine_km(lat, lon, m.lat, m.lon) <= radius_km]

    # ── Buyers ────────────────────────────────────────────────────────────────

    def put_buyer(self, buyer: Buyer) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO buyers (
                    buyer_id, provider_id, name, buyer_type, district,
                    lat, lon, price_per_tonne, min_quantity_tonnes,
                    transport_terms, phone, source, is_synthetic
                ) VALUES (
                    %(buyer_id)s, %(provider_id)s, %(name)s, %(buyer_type)s, %(district)s,
                    %(lat)s, %(lon)s, %(price_per_tonne)s, %(min_quantity_tonnes)s,
                    %(transport_terms)s, %(phone)s, %(source)s, %(is_synthetic)s
                )
                ON CONFLICT (buyer_id) DO UPDATE SET
                    name                = EXCLUDED.name,
                    buyer_type          = EXCLUDED.buyer_type,
                    district            = EXCLUDED.district,
                    lat                 = EXCLUDED.lat,
                    lon                 = EXCLUDED.lon,
                    price_per_tonne     = EXCLUDED.price_per_tonne,
                    min_quantity_tonnes = EXCLUDED.min_quantity_tonnes,
                    transport_terms     = EXCLUDED.transport_terms,
                    phone               = EXCLUDED.phone,
                    source              = EXCLUDED.source,
                    is_synthetic        = EXCLUDED.is_synthetic
                """,
                {
                    "buyer_id": buyer.buyer_id,
                    "provider_id": buyer.provider_id,
                    "name": buyer.name,
                    "buyer_type": str(buyer.buyer_type.value
                                     if hasattr(buyer.buyer_type, "value")
                                     else buyer.buyer_type),
                    "district": buyer.district,
                    "lat": buyer.lat,
                    "lon": buyer.lon,
                    "price_per_tonne": buyer.price_per_tonne,
                    "min_quantity_tonnes": buyer.min_quantity_tonnes,
                    "transport_terms": str(buyer.transport_terms.value
                                          if hasattr(buyer.transport_terms, "value")
                                          else buyer.transport_terms),
                    "phone": buyer.phone,
                    "source": buyer.source,
                    "is_synthetic": buyer.is_synthetic,
                },
            )

    def get_buyer(self, buyer_id: str) -> Buyer | None:
        conn = self._get_conn()
        cur = conn.execute("SELECT * FROM buyers WHERE buyer_id = %s", (buyer_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc.name for desc in cur.description]
        return _buyer_from_row(dict(zip(cols, row)))

    def list_buyers(self) -> list[Buyer]:
        conn = self._get_conn()
        cur = conn.execute("SELECT * FROM buyers")
        cols = [desc.name for desc in cur.description]
        return [_buyer_from_row(dict(zip(cols, r))) for r in cur.fetchall()]

    # ── Bookings ──────────────────────────────────────────────────────────────

    def put_booking(self, booking: Booking) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO bookings (
                    booking_id, farmer_chat_id, provider_id, option_type, target_id,
                    acres, requested_date, status, rating, created_at, updated_at, completed_at
                ) VALUES (
                    %(booking_id)s, %(farmer_chat_id)s, %(provider_id)s, %(option_type)s,
                    %(target_id)s, %(acres)s, %(requested_date)s, %(status)s, %(rating)s,
                    %(created_at)s, %(updated_at)s, %(completed_at)s
                )
                ON CONFLICT (booking_id) DO UPDATE SET
                    status       = EXCLUDED.status,
                    rating       = EXCLUDED.rating,
                    updated_at   = now(),
                    completed_at = EXCLUDED.completed_at
                """,
                {
                    "booking_id": booking.booking_id,
                    "farmer_chat_id": str(booking.farmer_chat_id),
                    "provider_id": booking.provider_id,
                    "option_type": str(booking.option_type.value
                                      if hasattr(booking.option_type, "value")
                                      else booking.option_type),
                    "target_id": booking.target_id,
                    "acres": booking.acres,
                    "requested_date": booking.requested_date,
                    "status": booking.status.value,
                    "rating": booking.rating,
                    "created_at": booking.created_at,
                    "updated_at": booking.updated_at,
                    "completed_at": booking.completed_at,
                },
            )

    def get_booking(self, booking_id: str) -> Booking | None:
        conn = self._get_conn()
        cur = conn.execute("SELECT * FROM bookings WHERE booking_id = %s", (booking_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc.name for desc in cur.description]
        return _booking_from_row(dict(zip(cols, row)))

    def list_bookings_by_farmer(self, farmer_chat_id: int) -> list[Booking]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT * FROM bookings WHERE farmer_chat_id = %s ORDER BY created_at DESC",
            (str(farmer_chat_id),),
        )
        cols = [desc.name for desc in cur.description]
        return [_booking_from_row(dict(zip(cols, r))) for r in cur.fetchall()]

    def update_booking_status(
        self, booking_id: str, status: BookingStatus
    ) -> Booking | None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute(
                """
                UPDATE bookings SET
                    status       = %s,
                    updated_at   = now(),
                    completed_at = CASE WHEN %s = 'COMPLETED' THEN now() ELSE completed_at END
                WHERE booking_id = %s
                """,
                (status.value, status.value, booking_id),
            )
        return self.get_booking(booking_id)

    # ── Hotspots ──────────────────────────────────────────────────────────────

    def put_hotspots(self, hotspots: list[Hotspot]) -> int:
        conn = self._get_conn()
        count = 0
        with conn.transaction():
            for h in hotspots:
                expires = h.expires_at or (datetime.now(timezone.utc) + timedelta(hours=72))
                conn.execute(
                    """
                    INSERT INTO hotspots (grid_cell, acq_date, acq_time, lat, lon, frp, confidence, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (grid_cell, acq_date) DO UPDATE SET
                        lat        = EXCLUDED.lat,
                        lon        = EXCLUDED.lon,
                        frp        = EXCLUDED.frp,
                        confidence = EXCLUDED.confidence,
                        expires_at = EXCLUDED.expires_at
                    """,
                    (h.grid_cell, h.acq_date, h.acq_time, h.lat, h.lon, h.frp, h.confidence, expires),
                )
                count += 1
        return count

    def list_hotspots(self) -> list[Hotspot]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT grid_cell, acq_date, acq_time, lat, lon, frp, confidence, expires_at "
            "FROM hotspots WHERE expires_at > now()"
        )
        cols = [desc.name for desc in cur.description]
        return [Hotspot.model_validate(dict(zip(cols, r))) for r in cur.fetchall()]

    # ── Idempotency ───────────────────────────────────────────────────────────

    def is_update_processed(self, update_id: str | int) -> bool:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT 1 FROM processed_updates WHERE update_id = %s AND expires_at > now()",
            (int(update_id),),
        )
        return cur.fetchone() is not None

    def mark_update_processed(
        self, update_id: str | int, ttl_seconds: int = 86400
    ) -> None:
        conn = self._get_conn()
        expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO processed_updates (update_id, expires_at)
                VALUES (%s, %s)
                ON CONFLICT (update_id) DO NOTHING
                """,
                (int(update_id), expires),
            )

    # ── Geocode cache ─────────────────────────────────────────────────────────

    def get_geocode_cache(self, query_key: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT lat, lon, payload FROM geocode_cache WHERE query_key = %s AND expires_at > now()",
            (query_key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"lat": float(row[0]), "lon": float(row[1]), "payload": row[2]}

    def set_geocode_cache(
        self,
        query_key: str,
        lat: float,
        lon: float,
        payload: dict[str, Any],
        ttl_seconds: int = 604800,
    ) -> None:
        conn = self._get_conn()
        expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO geocode_cache (query_key, lat, lon, payload, expires_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (query_key) DO UPDATE SET
                    lat        = EXCLUDED.lat,
                    lon        = EXCLUDED.lon,
                    payload    = EXCLUDED.payload,
                    expires_at = EXCLUDED.expires_at
                """,
                (query_key, lat, lon, payload, expires),
            )

    # ── Maintenance ───────────────────────────────────────────────────────────

    def prune_expired(self) -> None:
        conn = self._get_conn()
        with conn.transaction():
            conn.execute("SELECT prune_expired()")
        logger.info("[DB] prune_expired() executed")

    def clear_all(self) -> None:
        if os.getenv("DB_ENV", "prod").strip().lower() not in ("dev", "test"):
            raise RuntimeError(
                "clear_all() refused: DB_ENV must be 'dev' or 'test'. "
                "This prevents accidental data wipe in production."
            )
        conn = self._get_conn()
        with conn.transaction():
            for table in (
                "bookings", "chat_messages", "chat_state",
                "hotspots", "processed_updates", "geocode_cache",
                "machines", "buyers", "providers", "farmers",
            ):
                conn.execute(f"TRUNCATE {table} CASCADE")  # noqa: S608


# ── Row mappers (Postgres → Pydantic) ────────────────────────────────────────


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        dt = datetime.fromisoformat(val)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _farmer_from_row(d: dict[str, Any]) -> FarmerSession:
    d = dict(d)
    d["chat_id"] = int(d["chat_id"])
    return FarmerSession.model_validate(d)


def _machine_from_row(d: dict[str, Any]) -> Machine:
    d = dict(d)
    # blocked_dates comes as a Postgres array of date objects or strings
    bd = d.get("blocked_dates") or []
    from datetime import date as _date
    d["blocked_dates"] = [
        b if isinstance(b, _date) else _date.fromisoformat(str(b))
        for b in bd
    ]
    # owner_name / owner_phone not stored in machines table; default to empty
    d.setdefault("owner_name", "")
    d.setdefault("owner_phone", "")
    return Machine.model_validate(d)


def _buyer_from_row(d: dict[str, Any]) -> Buyer:
    return Buyer.model_validate(d)


def _booking_from_row(d: dict[str, Any]) -> Booking:
    d = dict(d)
    d["farmer_chat_id"] = int(d["farmer_chat_id"])
    return Booking.model_validate(d)


# ── Factory ───────────────────────────────────────────────────────────────────

_in_memory_instance = InMemoryDatabase()


def get_db_client(mode: str | None = None) -> DatabaseClient:
    """Return the correct database client based on DB_MODE.

    Modes:
      postgres | neon -> PostgresClient (Neon serverless Postgres)
      local           -> InMemoryDatabase (offline, no credentials)

    There is NO automatic fallback between backends. A Postgres connection
    failure raises ServiceUnavailableError; callers surface a friendly
    'Service is waking up' message to the farmer.
    """
    resolved = (mode or os.getenv("DB_MODE", "local")).strip().lower()
    if resolved in ("postgres", "neon"):
        logger.info("[DB] mode=postgres")
        return PostgresClient()
    if resolved == "local":
        logger.info("[DB] mode=local (InMemoryDatabase)")
        return _in_memory_instance
    raise ValueError(
        f"Unknown DB_MODE: {resolved!r}. Valid values: postgres | neon | local"
    )


def get_db(mode: str | None = None) -> DatabaseClient:
    """Deprecated alias for get_db_client(). Use get_db_client() in new code."""
    return get_db_client(mode=mode)
