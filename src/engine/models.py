"""Domain models and data structures for the Parali Mitra recommendation engine."""

from __future__ import annotations

from datetime import date as dt_date
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from src.common.models import OptionType


class DailyWeather(BaseModel):
    """Daily weather forecast record."""
    model_config = ConfigDict(extra="forbid")

    date: dt_date = Field(..., description="Forecast date")
    precipitation_mm: float = Field(default=0.0, ge=0.0, description="Forecast precipitation in mm")
    precipitation_probability_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Precipitation probability in %")
    max_wind_kmh: float = Field(default=0.0, ge=0.0, description="Forecast maximum wind speed in km/h")


class WeatherForecast(BaseModel):
    """Collection of daily weather forecast entries."""
    model_config = ConfigDict(extra="forbid")

    forecasts: list[DailyWeather] = Field(default_factory=list, description="List of daily forecast records")

    def to_map(self) -> dict[dt_date, DailyWeather]:
        """Returns a dictionary mapping date to DailyWeather."""
        return {item.date: item for item in self.forecasts}


class FarmerProfile(BaseModel):
    """Normalized farmer input for residue management evaluation."""
    model_config = ConfigDict(extra="forbid")

    acres: float = Field(..., gt=0.0, description="Farm size in acres")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Farm latitude")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Farm longitude")
    sowing_deadline: dt_date = Field(..., description="Target wheat sowing deadline")
    village_text: str | None = Field(default=None, description="Village / District identifier")


class RankingWeights(BaseModel):
    """Configurable weights for multi-criteria option ranking."""
    model_config = ConfigDict(extra="forbid")

    cost_weight: float = Field(default=0.50, ge=0.0, description="Weight for net cost (lower is better)")
    slack_weight: float = Field(default=0.30, ge=0.0, description="Weight for time slack (more slack is better)")
    distance_weight: float = Field(default=0.20, ge=0.0, description="Weight for operational distance (closer is better)")


class Option(BaseModel):
    """Evaluated residue management option (In-situ or Ex-situ)."""
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(..., description="Unique generated option identifier")
    option_type: OptionType | str = Field(..., description="IN_SITU or EX_SITU")
    category: str = Field(..., description="Machine or aggregation category (e.g. SUPER_SEEDER, BALER_BUYER)")
    target_id: str = Field(..., description="Machine ID or Buyer ID / combo")
    target_name: str = Field(..., description="Provider or facility name")
    village: str = Field(..., description="Location of machinery/facility")
    distance_km: float = Field(..., ge=0.0, description="Distance from farm in km")
    net_cost: float = Field(..., description="Net cost in INR (negative value represents net profit)")
    cost_breakdown: dict[str, float] = Field(default_factory=dict, description="Itemized costs and revenues")
    earliest_date: dt_date = Field(..., description="Earliest date work can commence")
    completion_date: dt_date = Field(..., description="Date on which clearing/sowing finishes")
    slack_days: int = Field(..., description="Days remaining between completion and sowing deadline")
    score: float = Field(default=0.0, description="Ranked composite multi-criteria score")
    reasons: list[str] = Field(default_factory=list, description="Human-readable breakdown explaining metrics")
    is_feasible: bool = Field(default=True, description="Whether option meets all operational constraints")
    infeasible_reasons: list[str] = Field(default_factory=list, description="Reasons if option is not feasible")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Supplemental metadata for booking/routing")


class RankingResult(BaseModel):
    """Result of residue management option evaluation and ranking."""
    model_config = ConfigDict(extra="forbid")

    feasible: list[Option] = Field(default_factory=list, description="Ranked feasible options")
    infeasible: list[Option] = Field(default_factory=list, description="Filtered out infeasible options with explanations")

    @property
    def best_option(self) -> Option | None:
        """Returns highest-ranked feasible option if available."""
        return self.feasible[0] if self.feasible else None

    def all_options(self) -> list[Option]:
        """Returns all evaluated options."""
        return self.feasible + self.infeasible

    def __len__(self) -> int:
        return len(self.feasible)

    def __iter__(self):
        return iter(self.feasible)


class GridCellGap(BaseModel):
    """Aggregated hotspot cluster and machinery coverage gap."""
    model_config = ConfigDict(extra="forbid")

    grid_cell: str = Field(..., description="Spatial grid identifier")
    lat: float = Field(..., ge=-90.0, le=90.0, description="Centroid latitude of grid cell")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Centroid longitude of grid cell")
    fire_count: int = Field(..., ge=0, description="Count of active fire hotspots in cell")
    total_frp: float = Field(..., ge=0.0, description="Sum of Fire Radiative Power (MW)")
    max_frp: float = Field(..., ge=0.0, description="Peak Fire Radiative Power (MW)")
    nearest_machine_id: str | None = Field(default=None, description="ID of closest machine")
    nearest_machine_name: str | None = Field(default=None, description="Name/Owner of closest machine")
    nearest_machine_distance_km: float | None = Field(default=None, ge=0.0, description="Distance to closest machine in km")
    is_gap: bool = Field(default=False, description="True if cell has active fires but no machine within radius")
