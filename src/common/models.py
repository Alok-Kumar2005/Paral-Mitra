"""Domain models for Parali Mitra data layer."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


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


class Machine(BaseModel):
    """Agricultural machinery registered for in-situ or baling custom hiring."""
    model_config = ConfigDict(extra="forbid")

    machine_id: str = Field(..., min_length=1, description="Unique machine identifier (e.g. MCH_001)")
    owner_name: str = Field(..., min_length=1, description="Owner or CHC name")
    owner_phone: str = Field(..., min_length=10, description="Owner contact number")
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
    name: str = Field(..., min_length=1, description="Company or plant name")
    buyer_type: BuyerType | str = Field(..., description="Type of buyer facility")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude")
    price_per_tonne: float = Field(..., ge=0.0, description="Offered price per metric tonne in INR")
    min_quantity_tonnes: float = Field(..., ge=0.0, description="Minimum procurement volume in tonnes")
    transport_terms: TransportTerms | str = Field(..., description="Logistics arrangement terms")
    phone: str = Field(..., min_length=10, description="Procurement contact number")
    source: str = Field(default="MANUAL", description="Source directory")
    is_synthetic: bool = Field(default=False, description="Flag indicating synthetic test data")


class Booking(BaseModel):
    """A farmer's booking request for a machine or buyer dispatch."""
    model_config = ConfigDict(extra="forbid")

    booking_id: str = Field(..., min_length=1, description="Unique booking ID (e.g. BKG_1001)")
    farmer_chat_id: int = Field(..., description="Telegram chat ID of the farmer")
    option_type: OptionType | str = Field(..., description="IN_SITU or EX_SITU")
    target_id: str = Field(..., min_length=1, description="Machine ID or Buyer ID booked")
    acres: float = Field(..., gt=0.0, description="Land area in acres")
    requested_date: date = Field(..., description="Requested execution date")
    status: BookingStatus = Field(default=BookingStatus.PENDING, description="Current booking status")
    created_at: datetime = Field(default_factory=_utc_now, description="Booking creation timestamp")
    updated_at: datetime = Field(default_factory=_utc_now, description="Last update timestamp")


class FarmerSession(BaseModel):
    """Farmer profile and interactive session state."""
    model_config = ConfigDict(extra="forbid")

    chat_id: int = Field(..., description="Telegram user/chat ID")
    language: str = Field(default="hi", description="Preferred language (hi, pa, en)")
    lat: float | None = Field(default=None, ge=-90.0, le=90.0, description="Latitude of the farm")
    lon: float | None = Field(default=None, ge=-180.0, le=180.0, description="Longitude of the farm")
    village_text: str | None = Field(default=None, description="Farmer specified village/district name")
    acres: float | None = Field(default=None, gt=0.0, description="Total farm acreage")
    sowing_deadline: date | None = Field(default=None, description="Target wheat sowing deadline")
    last_options: list[dict[str, Any]] | None = Field(default=None, description="Cached evaluated residue options")
    updated_at: datetime = Field(default_factory=_utc_now, description="Last session update timestamp")


class Hotspot(BaseModel):
    """Active fire detection record from NASA FIRMS."""
    model_config = ConfigDict(extra="forbid")

    grid_cell: str = Field(..., min_length=1, description="Spatial grid cell identifier")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Hotspot latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Hotspot longitude")
    acq_date: date = Field(..., description="Acquisition date")
    frp: float = Field(..., ge=0.0, description="Fire Radiative Power in MW")
    confidence: str = Field(..., description="Detection confidence (e.g. nominal, high, 85%)")
    ttl: int | None = Field(default=None, description="DynamoDB TTL epoch timestamp")
