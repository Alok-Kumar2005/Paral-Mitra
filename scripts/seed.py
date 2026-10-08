"""Seed data loader and validator for Parali Mitra.

Validates all CSV seed files (constants, machines, buyers) against Pydantic models
and loads them into Postgres or the local in-memory store with idempotent upserts,
printing a comprehensive report.

Usage:
    python scripts/seed.py --mode local          # offline (default)
    python scripts/seed.py --mode postgres       # Neon Postgres (requires DATABASE_URL)
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import os
from dotenv import load_dotenv

load_dotenv()

from pydantic import ValidationError

from src.common.constants import AgriculturalConstants, MissingConstantError
from src.common.db import DatabaseClient, get_db_client
from src.common.models import Buyer, Machine


@dataclass
class SeedValidationReport:
    file_name: str
    total_rows: int = 0
    valid_rows: int = 0
    rejected_rows: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


def load_and_validate_machines(
    csv_path: Path, db: DatabaseClient
) -> tuple[list[Machine], SeedValidationReport]:
    report = SeedValidationReport(file_name=csv_path.name)
    valid_machines: list[Machine] = []

    if not csv_path.exists():
        report.errors.append({"row": 0, "error": f"File not found: {csv_path}"})
        return valid_machines, report

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=2):
            report.total_rows += 1
            clean_row: dict[str, Any] = {
                k.strip(): v.strip() for k, v in row.items() if k
            }
            # Normalize optional fields
            if clean_row.get("owner_telegram_chat_id") == "":
                clean_row["owner_telegram_chat_id"] = None
            if "is_synthetic" in clean_row:
                clean_row["is_synthetic"] = clean_row["is_synthetic"].lower() in ("true", "1", "yes")

            try:
                machine = Machine.model_validate(clean_row)
                valid_machines.append(machine)
                db.put_machine(machine)
                report.valid_rows += 1
            except ValidationError as e:
                report.rejected_rows += 1
                error_msgs = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
                report.errors.append({"row": idx, "data": clean_row, "error": "; ".join(error_msgs)})
            except Exception as e:
                report.rejected_rows += 1
                report.errors.append({"row": idx, "data": clean_row, "error": str(e)})

    return valid_machines, report


def load_and_validate_buyers(
    csv_path: Path, db: DatabaseClient
) -> tuple[list[Buyer], SeedValidationReport]:
    report = SeedValidationReport(file_name=csv_path.name)
    valid_buyers: list[Buyer] = []

    if not csv_path.exists():
        report.errors.append({"row": 0, "error": f"File not found: {csv_path}"})
        return valid_buyers, report

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, start=2):
            report.total_rows += 1
            clean_row: dict[str, Any] = {
                k.strip(): v.strip() for k, v in row.items() if k
            }
            if "is_synthetic" in clean_row:
                clean_row["is_synthetic"] = clean_row["is_synthetic"].lower() in ("true", "1", "yes")

            try:
                buyer = Buyer.model_validate(clean_row)
                valid_buyers.append(buyer)
                db.put_buyer(buyer)
                report.valid_rows += 1
            except ValidationError as e:
                report.rejected_rows += 1
                error_msgs = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
                report.errors.append({"row": idx, "data": clean_row, "error": "; ".join(error_msgs)})
            except Exception as e:
                report.rejected_rows += 1
                report.errors.append({"row": idx, "data": clean_row, "error": str(e)})

    return valid_buyers, report


def seed_database(
    seed_dir: Path | str | DatabaseClient | None = None,
    db_mode: str | None = None,
    db: DatabaseClient | None = None,
) -> dict[str, SeedValidationReport]:
    """Validates and loads all seed files into the specified database."""
    default_seed_dir = Path(__file__).resolve().parents[1] / "data" / "seed"
    if isinstance(seed_dir, DatabaseClient):
        db = seed_dir
        base_dir = default_seed_dir
    elif seed_dir is not None:
        base_dir = Path(seed_dir)
    else:
        base_dir = default_seed_dir

    if db is None:
        resolved_mode = db_mode or os.getenv("DB_MODE", "local")
        db = get_db_client(mode=resolved_mode)

    reports: dict[str, SeedValidationReport] = {}

    print("\n=======================================================")
    print(f"[SEED] PARALI MITRA DATA INGESTION")
    print("=======================================================")
    print(f"Source directory: {base_dir.resolve()}\n")

    # 1. Validate Constants
    constants_csv = base_dir / "constants.csv"
    const_report = SeedValidationReport(file_name="constants.csv")
    try:
        constants = AgriculturalConstants.load_from_csv(constants_csv)
        const_report.total_rows = len(constants.REQUIRED_KEYS)
        const_report.valid_rows = len(constants.REQUIRED_KEYS)
        print(f"[OK] Constants: Successfully loaded {const_report.valid_rows} required constants.")
    except (MissingConstantError, FileNotFoundError) as e:
        const_report.rejected_rows = 1
        const_report.errors.append({"row": 0, "error": str(e)})
        print(f"[ERROR] Constants: FAILED to load: {e}")
    reports["constants"] = const_report

    # 2. Validate Machines
    machines_csv = base_dir / "machines.csv"
    _, m_report = load_and_validate_machines(machines_csv, db)
    reports["machines"] = m_report
    print(
        f"[OK] Machines:  {m_report.valid_rows}/{m_report.total_rows} valid records loaded. "
        f"({m_report.rejected_rows} rejected)"
    )
    if m_report.errors:
        for err in m_report.errors:
            print(f"   [WARN] Row {err['row']}: {err['error']}")

    # 3. Validate Buyers
    buyers_csv = base_dir / "buyers.csv"
    _, b_report = load_and_validate_buyers(buyers_csv, db)
    reports["buyers"] = b_report
    print(
        f"[OK] Buyers:    {b_report.valid_rows}/{b_report.total_rows} valid records loaded. "
        f"({b_report.rejected_rows} rejected)"
    )
    if b_report.errors:
        for err in b_report.errors:
            print(f"   [WARN] Row {err['row']}: {err['error']}")

    print("=======================================================\n")
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Parali Mitra database from CSV files.")
    parser.add_argument(
        "--seed-dir",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "data" / "seed"),
        help="Path to data/seed folder",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="local",
        choices=["local", "postgres", "neon"],
        help="Database target mode: local (default), postgres, or neon",
    )
    # Legacy alias kept for backward compat with any existing scripts
    parser.add_argument(
        "--db-mode",
        type=str,
        default=None,
        choices=["local", "postgres", "neon"],
        help="Alias for --mode (deprecated)",
    )
    args = parser.parse_args()

    # --db-mode takes precedence if both given (backward compat)
    mode = args.db_mode or args.mode

    reports = seed_database(seed_dir=args.seed_dir, db_mode=mode)
    has_errors = any(r.rejected_rows > 0 for r in reports.values())
    if has_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
