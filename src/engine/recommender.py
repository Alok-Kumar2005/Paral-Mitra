"""Core recommendation and ranking engine for Parali Mitra residue management."""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence

from src.common.constants import AgriculturalConstants
from src.common.models import Buyer, FarmerSession, Machine, MachineType, OptionType
from src.engine.economics import compute_ex_situ_economics, compute_in_situ_cost, get_burning_fine
from src.engine.geo import haversine_distance
from src.engine.models import DailyWeather, FarmerProfile, Option, RankingResult, RankingWeights, WeatherForecast
from src.engine.schedule import compute_work_duration_days, get_machine_speed_acres_per_hour, simulate_schedule
from src.engine.scorer import score_and_rank_options


def _normalize_farmer(farmer: FarmerSession | FarmerProfile | dict[str, Any]) -> FarmerProfile:
    """Extracts and validates a FarmerProfile from various accepted input representations."""
    if isinstance(farmer, FarmerProfile):
        return farmer
    if isinstance(farmer, FarmerSession):
        if farmer.acres is None or farmer.lat is None or farmer.lon is None or farmer.sowing_deadline is None:
            raise ValueError("FarmerSession is missing required fields (acres, lat, lon, sowing_deadline)")
        return FarmerProfile(
            acres=farmer.acres,
            lat=farmer.lat,
            lon=farmer.lon,
            sowing_deadline=farmer.sowing_deadline,
            village_text=farmer.village_text,
        )
    if isinstance(farmer, dict):
        return FarmerProfile(**farmer)
    raise TypeError(f"Unsupported farmer profile input type: {type(farmer)}")


def _normalize_weather(
    weather: Sequence[DailyWeather | dict[str, Any]] | WeatherForecast | None,
) -> dict[date, DailyWeather]:
    """Normalizes weather forecast input into a fast date lookup dictionary."""
    if not weather:
        return {}
    if isinstance(weather, WeatherForecast):
        return weather.to_map()

    result: dict[date, DailyWeather] = {}
    for item in weather:
        if isinstance(item, DailyWeather):
            result[item.date] = item
        elif isinstance(item, dict):
            dw = DailyWeather(**item)
            result[dw.date] = dw
    return result


def rank_options(
    farmer: FarmerSession | FarmerProfile | dict[str, Any],
    machines: Sequence[Machine],
    buyers: Sequence[Buyer],
    constants: AgriculturalConstants,
    weather: Sequence[DailyWeather | dict[str, Any]] | WeatherForecast | None,
    today: date,
    completion_buffer_days: int = 2,
    rain_threshold_mm: float = 2.5,
    weights: RankingWeights | None = None,
) -> RankingResult:
    """Evaluates and ranks all feasible and infeasible residue management options for a farmer.
    
    Computes:
    1. In-situ sowing machinery (Super Seeder, Happy Seeder, Smart Seeder).
    2. In-situ incorporation (Mulcher/Chopper, Rotavator).
    3. Ex-situ baling and commercial off-take (Baler + Biomass Buyer).
    
    Evaluates:
    - Net cost / net profit (incorporating machinery rentals, transit, transport, sales, CRM subsidies).
    - Time feasibility (simulation considering weather rain forecasts, blocked dates, and sowing buffer).
    - Service radius constraints.
    - Multi-criteria normalized scoring.
    
    Args:
        farmer: Farmer profile with acreage, location, and sowing deadline.
        machines: Catalog of registered machinery.
        buyers: Directory of commercial biomass buyers.
        constants: Agricultural economic and agronomic constants.
        weather: Weather forecast records.
        today: Reference current date.
        completion_buffer_days: Minimum spare days required before sowing deadline (default 2).
        rain_threshold_mm: Precipitation threshold for field work suspension (default 2.5mm).
        weights: Multi-criteria ranking weights.
        
    Returns:
        RankingResult containing sorted feasible options and documented infeasible options.
    """
    profile = _normalize_farmer(farmer)
    weather_map = _normalize_weather(weather)
    ranking_weights = weights or RankingWeights()

    feasible_options: list[Option] = []
    infeasible_options: list[Option] = []

    acres = profile.acres
    f_lat, f_lon = profile.lat, profile.lon
    sowing_deadline = profile.sowing_deadline
    avoided_fine = get_burning_fine(acres, constants)

    # ---------------------------------------------------------
    # 1. In-Situ Machinery (Super Seeder, Happy Seeder, Mulcher, Rotavator)
    # ---------------------------------------------------------
    for m in machines:
        mtype_str = str(m.machine_type.value if hasattr(m.machine_type, "value") else m.machine_type).upper()
        if mtype_str == MachineType.BALER.value:
            continue  # Handled in Ex-situ workflow

        distance_km = haversine_distance(f_lat, f_lon, m.lat, m.lon)
        speed = get_machine_speed_acres_per_hour(m.machine_type, constants)
        duration_days = compute_work_duration_days(acres, speed)

        start_date, completion_date, worked_days, skipped_reasons = simulate_schedule(
            available_from=m.available_from,
            today=today,
            duration_days=duration_days,
            blocked_dates=m.blocked_dates,
            weather_map=weather_map,
            rain_threshold_mm=rain_threshold_mm,
        )

        slack_days = (sowing_deadline - completion_date).days
        net_cost, breakdown = compute_in_situ_cost(acres, m, distance_km)
        breakdown["avoided_burning_fine"] = avoided_fine

        # Feasibility checks
        infeasible_reasons: list[str] = []
        if distance_km > m.service_radius_km:
            infeasible_reasons.append(
                f"Distance ({distance_km:.1f} km) exceeds machine service radius ({m.service_radius_km:.1f} km)"
            )
        if slack_days < completion_buffer_days:
            infeasible_reasons.append(
                f"Completion date ({completion_date.isoformat()}) provides only {slack_days} slack days "
                f"(minimum buffer required: {completion_buffer_days} days before deadline {sowing_deadline.isoformat()})"
            )

        # Human-readable reasons breakdown
        reasons = [
            f"{mtype_str.replace('_', ' ').title()} ({m.owner_name}): {acres:.1f} acres @ ₹{m.rate_per_acre:,.0f}/acre "
            f"+ ₹{breakdown['travel_cost']:,.0f} travel ({distance_km:.1f} km) = Total ₹{net_cost:,.0f}",
            f"Execution: {duration_days} day(s) starting {start_date.isoformat()}, finishing {completion_date.isoformat()} "
            f"({slack_days} days before sowing deadline)",
            f"Avoids statutory NGT burning fine of ₹{avoided_fine:,.0f}",
        ]
        if skipped_reasons:
            reasons.extend([f"Schedule note: {r}" for r in skipped_reasons[:2]])

        opt = Option(
            option_id=f"OPT_INSITU_{m.machine_id}",
            option_type=OptionType.IN_SITU,
            category=mtype_str,
            target_id=m.machine_id,
            target_name=m.owner_name,
            village=f"{m.village}, {m.district}",
            distance_km=distance_km,
            net_cost=net_cost,
            cost_breakdown=breakdown,
            earliest_date=start_date,
            completion_date=completion_date,
            slack_days=slack_days,
            score=0.0,
            reasons=reasons,
            is_feasible=len(infeasible_reasons) == 0,
            infeasible_reasons=infeasible_reasons,
            metadata={
                "owner_phone": m.owner_phone,
                "owner_telegram_chat_id": m.owner_telegram_chat_id,
                "machine_type": mtype_str,
                "worked_days": [d.isoformat() for d in worked_days],
            },
        )

        if opt.is_feasible:
            feasible_options.append(opt)
        else:
            infeasible_options.append(opt)

    # ---------------------------------------------------------
    # 2. Ex-Situ Baling & Buyer Commercial Off-take
    # ---------------------------------------------------------
    balers = [
        m for m in machines
        if str(m.machine_type.value if hasattr(m.machine_type, "value") else m.machine_type).upper() == MachineType.BALER.value
    ]

    for baler in balers:
        baler_dist = haversine_distance(f_lat, f_lon, baler.lat, baler.lon)
        baler_speed = constants.baling_speed_acres_per_hour
        duration_days = compute_work_duration_days(acres, baler_speed)

        start_date, completion_date, worked_days, skipped_reasons = simulate_schedule(
            available_from=baler.available_from,
            today=today,
            duration_days=duration_days,
            blocked_dates=baler.blocked_dates,
            weather_map=weather_map,
            rain_threshold_mm=rain_threshold_mm,
        )
        slack_days = (sowing_deadline - completion_date).days

        for buyer in buyers:
            buyer_dist = haversine_distance(f_lat, f_lon, buyer.lat, buyer.lon)
            net_cost, breakdown, is_vol_ok, vol_reason = compute_ex_situ_economics(
                acres=acres,
                baler=baler,
                buyer=buyer,
                distance_farmer_baler_km=baler_dist,
                distance_farmer_buyer_km=buyer_dist,
                constants=constants,
            )
            breakdown["avoided_burning_fine"] = avoided_fine

            infeasible_reasons = []
            if baler_dist > baler.service_radius_km:
                infeasible_reasons.append(
                    f"Baler distance ({baler_dist:.1f} km) exceeds service radius ({baler.service_radius_km:.1f} km)"
                )
            if buyer_dist > constants.max_search_radius_km:
                infeasible_reasons.append(
                    f"Buyer distance ({buyer_dist:.1f} km) exceeds max search radius ({constants.max_search_radius_km:.1f} km)"
                )
            if slack_days < completion_buffer_days:
                infeasible_reasons.append(
                    f"Baling completion ({completion_date.isoformat()}) provides only {slack_days} slack days "
                    f"(buffer required: {completion_buffer_days} days)"
                )
            if not is_vol_ok and vol_reason:
                infeasible_reasons.append(vol_reason)

            net_text = f"Net Profit: ₹{abs(net_cost):,.0f}" if net_cost < 0 else f"Net Cost: ₹{net_cost:,.0f}"
            reasons = [
                f"Ex-situ Baling ({baler.owner_name}) + Off-take at {buyer.name} ({buyer_dist:.1f} km): {net_text}",
                f"Yield: {breakdown['residue_tonnes']:.1f} tonnes straw. Off-take revenue: ₹{breakdown['gross_revenue']:,.0f} "
                f"(@ ₹{buyer.price_per_tonne:,.0f}/t) + Govt CRM subsidy: ₹{breakdown['govt_incentive']:,.0f}",
                f"Baling & transit cost: ₹{breakdown['total_baling_cost']:,.0f}, Transport to plant: ₹{breakdown['transport_cost']:,.0f}",
                f"Execution: {duration_days} day(s) ready by {completion_date.isoformat()} ({slack_days} days slack)",
                f"Avoids statutory NGT burning fine of ₹{avoided_fine:,.0f}",
            ]
            if skipped_reasons:
                reasons.extend([f"Schedule note: {r}" for r in skipped_reasons[:2]])

            opt = Option(
                option_id=f"OPT_EXSITU_{baler.machine_id}_{buyer.buyer_id}",
                option_type=OptionType.EX_SITU,
                category="EX_SITU_BALING",
                target_id=f"{baler.machine_id}+{buyer.buyer_id}",
                target_name=f"{baler.owner_name} -> {buyer.name}",
                village=f"{baler.village} -> {buyer.name}",
                distance_km=round(baler_dist + buyer_dist, 2),
                net_cost=net_cost,
                cost_breakdown=breakdown,
                earliest_date=start_date,
                completion_date=completion_date,
                slack_days=slack_days,
                score=0.0,
                reasons=reasons,
                is_feasible=len(infeasible_reasons) == 0,
                infeasible_reasons=infeasible_reasons,
                metadata={
                    "baler_id": baler.machine_id,
                    "baler_phone": baler.owner_phone,
                    "buyer_id": buyer.buyer_id,
                    "buyer_phone": buyer.phone,
                    "buyer_type": str(buyer.buyer_type.value if hasattr(buyer.buyer_type, "value") else buyer.buyer_type),
                    "transport_terms": str(buyer.transport_terms.value if hasattr(buyer.transport_terms, "value") else buyer.transport_terms),
                    "baler_distance_km": baler_dist,
                    "buyer_distance_km": buyer_dist,
                },
            )

            if opt.is_feasible:
                feasible_options.append(opt)
            else:
                infeasible_options.append(opt)

    # ---------------------------------------------------------
    # 3. Multi-Criteria Scoring and Sorting
    # ---------------------------------------------------------
    ranked_feasible = score_and_rank_options(feasible_options, weights=ranking_weights)
    return RankingResult(feasible=ranked_feasible, infeasible=infeasible_options)
