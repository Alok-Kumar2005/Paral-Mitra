"""Unit tests for seed loading script and row validation reporting."""

import tempfile
from pathlib import Path

from scripts.seed import (
    load_and_validate_buyers,
    load_and_validate_machines,
    seed_database,
)
from src.common.db import InMemoryDatabase


def test_seed_database_default():
    seed_dir = Path(__file__).resolve().parents[1] / "data" / "seed"
    reports = seed_database(seed_dir=seed_dir, db_mode="local")

    assert "constants" in reports
    assert reports["constants"].rejected_rows == 0
    assert reports["constants"].valid_rows > 0

    assert "machines" in reports
    assert reports["machines"].total_rows == 12
    assert reports["machines"].valid_rows == 12
    assert reports["machines"].rejected_rows == 0

    assert "buyers" in reports
    assert reports["buyers"].total_rows == 10
    assert reports["buyers"].valid_rows == 10
    assert reports["buyers"].rejected_rows == 0


def test_seed_rejects_invalid_machine_row():
    db = InMemoryDatabase()
    csv_content = """machine_id,owner_name,owner_phone,owner_telegram_chat_id,machine_type,village,district,lat,lon,rate_per_acre,travel_charge_per_km,service_radius_km,available_from,blocked_dates,source,is_synthetic
MCH_VALID,Valid Owner,+919876543210,,SUPER_SEEDER,V1,D1,30.5,76.5,2000.0,20.0,15.0,2026-10-15,,SEED,True
MCH_INVALID,Invalid Owner,+919876543210,,SUPER_SEEDER,V1,D1,120.5,76.5,2000.0,20.0,15.0,2026-10-15,,SEED,True
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
        f_path = Path(f.name)

    try:
        valid_machines, report = load_and_validate_machines(f_path, db)
        assert len(valid_machines) == 1
        assert report.total_rows == 2
        assert report.valid_rows == 1
        assert report.rejected_rows == 1
        assert len(report.errors) == 1
        assert "lat" in report.errors[0]["error"]
    finally:
        f_path.unlink(missing_ok=True)


def test_seed_rejects_invalid_buyer_row():
    db = InMemoryDatabase()
    csv_content = """buyer_id,name,buyer_type,lat,lon,price_per_tonne,min_quantity_tonnes,transport_terms,phone,source,is_synthetic
BYR_VALID,Good Buyer,CBG_PLANT,30.5,76.5,1800.0,10.0,EX_FARM,+919876543210,SEED,True
BYR_BAD,Bad Phone Buyer,CBG_PLANT,30.5,76.5,1800.0,10.0,EX_FARM,123,SEED,True
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
        f_path = Path(f.name)

    try:
        valid_buyers, report = load_and_validate_buyers(f_path, db)
        assert len(valid_buyers) == 1
        assert report.total_rows == 2
        assert report.valid_rows == 1
        assert report.rejected_rows == 1
        assert "phone" in report.errors[0]["error"]
    finally:
        f_path.unlink(missing_ok=True)
