"""Unit tests for constants loader and strict error behavior."""

import tempfile
from pathlib import Path
import pytest

from src.common.constants import (
    AgriculturalConstants,
    MissingConstantError,
    get_constants,
)


def test_load_constants_from_seed():
    constants = get_constants()
    assert constants.residue_tonnes_per_acre > 0
    assert constants.diesel_cost_per_litre > 0
    assert constants.baling_cost_per_acre > 0
    assert constants.max_search_radius_km == 50.0


def test_missing_constant_fails_loudly():
    incomplete_csv = """key,value,unit,description
residue_tonnes_per_acre,2.8,tonnes/acre,Residue
diesel_cost_per_litre,90.0,INR,Diesel
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(incomplete_csv)
        f_path = Path(f.name)

    try:
        with pytest.raises(MissingConstantError) as excinfo:
            AgriculturalConstants.load_from_csv(f_path)
        assert "Missing required agricultural constants" in str(excinfo.value)
    finally:
        f_path.unlink(missing_ok=True)


def test_invalid_constant_value_fails_loudly():
    bad_csv = """key,value,unit,description
residue_tonnes_per_acre,NOT_A_FLOAT,tonnes/acre,Residue
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(bad_csv)
        f_path = Path(f.name)

    try:
        with pytest.raises(MissingConstantError) as excinfo:
            AgriculturalConstants.load_from_csv(f_path)
        assert "is not a valid float" in str(excinfo.value)
    finally:
        f_path.unlink(missing_ok=True)


def test_empty_constant_value_fails_loudly():
    empty_val_csv = """key,value,unit,description
residue_tonnes_per_acre,,tonnes/acre,Residue
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(empty_val_csv)
        f_path = Path(f.name)

    try:
        with pytest.raises(MissingConstantError) as excinfo:
            AgriculturalConstants.load_from_csv(f_path)
        assert "has an empty value" in str(excinfo.value)
    finally:
        f_path.unlink(missing_ok=True)


def test_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        AgriculturalConstants.load_from_csv(Path("non_existent_file.csv"))
