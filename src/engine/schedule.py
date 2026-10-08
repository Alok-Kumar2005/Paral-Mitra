"""Deterministic scheduling and weather feasibility simulation for machinery operations."""

from __future__ import annotations

from datetime import date, timedelta
import math
from typing import Mapping

from src.common.constants import AgriculturalConstants
from src.common.models import MachineType
from src.engine.models import DailyWeather


def get_machine_speed_acres_per_hour(
    machine_type: MachineType | str,
    constants: AgriculturalConstants,
) -> float:
    """Returns the operational throughput in acres/hour for a machine type.
    
    Args:
        machine_type: Enum or string identifier of machine type.
        constants: Agricultural constants containing speed specifications.
        
    Returns:
        Throughput in acres/hour.
    """
    mtype_str = str(machine_type.value if hasattr(machine_type, "value") else machine_type).upper()
    if mtype_str == MachineType.SUPER_SEEDER.value:
        return constants.super_seeder_speed_acres_per_hour
    elif mtype_str == MachineType.HAPPY_SEEDER.value:
        return constants.happy_seeder_speed_acres_per_hour
    elif mtype_str == MachineType.SMART_SEEDER.value:
        return constants.super_seeder_speed_acres_per_hour
    elif mtype_str == MachineType.BALER.value:
        return constants.baling_speed_acres_per_hour
    elif mtype_str in (MachineType.MULCHER_CHOOPER.value, "MULCHER", "CHOPPER"):
        return constants.mulcher_speed_acres_per_hour
    elif mtype_str == MachineType.ROTAVATOR.value:
        return constants.mulcher_speed_acres_per_hour
    elif mtype_str == MachineType.ZERO_TILL_DRILL.value:
        return constants.happy_seeder_speed_acres_per_hour
    return 1.0


def compute_work_duration_days(
    acres: float,
    speed_acres_per_hour: float,
    work_hours_per_day: float = 8.0,
) -> int:
    """Computes number of calendar working days needed to cover the acreage.
    
    Args:
        acres: Land area in acres.
        speed_acres_per_hour: Machine throughput in acres per hour.
        work_hours_per_day: Effective daily field working hours (default 8.0).
        
    Returns:
        Integer working days required (minimum 1 day).
    """
    if acres <= 0.0:
        return 1
    daily_capacity = max(0.1, speed_acres_per_hour * work_hours_per_day)
    return max(1, math.ceil(acres / daily_capacity))


def simulate_schedule(
    available_from: date,
    today: date,
    duration_days: int,
    blocked_dates: list[date] | set[date],
    weather_map: Mapping[date, DailyWeather] | None = None,
    rain_threshold_mm: float = 2.5,
    rain_prob_threshold_pct: float = 70.0,
    max_lookahead_days: int = 45,
) -> tuple[date, date, list[date], list[str]]:
    """Simulates day-by-day machine scheduling accounting for blocked dates and rain.
    
    Args:
        available_from: Date when the machine becomes available.
        today: Reference current date.
        duration_days: Number of working days required.
        blocked_dates: Dates on which the machine is already booked or offline.
        weather_map: Daily weather forecasts keyed by date.
        rain_threshold_mm: Precipitation threshold above which work is skipped.
        rain_prob_threshold_pct: Rain probability threshold above which work is skipped.
        max_lookahead_days: Maximum days to project into the future before aborting.
        
    Returns:
        Tuple of (earliest_start_date, completion_date, worked_days, skipped_reasons)
    """
    blocked_set = set(blocked_dates)
    w_map = weather_map or {}
    curr_date = max(available_from, today)

    worked_days: list[date] = []
    skipped_reasons: list[str] = []
    earliest_start: date | None = None

    for _ in range(max_lookahead_days):
        is_blocked = curr_date in blocked_set
        is_rainy = False
        rain_info = ""

        if curr_date in w_map:
            dw = w_map[curr_date]
            if dw.precipitation_mm >= rain_threshold_mm or dw.precipitation_probability_pct >= rain_prob_threshold_pct:
                is_rainy = True
                rain_info = f"{dw.precipitation_mm:.1f}mm rain ({dw.precipitation_probability_pct:.0f}% chance)"

        if is_blocked:
            skipped_reasons.append(f"{curr_date.isoformat()}: Machine previously booked")
        elif is_rainy:
            skipped_reasons.append(f"{curr_date.isoformat()}: Unsuitable weather ({rain_info})")
        else:
            if earliest_start is None:
                earliest_start = curr_date
            worked_days.append(curr_date)
            if len(worked_days) >= duration_days:
                break

        curr_date += timedelta(days=1)

    if earliest_start is None:
        earliest_start = max(available_from, today)
    completion_date = worked_days[-1] if worked_days else curr_date

    return earliest_start, completion_date, worked_days, skipped_reasons
