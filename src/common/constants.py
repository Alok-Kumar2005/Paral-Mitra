"""Deterministic constants loader for Parali Mitra economic & agronomic calculations."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import ClassVar
from pydantic import BaseModel, ConfigDict, Field


class MissingConstantError(ValueError):
    """Raised when a required agricultural or economic constant is missing from constants.csv."""
    pass


class AgriculturalConstants(BaseModel):
    """Immutable, strongly-typed constants loaded from data/seed/constants.csv.
    
    Rule: Never hardcode default fallbacks here. All values MUST be supplied by constants.csv.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    residue_tonnes_per_acre: float = Field(..., description="Paddy straw tonnes generated per acre")
    diesel_cost_per_litre: float = Field(..., description="Benchmark diesel price per litre in INR")
    burning_fine_under_2_acres: float = Field(..., description="NGT fine for burning under 2 acres")
    burning_fine_2_to_5_acres: float = Field(..., description="NGT fine for burning 2 to 5 acres")
    burning_fine_above_5_acres: float = Field(..., description="NGT fine for burning above 5 acres")
    govt_ex_situ_incentive_per_acre: float = Field(..., description="Government incentive per acre for ex-situ")
    baling_cost_per_acre: float = Field(..., description="Contract baling cost per acre in INR")
    baling_speed_acres_per_hour: float = Field(..., description="Baler operational throughput in acres/hour")
    super_seeder_speed_acres_per_hour: float = Field(..., description="Super Seeder throughput in acres/hour")
    happy_seeder_speed_acres_per_hour: float = Field(..., description="Happy Seeder throughput in acres/hour")
    mulcher_speed_acres_per_hour: float = Field(..., description="Mulcher throughput in acres/hour")
    max_search_radius_km: float = Field(..., description="Max radial search threshold in km")
    default_transport_cost_per_tonne_km: float = Field(..., description="Transport cost in INR/tonne-km")

    REQUIRED_KEYS: ClassVar[set[str]] = {
        "residue_tonnes_per_acre",
        "diesel_cost_per_litre",
        "burning_fine_under_2_acres",
        "burning_fine_2_to_5_acres",
        "burning_fine_above_5_acres",
        "govt_ex_situ_incentive_per_acre",
        "baling_cost_per_acre",
        "baling_speed_acres_per_hour",
        "super_seeder_speed_acres_per_hour",
        "happy_seeder_speed_acres_per_hour",
        "mulcher_speed_acres_per_hour",
        "max_search_radius_km",
        "default_transport_cost_per_tonne_km",
    }

    @classmethod
    def load_from_csv(cls, csv_path: str | Path) -> AgriculturalConstants:
        """Loads and strictly validates constants from a CSV file.
        
        Args:
            csv_path: Absolute or relative path to constants.csv
            
        Returns:
            AgriculturalConstants instance
            
        Raises:
            FileNotFoundError: If the CSV file does not exist.
            MissingConstantError: If any required constant key is absent or empty.
        """
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Constants file not found at: {path.resolve()}")

        raw_data: dict[str, float] = {}
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row_idx, row in enumerate(reader, start=2):
                key = (row.get("key") or "").strip()
                val_str = (row.get("value") or "").strip()
                if not key:
                    continue
                if not val_str:
                    raise MissingConstantError(f"Row {row_idx}: Constant '{key}' has an empty value in {path}")
                try:
                    raw_data[key] = float(val_str)
                except ValueError as e:
                    raise MissingConstantError(
                        f"Row {row_idx}: Constant '{key}' value '{val_str}' is not a valid float: {e}"
                    ) from e

        missing = cls.REQUIRED_KEYS - set(raw_data.keys())
        if missing:
            raise MissingConstantError(
                f"Missing required agricultural constants in {path.name}: {sorted(missing)}. "
                "All parameters must be explicitly defined."
            )

        return cls(**{k: raw_data[k] for k in cls.REQUIRED_KEYS})


_DEFAULT_CSV_PATH = Path(__file__).resolve().parents[2] / "data" / "seed" / "constants.csv"
_cached_constants: AgriculturalConstants | None = None


def get_constants(csv_path: str | Path | None = None) -> AgriculturalConstants:
    """Returns the singleton constants instance, or loads from the provided path."""
    global _cached_constants
    target_path = Path(csv_path) if csv_path else _DEFAULT_CSV_PATH
    if _cached_constants is None or csv_path is not None:
        _cached_constants = AgriculturalConstants.load_from_csv(target_path)
    return _cached_constants
