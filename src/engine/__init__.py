"""Parali Mitra pure deterministic residue management optimization engine."""

from __future__ import annotations

from src.engine.economics import compute_ex_situ_economics, compute_in_situ_cost, get_burning_fine
from src.engine.geo import get_grid_cell_id, haversine_distance
from src.engine.hotspots import compute_gap
from src.engine.models import (
    DailyWeather,
    FarmerProfile,
    GridCellGap,
    Option,
    RankingResult,
    RankingWeights,
    WeatherForecast,
)
from src.engine.recommender import rank_options
from src.engine.schedule import compute_work_duration_days, get_machine_speed_acres_per_hour, simulate_schedule
from src.engine.scorer import score_and_rank_options

__all__ = [
    "rank_options",
    "compute_gap",
    "haversine_distance",
    "get_grid_cell_id",
    "compute_in_situ_cost",
    "compute_ex_situ_economics",
    "get_burning_fine",
    "compute_work_duration_days",
    "get_machine_speed_acres_per_hour",
    "simulate_schedule",
    "score_and_rank_options",
    "DailyWeather",
    "WeatherForecast",
    "FarmerProfile",
    "RankingWeights",
    "Option",
    "RankingResult",
    "GridCellGap",
]
