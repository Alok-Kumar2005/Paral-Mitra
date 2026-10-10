"""Domain models for Parali Mitra data layer.

All monetary and area values are stored as float in Python (matching numeric in Postgres).
The DB layer casts to/from str for chat_id at the Postgres boundary; Python always uses int.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Enumerations ──────────────────────────────────────────────────────────────


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    PENDING_MANUAL = "PENDING_MANUAL"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


class ProviderStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ProviderType(str, Enum):
    CHC = "CHC"
    BUYER = "BUYER"


class MachineType(str, Enum):
    SUPER_SEEDER = "SUPER_SEEDER"
    HAPPY_SEEDER = "HAPPY_SEEDER"
    SMART_SEEDER = "SMART_SEEDER"
    BALER = "BALER"
    MULCHER_CHOOPER = "MULCHER_CHOPPER"
    ROTAVATOR = "ROTAVATOR"
    ZERO_TILL_DRILL = "ZERO_TILL_DRILL"
    REVERSIBLE_PLOUGH = "REVERSIBLE_PLOUGH"
    OTHER = "OTHER"


class BuyerType(str, Enum):
    CBG_PLANT = "CBG_PLANT"
    BIOMASS_POWER = "BIOMASS_POWER"
    PELLET_PLANT = "PELLET_PLANT"
    CARDBOARD_MILL = "CARDBOARD_MILL"
    ETHANOL_PLANT = "ETHANOL_PLANT"
    OTHER = "OTHER"


class TransportTerms(str, Enum):
    EX_FARM = "EX_FARM"        # Buyer arranges pickup from farm
    DELIVERED = "DELIVERED"    # Farmer/aggregator delivers to plant gate
    NEGOTIABLE = "NEGOTIABLE"


class OptionType(str, Enum):
    IN_SITU = "IN_SITU"
    EX_SITU = "EX_SITU"


# ── Provider marketplace ──────────────────────────────────────────────────────


class Provider(BaseModel):
    """A registered CHC or commercial buyer operator in the marketplace."""
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(..., min_length=1)
    provider_type: ProviderType | str = Field(..., description="CHC or BUYER")
    name: str = Field(..., min_length=1)
    contact_phone: str = Field(..., min_length=10)
    telegram_chat_id: str | None = Field(default=None, description="Linked Telegram chat ID")
    district: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    status: ProviderStatus = Field(default=ProviderStatus.PENDING)
    verified_by: str | None = Field(default=None)
    verified_at: datetime | None = Field(default=None)
    is_directory_listing: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utc_now)


# ── Agricultural resources ────────────────────────────────────────────────────


class Machine(BaseModel):
    """Agricultural machinery registered for in-situ or baling custom hiring."""
    model_config = ConfigDict(extra="forbid")

    machine_id: str = Field(..., min_length=1, description="Unique machine identifier (e.g. MCH_001)")
    # provider_id is optional to preserve backward compat with seed CSV rows
    provider_id: str | None = Field(default=None, description="FK to providers table")
    # Legacy owner fields kept for seed CSV and in-memory compat
    owner_name: str = Field(default="", description="Owner or CHC name (legacy; use provider)")
    owner_phone: str = Field(default="", description="Owner contact number (legacy; use provider)")
    owner_telegram_chat_id: int | None = Field(default=None, description="Telegram Chat ID for notifications")
    machine_type: MachineType | str = Field(..., description="Type of machinery")
    village: str = Field(..., min_length=1, description="Base village")
    district: str = Field(..., min_length=1, description="Base district")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude")
    rate_per_acre: float = Field(..., ge=0.0, description="Rental charge per acre in INR")
    travel_charge_per_km: float = Field(..., ge=0.0, description="Charge per km of transit in INR")
    service_radius_km: float = Field(..., gt=0.0, description="Maximum operational radius in km")
    available_from: date = Field(..., description="Date from which machine is available")
    blocked_dates: list[date] = Field(default_factory=list, description="Dates already booked or unavailable")
    status: str = Field(default="ACTIVE", description="ACTIVE or INACTIVE")
    rating_avg: float | None = Field(default=None, description="Average rating (1-5)")
    rating_count: int = Field(default=0, description="Number of ratings received")
    source: str = Field(default="MANUAL", description="Source registry (e.g. CHC_PORTAL, DIRECT, SEED)")
    is_synthetic: bool = Field(default=False, description="Flag indicating synthetic test data")

    @field_validator("blocked_dates", mode="before")
    @classmethod
    def parse_blocked_dates(cls, v: Any) -> list[date]:
        if isinstance(v, str):
            if not v.strip():
                return []
            # Support semicolon or comma separated dates in CSV
            parts = [p.strip() for p in v.replace(";", ",").split(",") if p.strip()]
            return [date.fromisoformat(p) for p in parts]
        return v or []


class Buyer(BaseModel):
    """Ex-situ commercial buyer for paddy straw (CBG, Biomass, Pellets)."""
    model_config = ConfigDict(extra="forbid")

    buyer_id: str = Field(..., min_length=1, description="Unique buyer identifier (e.g. BYR_001)")
    provider_id: str | None = Field(default=None, description="FK to providers table")
    name: str = Field(..., min_length=1, description="Company or plant name")
    buyer_type: BuyerType | str = Field(..., description="Type of buyer facility")
    district: str = Field(default="", description="District where buyer is located")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude")
    price_per_tonne: float = Field(..., ge=0.0, description="Offered price per metric tonne in INR")
    min_quantity_tonnes: float = Field(..., ge=0.0, description="Minimum procurement volume in tonnes")
    transport_terms: TransportTerms | str = Field(..., description="Logistics arrangement terms")
    phone: str = Field(..., min_length=10, description="Procurement contact number")
    source: str = Field(default="MANUAL", description="Source directory")
    is_synthetic: bool = Field(default=False, description="Flag indicating synthetic test data")


from dataclasses import dataclass


# ── Bookings ──────────────────────────────────────────────────────────────────


class Booking(BaseModel):
    """A farmer's booking request for a machine or buyer dispatch."""
    model_config = ConfigDict(extra="forbid")

    booking_id: str = Field(..., min_length=1, description="Unique booking ID (e.g. BK-XXXXXXXX)")
    farmer_chat_id: int = Field(..., description="Telegram chat ID of the farmer")
    provider_id: str | None = Field(default=None, description="FK to providers table")
    option_type: OptionType | str = Field(..., description="IN_SITU or EX_SITU")
    target_id: str = Field(..., min_length=1, description="Machine ID or Buyer ID booked")
    acres: float = Field(..., gt=0.0, description="Land area in acres")
    requested_date: date = Field(..., description="Requested execution date")
    status: BookingStatus = Field(default=BookingStatus.PENDING, description="Current booking status")
    rating: int | None = Field(default=None, ge=1, le=5, description="Farmer rating (1-5)")
    created_at: datetime = Field(default_factory=_utc_now, description="Booking creation timestamp")
    updated_at: datetime = Field(default_factory=_utc_now, description="Last update timestamp")
    completed_at: datetime | None = Field(default=None, description="Completion timestamp")
    expires_at: datetime | None = Field(default=None, description="Auto-expiry timestamp")
    decided_at: datetime | None = Field(default=None, description="Timestamp of accept/reject decision")
    decided_by: str | None = Field(default=None, description="Operator chat ID or system marker that decided")


# ── Interactive Chat Flow ─────────────────────────────────────────────────────


class ChatFlow(BaseModel):
    """State machine for multi-step interactive flows (e.g. /owner registration)."""
    model_config = ConfigDict(extra="forbid")

    chat_id: int = Field(..., description="Telegram chat ID")
    flow: str = Field(..., description="Flow identifier, e.g. OWNER_REGISTER, OWNER_ADD_MACHINE")
    step: str = Field(..., description="Current step in the flow")
    data: dict[str, Any] = Field(default_factory=dict, description="Collected step data")
    attempts: int = Field(default=0, description="Passcode or retry attempts")
    locked_until: datetime | None = Field(default=None, description="Lockout timestamp")
    updated_at: datetime = Field(default_factory=_utc_now)


# ── Public Views & Outbound Notifications ─────────────────────────────────────


class PublicMachineView(BaseModel):
    """Sanitized machine view for public farmer exploration without leaking sensitive owner info before booking."""
    model_config = ConfigDict(extra="forbid")

    machine_id: str
    machine_type: MachineType | str
    village: str
    district: str
    rate_per_acre: float
    travel_charge_per_km: float
    service_radius_km: float
    rating_avg: float | None = None
    rating_count: int = 0
    provider_name: str
    provider_status: ProviderStatus | str
    distance_km: float | None = None


@dataclass
class Notification:
    """Out-of-band notification message emitted by marketplace service functions."""
    chat_id: int
    text: str
    reply_markup: dict[str, Any] | None = None


# ── Farmer session ────────────────────────────────────────────────────────────


class FarmerSession(BaseModel):
    """Farmer profile and interactive session state.

    Persisted to the `farmers` table. The `history` field is a convenience
    cache used by the in-memory backend and the memory.py shim; the Postgres
    backend stores messages in `chat_messages` separately.
    """
    model_config = ConfigDict(extra="forbid")

    chat_id: int = Field(..., description="Telegram user/chat ID")
    language: str = Field(default="hi", description="Preferred language (hi, pa, en)")
    lat: float | None = Field(default=None, ge=-90.0, le=90.0, description="Latitude of the farm")
    lon: float | None = Field(default=None, ge=-180.0, le=180.0, description="Longitude of the farm")
    village_text: str | None = Field(default=None, description="Farmer specified village/district name")
    district: str | None = Field(default=None, description="District of the farm")
    state: str | None = Field(default=None, description="State of the farm")
    acres: float | None = Field(default=None, gt=0.0, description="Total farm acreage")
    crop: str | None = Field(default=None, description="Current crop type")
    sowing_deadline: date | None = Field(default=None, description="Target wheat sowing deadline")
    consent_given_at: datetime | None = Field(default=None, description="Timestamp when farmer gave consent")
    created_at: datetime = Field(default_factory=_utc_now, description="Profile creation timestamp")
    last_seen_at: datetime = Field(default_factory=_utc_now, description="Last activity timestamp")
    last_options: list[dict[str, Any]] | None = Field(default=None, description="Cached evaluated residue options")
    # history: used by InMemoryDatabase and memory.py shim.
    # PostgresClient reads from chat_messages table instead.
    history: list[dict[str, Any]] = Field(default_factory=list, description="Recent conversation turns (messages)")
    updated_at: datetime = Field(default_factory=_utc_now, description="Last session update timestamp")


# ── Conversation memory (Postgres-native) ────────────────────────────────────


class ChatMessage(BaseModel):
    """Individual conversation message persisted to chat_messages table."""
    model_config = ConfigDict(extra="forbid")

    id: int | None = Field(default=None, description="bigserial primary key (set by DB)")
    chat_id: int = Field(..., description="Telegram chat ID")
    role: str = Field(..., description="user or assistant")
    text: str = Field(..., description="Message content")
    created_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime = Field(..., description="Expiry timestamp for prune_expired()")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {v!r}")
        return v


class ChatState(BaseModel):
    """Rolling conversation summary record for a farmer (chat_state table)."""
    model_config = ConfigDict(extra="forbid")

    chat_id: int = Field(..., description="Telegram chat ID")
    summary: str | None = Field(default=None, description="LLM-generated rolling summary")
    summarized_upto: int | None = Field(default=None, description="id of last message summarised")
    version: int = Field(default=0, description="Optimistic concurrency version")
    updated_at: datetime = Field(default_factory=_utc_now)


# ── Environmental monitoring ──────────────────────────────────────────────────


class Hotspot(BaseModel):
    """Active fire detection record from NASA FIRMS.

    expires_at replaces the DynamoDB-era `ttl` epoch integer field.
    A legacy `ttl` property is provided for backward compatibility with
    code that still reads h.ttl (e.g. ingest_fires.py shim period).
    """
    model_config = ConfigDict(extra="forbid")

    grid_cell: str = Field(..., min_length=1, description="Spatial grid cell identifier")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Hotspot latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Hotspot longitude")
    acq_date: date = Field(..., description="Acquisition date")
    acq_time: str | None = Field(default=None, description="Acquisition time string (HHMM UTC)")
    frp: float = Field(..., ge=0.0, description="Fire Radiative Power in MW")
    confidence: str = Field(..., description="Detection confidence (e.g. nominal, high, 85%)")
    expires_at: datetime | None = Field(
        default=None,
        description="Row expiry for prune_expired(); replaces DynamoDB TTL epoch",
    )

    @property
    def ttl(self) -> int | None:
        """Backward-compat shim: returns Unix epoch of expires_at, or None."""
        if self.expires_at is None:
            return None
        return int(self.expires_at.timestamp())

    @ttl.setter
    def ttl(self, epoch: int | None) -> None:
        """Backward-compat shim: sets expires_at from a Unix epoch integer."""
        if epoch is None:
            object.__setattr__(self, "expires_at", None)
        else:
            object.__setattr__(
                self,
                "expires_at",
                datetime.fromtimestamp(epoch, tz=timezone.utc),
            )
