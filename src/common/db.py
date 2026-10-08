"""Database access layer supporting both AWS DynamoDB and local in-memory storage."""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from src.common.models import (
    Booking,
    BookingStatus,
    Buyer,
    FarmerSession,
    Hotspot,
    Machine,
)


def _float_to_decimal(obj: Any) -> Any:
    """Recursively converts float values to Decimal for DynamoDB serialization."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: _float_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_float_to_decimal(v) for v in obj]
    return obj


def _decimal_to_float(obj: Any) -> Any:
    """Recursively converts Decimal values back to float/int."""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    elif isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_decimal_to_float(v) for v in obj]
    return obj


class DatabaseClient(ABC):
    """Abstract interface for all Parali Mitra database operations."""

    @abstractmethod
    def put_machine(self, machine: Machine) -> None: ...

    @abstractmethod
    def get_machine(self, machine_id: str) -> Machine | None: ...

    @abstractmethod
    def list_machines(self, district: str | None = None) -> list[Machine]: ...

    @abstractmethod
    def put_buyer(self, buyer: Buyer) -> None: ...

    @abstractmethod
    def get_buyer(self, buyer_id: str) -> Buyer | None: ...

    @abstractmethod
    def list_buyers(self) -> list[Buyer]: ...

    @abstractmethod
    def put_booking(self, booking: Booking) -> None: ...

    @abstractmethod
    def get_booking(self, booking_id: str) -> Booking | None: ...

    @abstractmethod
    def list_bookings_by_farmer(self, farmer_chat_id: int) -> list[Booking]: ...

    @abstractmethod
    def update_booking_status(self, booking_id: str, status: BookingStatus) -> Booking | None: ...

    @abstractmethod
    def put_session(self, session: FarmerSession) -> None: ...

    @abstractmethod
    def get_session(self, chat_id: int) -> FarmerSession | None: ...

    @abstractmethod
    def put_hotspots(self, hotspots: list[Hotspot]) -> int: ...

    @abstractmethod
    def list_hotspots(self) -> list[Hotspot]: ...

    @abstractmethod
    def is_update_processed(self, update_id: str | int) -> bool: ...

    @abstractmethod
    def mark_update_processed(self, update_id: str | int, ttl_seconds: int = 86400) -> None: ...

    @abstractmethod
    def clear_all(self) -> None: ...


class InMemoryDatabase(DatabaseClient):
    """Local in-memory storage implementation for tests and offline development."""

    def __init__(self) -> None:
        self.machines: dict[str, dict[str, Any]] = {}
        self.buyers: dict[str, dict[str, Any]] = {}
        self.bookings: dict[str, dict[str, Any]] = {}
        self.sessions: dict[int, dict[str, Any]] = {}
        self.hotspots: dict[str, dict[str, Any]] = {}
        self.processed_updates: dict[str, int] = {}  # update_id -> ttl_timestamp

    def clear_all(self) -> None:
        self.machines.clear()
        self.buyers.clear()
        self.bookings.clear()
        self.sessions.clear()
        self.hotspots.clear()
        self.processed_updates.clear()

    def put_machine(self, machine: Machine) -> None:
        self.machines[machine.machine_id] = machine.model_dump(mode="json")

    def get_machine(self, machine_id: str) -> Machine | None:
        data = self.machines.get(machine_id)
        return Machine.model_validate(data) if data else None

    def list_machines(self, district: str | None = None) -> list[Machine]:
        res = [Machine.model_validate(d) for d in self.machines.values()]
        if district:
            res = [m for m in res if m.district.strip().lower() == district.strip().lower()]
        return res

    def put_buyer(self, buyer: Buyer) -> None:
        self.buyers[buyer.buyer_id] = buyer.model_dump(mode="json")

    def get_buyer(self, buyer_id: str) -> Buyer | None:
        data = self.buyers.get(buyer_id)
        return Buyer.model_validate(data) if data else None

    def list_buyers(self) -> list[Buyer]:
        return [Buyer.model_validate(d) for d in self.buyers.values()]

    def put_booking(self, booking: Booking) -> None:
        self.bookings[booking.booking_id] = booking.model_dump(mode="json")

    def get_booking(self, booking_id: str) -> Booking | None:
        data = self.bookings.get(booking_id)
        return Booking.model_validate(data) if data else None

    def list_bookings_by_farmer(self, farmer_chat_id: int) -> list[Booking]:
        return [
            Booking.model_validate(d)
            for d in self.bookings.values()
            if d.get("farmer_chat_id") == farmer_chat_id
        ]

    def update_booking_status(self, booking_id: str, status: BookingStatus) -> Booking | None:
        data = self.bookings.get(booking_id)
        if not data:
            return None
        data["status"] = status.value
        booking = Booking.model_validate(data)
        self.bookings[booking_id] = booking.model_dump(mode="json")
        return booking

    def put_session(self, session: FarmerSession) -> None:
        self.sessions[session.chat_id] = session.model_dump(mode="json")

    def get_session(self, chat_id: int) -> FarmerSession | None:
        data = self.sessions.get(chat_id)
        return FarmerSession.model_validate(data) if data else None

    def put_hotspots(self, hotspots: list[Hotspot]) -> int:
        now_epoch = int(time.time())
        count = 0
        for h in hotspots:
            # Expire in 72 hours if ttl not set
            ttl = h.ttl or (now_epoch + 72 * 3600)
            dumped = h.model_dump(mode="json")
            dumped["ttl"] = ttl
            key = f"{h.grid_cell}#{h.acq_date.isoformat()}"
            self.hotspots[key] = dumped
            count += 1
        return count

    def list_hotspots(self) -> list[Hotspot]:
        now_epoch = int(time.time())
        active = []
        for d in self.hotspots.values():
            if d.get("ttl", 0) >= now_epoch:
                active.append(Hotspot.model_validate(d))
        return active

    def is_update_processed(self, update_id: str | int) -> bool:
        uid = str(update_id)
        expiry = self.processed_updates.get(uid)
        if expiry is None:
            return False
        if time.time() > expiry:
            del self.processed_updates[uid]
            return False
        return True

    def mark_update_processed(self, update_id: str | int, ttl_seconds: int = 86400) -> None:
        uid = str(update_id)
        self.processed_updates[uid] = int(time.time()) + ttl_seconds


class DynamoDatabase(DatabaseClient):
    """Production DynamoDB storage implementation."""

    def __init__(
        self,
        table_prefix: str = "ParaliMitra_",
        region_name: str | None = None,
    ) -> None:
        import boto3

        region = region_name or os.getenv("AWS_REGION", "ap-south-1")
        self.dynamodb = boto3.resource("dynamodb", region_name=region)
        self.machines_table = self.dynamodb.Table(f"{table_prefix}Machines")
        self.buyers_table = self.dynamodb.Table(f"{table_prefix}Buyers")
        self.bookings_table = self.dynamodb.Table(f"{table_prefix}Bookings")
        self.sessions_table = self.dynamodb.Table(f"{table_prefix}Sessions")
        self.hotspots_table = self.dynamodb.Table(f"{table_prefix}Hotspots")
        self.updates_table = self.dynamodb.Table(f"{table_prefix}ProcessedUpdates")

    def clear_all(self) -> None:
        """Caution: Only for testing. Not recommended in production."""
        pass

    def put_machine(self, machine: Machine) -> None:
        item = _float_to_decimal(machine.model_dump(mode="json"))
        self.machines_table.put_item(Item=item)

    def get_machine(self, machine_id: str) -> Machine | None:
        response = self.machines_table.get_item(Key={"machine_id": machine_id})
        item = response.get("Item")
        return Machine.model_validate(_decimal_to_float(item)) if item else None

    def list_machines(self, district: str | None = None) -> list[Machine]:
        response = self.machines_table.scan()
        items = response.get("Items", [])
        machines = [Machine.model_validate(_decimal_to_float(i)) for i in items]
        if district:
            machines = [m for m in machines if m.district.strip().lower() == district.strip().lower()]
        return machines

    def put_buyer(self, buyer: Buyer) -> None:
        item = _float_to_decimal(buyer.model_dump(mode="json"))
        self.buyers_table.put_item(Item=item)

    def get_buyer(self, buyer_id: str) -> Buyer | None:
        response = self.buyers_table.get_item(Key={"buyer_id": buyer_id})
        item = response.get("Item")
        return Buyer.model_validate(_decimal_to_float(item)) if item else None

    def list_buyers(self) -> list[Buyer]:
        response = self.buyers_table.scan()
        items = response.get("Items", [])
        return [Buyer.model_validate(_decimal_to_float(i)) for i in items]

    def put_booking(self, booking: Booking) -> None:
        item = _float_to_decimal(booking.model_dump(mode="json"))
        self.bookings_table.put_item(Item=item)

    def get_booking(self, booking_id: str) -> Booking | None:
        response = self.bookings_table.get_item(Key={"booking_id": booking_id})
        item = response.get("Item")
        return Booking.model_validate(_decimal_to_float(item)) if item else None

    def list_bookings_by_farmer(self, farmer_chat_id: int) -> list[Booking]:
        response = self.bookings_table.scan()
        items = response.get("Items", [])
        bookings = [Booking.model_validate(_decimal_to_float(i)) for i in items]
        return [b for b in bookings if b.farmer_chat_id == farmer_chat_id]

    def update_booking_status(self, booking_id: str, status: BookingStatus) -> Booking | None:
        response = self.bookings_table.update_item(
            Key={"booking_id": booking_id},
            UpdateExpression="SET #st = :status, updated_at = :now",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":status": status.value,
                ":now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ReturnValues="ALL_NEW",
        )
        item = response.get("Attributes")
        return Booking.model_validate(_decimal_to_float(item)) if item else None

    def put_session(self, session: FarmerSession) -> None:
        item = _float_to_decimal(session.model_dump(mode="json"))
        self.sessions_table.put_item(Item=item)

    def get_session(self, chat_id: int) -> FarmerSession | None:
        response = self.sessions_table.get_item(Key={"chat_id": chat_id})
        item = response.get("Item")
        return FarmerSession.model_validate(_decimal_to_float(item)) if item else None

    def put_hotspots(self, hotspots: list[Hotspot]) -> int:
        now_epoch = int(time.time())
        with self.hotspots_table.batch_writer() as batch:
            for h in hotspots:
                ttl = h.ttl or (now_epoch + 72 * 3600)
                dumped = h.model_dump(mode="json")
                dumped["ttl"] = ttl
                dumped["grid_key"] = f"{h.grid_cell}#{h.acq_date.isoformat()}"
                batch.put_item(Item=_float_to_decimal(dumped))
        return len(hotspots)

    def list_hotspots(self) -> list[Hotspot]:
        response = self.hotspots_table.scan()
        items = response.get("Items", [])
        return [Hotspot.model_validate(_decimal_to_float(i)) for i in items]

    def is_update_processed(self, update_id: str | int) -> bool:
        response = self.updates_table.get_item(Key={"update_id": str(update_id)})
        return "Item" in response

    def mark_update_processed(self, update_id: str | int, ttl_seconds: int = 86400) -> None:
        ttl = int(time.time()) + ttl_seconds
        self.updates_table.put_item(
            Item={"update_id": str(update_id), "ttl": ttl}
        )


_in_memory_db_instance = InMemoryDatabase()


def get_db(mode: str | None = None) -> DatabaseClient:
    """Returns database client instance based on DATABASE_MODE environment variable or parameter."""
    resolved_mode = (mode or os.getenv("DATABASE_MODE", "local")).strip().lower()
    if resolved_mode in ("dynamodb", "aws"):
        return DynamoDatabase()
    return _in_memory_db_instance
