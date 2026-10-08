"""Comprehensive unit and integration test suite for Parali Mitra engine."""

from __future__ import annotations

from datetime import date
import pytest

from src.common.constants import AgriculturalConstants, get_constants
from src.common.models import (
    Buyer,
    BuyerType,
    FarmerSession,
    Hotspot,
    Machine,
    MachineType,
    OptionType,
    TransportTerms,
)
from src.engine import (
    DailyWeather,
    FarmerProfile,
    RankingResult,
    RankingWeights,
    compute_gap,
    rank_options,
)


@pytest.fixture
def constants() -> AgriculturalConstants:
    """Fixture to load standard agronomic constants from seed CSV."""
    return get_constants()


# =============================================================================
# SCENARIO 1: Hand-Verified In-Situ Super Seeder Arithmetic
# =============================================================================
def test_scenario_1_hand_verified_insitu_super_seeder(constants: AgriculturalConstants) -> None:
    """Hand-verified in-situ calculation for a 5-acre farm in Ludhiana.
    
    ARITHMETIC VERIFICATION:
    -------------------------------------------------------------------------
    Farmer Location: (30.8200, 75.8900) - Kaind, Ludhiana
    Acreage: 5.0 acres
    Sowing Deadline: 2026-10-25
    Today: 2026-10-10
    
    Machine: MCH_SS_01 (Super Seeder)
      Base Location: (30.8214, 75.8942)
      Rate per acre: ₹2,200.00
      Travel charge per km: ₹300.00
      Service radius: 15.0 km
      Available from: 2026-10-10
      Blocked dates: []
      
    1. Distance Calculation:
       lat1=30.8200, lon1=75.8900 to lat2=30.8214, lon2=75.8942
       delta_lat = 0.0014 deg (~0.155 km)
       delta_lon = 0.0042 deg (~0.401 km)
       haversine_distance ≈ 0.430 km
       
    2. Cost Calculation:
       rental_cost = 5.0 acres * ₹2,200.00/acre = ₹11,000.00
       travel_cost = 0.430 km * ₹300.00/km = ₹129.00
       net_cost = rental_cost + travel_cost = ₹11,129.00
       
    3. Operational Duration & Scheduling:
       Throughput (Super Seeder) = 1.0 acre/hour (from constants.csv)
       Daily field working capacity = 1.0 acre/hr * 8 hrs/day = 8.0 acres/day
       duration_days = ceil(5.0 / 8.0) = 1 day
       Start date: 2026-10-10
       Completion date: 2026-10-10
       
    4. Feasibility & Buffer:
       Buffer required: 2 days
       slack_days = 2026-10-25 - 2026-10-10 = 15 days
       Is feasible: 15 >= 2 (True) and distance 0.430 <= 15.0 km (True)
       
    5. Fine Avoided:
       5.0 acres falls in 2 to 5 acres tier -> Statutory Fine = ₹5,000.00
    -------------------------------------------------------------------------
    """
    farmer = FarmerProfile(
        acres=5.0,
        lat=30.8200,
        lon=75.8900,
        sowing_deadline=date(2026, 10, 25),
        village_text="Kaind, Ludhiana",
    )

    machine = Machine(
        machine_id="MCH_SS_01",
        owner_name="Dev Machinery CHC",
        owner_phone="+919876902425",
        machine_type=MachineType.SUPER_SEEDER,
        village="Village Kaind",
        district="Ludhiana",
        lat=30.8214,
        lon=75.8942,
        rate_per_acre=2200.0,
        travel_charge_per_km=300.0,
        service_radius_km=15.0,
        available_from=date(2026, 10, 10),
        blocked_dates=[],
    )

    result = rank_options(
        farmer=farmer,
        machines=[machine],
        buyers=[],
        constants=constants,
        weather=[],
        today=date(2026, 10, 10),
        completion_buffer_days=2,
    )

    assert len(result.feasible) == 1
    assert len(result.infeasible) == 0

    opt = result.feasible[0]
    assert opt.option_id == "OPT_INSITU_MCH_SS_01"
    assert opt.option_type == OptionType.IN_SITU
    assert opt.category == "SUPER_SEEDER"
    assert opt.distance_km == pytest.approx(0.43, abs=0.01)
    assert opt.net_cost == pytest.approx(11129.00, abs=1.0)
    assert opt.cost_breakdown["rental_cost"] == 11000.0
    assert opt.cost_breakdown["travel_cost"] == pytest.approx(129.00, abs=1.0)
    assert opt.cost_breakdown["avoided_burning_fine"] == 5000.0
    assert opt.earliest_date == date(2026, 10, 10)
    assert opt.completion_date == date(2026, 10, 10)
    assert opt.slack_days == 15
    assert opt.score == 100.0


# =============================================================================
# SCENARIO 2: Hand-Verified Ex-Situ Baling + Buyer Commercial Sale Arithmetic
# =============================================================================
def test_scenario_2_hand_verified_exsitu_commercial_sale(constants: AgriculturalConstants) -> None:
    """Hand-verified ex-situ calculation with commercial off-take and profit.
    
    ARITHMETIC VERIFICATION:
    -------------------------------------------------------------------------
    Farmer Location: (29.9300, 75.8300) - Sangrur, Punjab
    Acreage: 10.0 acres
    Sowing Deadline: 2026-10-28
    Today: 2026-10-12
    
    1. Straw Biomass Yield:
       residue_tonnes_per_acre = 2.8 tonnes/acre (constants.csv)
       total_biomass = 10.0 acres * 2.8 tonnes/acre = 28.0 metric tonnes
       
    2. Baler Machinery: MCH_BALER_01
       Base Location: (29.9320, 75.8280) -> Distance ≈ 0.293 km
       Baler rate: ₹1,800.00/acre
       Travel rate: ₹250.00/km
       baler_rental = 10.0 * ₹1,800.00 = ₹18,000.00
       baler_travel = 0.293 km * ₹250.00/km = ₹73.25
       total_baling_cost = ₹18,073.25
       
    3. Commercial Off-take: BYR_CBG_01 (Verbio India Bio-CBG Plant)
       Facility Location: (29.9320, 75.8280) -> Distance ≈ 0.293 km
       Off-take Price: ₹2,350.00 / tonne
       Min Quantity: 25.0 tonnes -> 28.0 tonnes >= 25.0 tonnes (PASSED)
       Transport Terms: EX_FARM -> Farmer transport cost = ₹0.00
       gross_revenue = 28.0 tonnes * ₹2,350.00/tonne = ₹65,800.00
       
    4. Government CRM Scheme Incentive:
       govt_ex_situ_incentive_per_acre = ₹1,000.00/acre (constants.csv)
       govt_subsidy = 10.0 acres * ₹1,000.00/acre = ₹10,000.00
       
    5. Net Economics (Profit for Farmer):
       total_gross_cost = total_baling_cost + transport = ₹18,073.25
       total_benefit = gross_revenue + govt_subsidy = ₹65,800.00 + ₹10,000.00 = ₹75,800.00
       net_cost = total_gross_cost - total_benefit = ₹18,073.25 - ₹75,800.00 = -₹57,726.75
       (Negative net cost represents ₹57,726.75 direct profit to the farmer!)
       
    6. Scheduling & Throughput:
       Baling speed = 1.2 acres/hour (constants.csv)
       Daily capacity = 1.2 * 8.0 = 9.6 acres/day
       duration_days = ceil(10.0 / 9.6) = 2 days
       Start: 2026-10-12, Completion: 2026-10-13
       slack_days = 2026-10-28 - 2026-10-13 = 15 days
       
    7. Statutory Fine Avoided:
       10.0 acres > 5.0 acres -> Statutory Fine = ₹15,000.00
    -------------------------------------------------------------------------
    """
    farmer = FarmerProfile(
        acres=10.0,
        lat=29.9300,
        lon=75.8300,
        sowing_deadline=date(2026, 10, 28),
    )

    baler = Machine(
        machine_id="MCH_BALER_01",
        owner_name="Gurbaz Farm Machinery",
        owner_phone="+919465733000",
        machine_type=MachineType.BALER,
        village="Village Amampura",
        district="Sangrur",
        lat=29.9320,
        lon=75.8280,
        rate_per_acre=1800.0,
        travel_charge_per_km=250.0,
        service_radius_km=20.0,
        available_from=date(2026, 10, 12),
        blocked_dates=[],
    )

    buyer = Buyer(
        buyer_id="BYR_CBG_01",
        name="Verbio India Bio-CBG Plant",
        buyer_type=BuyerType.CBG_PLANT,
        lat=29.9320,
        lon=75.8280,
        price_per_tonne=2350.0,
        min_quantity_tonnes=25.0,
        transport_terms=TransportTerms.EX_FARM,
        phone="+911676292000",
    )

    result = rank_options(
        farmer=farmer,
        machines=[baler],
        buyers=[buyer],
        constants=constants,
        weather=[],
        today=date(2026, 10, 12),
        completion_buffer_days=2,
    )

    assert len(result.feasible) == 1
    opt = result.feasible[0]
    assert opt.option_type == OptionType.EX_SITU
    assert opt.category == "EX_SITU_BALING"
    assert opt.net_cost == pytest.approx(-57726.75, abs=1.0)
    assert opt.cost_breakdown["gross_revenue"] == 65800.0
    assert opt.cost_breakdown["govt_incentive"] == 10000.0
    assert opt.cost_breakdown["transport_cost"] == 0.0
    assert opt.cost_breakdown["avoided_burning_fine"] == 15000.0
    assert opt.completion_date == date(2026, 10, 13)
    assert opt.slack_days == 15


# =============================================================================
# CASE 3: No Machines in Range (Radius constraint exceeded)
# =============================================================================
def test_case_no_machines_in_range(constants: AgriculturalConstants) -> None:
    """Machines located farther than their service radius must be marked infeasible."""
    farmer = FarmerProfile(
        acres=4.0,
        lat=30.0000,
        lon=75.0000,
        sowing_deadline=date(2026, 10, 25),
    )

    # Machine 80 km away with service radius 15 km
    far_machine = Machine(
        machine_id="MCH_FAR_01",
        owner_name="Far Away CHC",
        owner_phone="+919999999999",
        machine_type=MachineType.SUPER_SEEDER,
        village="Distant Village",
        district="Bathinda",
        lat=30.7000,
        lon=75.0000,  # ~77.8 km away
        rate_per_acre=2000.0,
        travel_charge_per_km=200.0,
        service_radius_km=15.0,
        available_from=date(2026, 10, 10),
    )

    result = rank_options(
        farmer=farmer,
        machines=[far_machine],
        buyers=[],
        constants=constants,
        weather=[],
        today=date(2026, 10, 10),
    )

    assert len(result.feasible) == 0
    assert len(result.infeasible) == 1
    assert result.infeasible[0].is_feasible is False
    assert any("exceeds" in r.lower() for r in result.infeasible[0].infeasible_reasons)


# =============================================================================
# CASE 4: Sowing Deadline Too Close / Expired Buffer
# =============================================================================
def test_case_sowing_deadline_buffer_violation(constants: AgriculturalConstants) -> None:
    """When work completion cannot meet the required buffer before sowing deadline."""
    today = date(2026, 10, 10)
    # Deadline is only 1 day away (2026-10-11), but 2-day buffer required
    tight_deadline = date(2026, 10, 11)

    farmer = FarmerProfile(
        acres=5.0,
        lat=30.8200,
        lon=75.8900,
        sowing_deadline=tight_deadline,
    )

    machine = Machine(
        machine_id="MCH_01",
        owner_name="Local CHC",
        owner_phone="+919876543210",
        machine_type=MachineType.HAPPY_SEEDER,
        village="Local Village",
        district="Ludhiana",
        lat=30.8200,
        lon=75.8900,
        rate_per_acre=2000.0,
        travel_charge_per_km=100.0,
        service_radius_km=20.0,
        available_from=today,
    )

    result = rank_options(
        farmer=farmer,
        machines=[machine],
        buyers=[],
        constants=constants,
        weather=[],
        today=today,
        completion_buffer_days=2,
    )

    # Work finishes on 2026-10-10 -> slack_days = 11 - 10 = 1 day (< 2 buffer days)
    assert len(result.feasible) == 0
    assert len(result.infeasible) == 1
    assert any("buffer" in r.lower() for r in result.infeasible[0].infeasible_reasons)


# =============================================================================
# CASE 5: Weather Rain Forecast Blocks Working Days
# =============================================================================
def test_case_rain_blocking_days_and_shifting_schedule(constants: AgriculturalConstants) -> None:
    """Heavy rain forecast on scheduled days forces simulator to skip and advance dates."""
    today = date(2026, 10, 10)
    farmer = FarmerProfile(
        acres=5.0,
        lat=30.8200,
        lon=75.8900,
        sowing_deadline=date(2026, 10, 20),
    )

    machine = Machine(
        machine_id="MCH_01",
        owner_name="Local CHC",
        owner_phone="+919876543210",
        machine_type=MachineType.SUPER_SEEDER,
        village="Local Village",
        district="Ludhiana",
        lat=30.8200,
        lon=75.8900,
        rate_per_acre=2200.0,
        travel_charge_per_km=100.0,
        service_radius_km=20.0,
        available_from=today,
    )

    # Forecast: Rain on Oct 10 (15.0mm) and Oct 11 (8.0mm), Clear on Oct 12
    weather = [
        DailyWeather(date=date(2026, 10, 10), precipitation_mm=15.0, precipitation_probability_pct=90.0),
        DailyWeather(date=date(2026, 10, 11), precipitation_mm=8.0, precipitation_probability_pct=80.0),
        DailyWeather(date=date(2026, 10, 12), precipitation_mm=0.0, precipitation_probability_pct=10.0),
    ]

    result = rank_options(
        farmer=farmer,
        machines=[machine],
        buyers=[],
        constants=constants,
        weather=weather,
        today=today,
        rain_threshold_mm=2.5,
    )

    assert len(result.feasible) == 1
    opt = result.feasible[0]
    # Work should skip Oct 10 and 11, commencing and finishing on Oct 12
    assert opt.earliest_date == date(2026, 10, 12)
    assert opt.completion_date == date(2026, 10, 12)
    assert opt.slack_days == (date(2026, 10, 20) - date(2026, 10, 12)).days


# =============================================================================
# CASE 6: Buyer Minimum Quantity Threshold Not Met
# =============================================================================
def test_case_buyer_minimum_quantity_not_met(constants: AgriculturalConstants) -> None:
    """When farmer straw biomass is below buyer's procurement gate threshold."""
    # 2.0 acres generates 2.0 * 2.8 = 5.6 tonnes
    farmer = FarmerProfile(
        acres=2.0,
        lat=30.0000,
        lon=76.0000,
        sowing_deadline=date(2026, 10, 30),
    )

    baler = Machine(
        machine_id="MCH_BALER_01",
        owner_name="Local Baler",
        owner_phone="+919876543210",
        machine_type=MachineType.BALER,
        village="Village A",
        district="Patiala",
        lat=30.0000,
        lon=76.0000,
        rate_per_acre=1700.0,
        travel_charge_per_km=200.0,
        service_radius_km=20.0,
        available_from=date(2026, 10, 10),
    )

    # Buyer requires minimum 50.0 tonnes
    large_buyer = Buyer(
        buyer_id="BYR_LARGE",
        name="Large Power Plant",
        buyer_type=BuyerType.BIOMASS_POWER,
        lat=30.0100,
        lon=76.0100,
        price_per_tonne=2400.0,
        min_quantity_tonnes=50.0,
        transport_terms=TransportTerms.DELIVERED,
        phone="+911632245100",
    )

    result = rank_options(
        farmer=farmer,
        machines=[baler],
        buyers=[large_buyer],
        constants=constants,
        weather=[],
        today=date(2026, 10, 10),
    )

    assert len(result.feasible) == 0
    assert len(result.infeasible) == 1
    assert any("minimum procurement threshold" in r.lower() for r in result.infeasible[0].infeasible_reasons)


# =============================================================================
# CASE 7: Empty Inputs Handling
# =============================================================================
def test_case_empty_inputs_graceful_handling(constants: AgriculturalConstants) -> None:
    """Empty machine and buyer lists must safely return empty RankingResult without exceptions."""
    farmer = FarmerProfile(
        acres=5.0,
        lat=30.0000,
        lon=76.0000,
        sowing_deadline=date(2026, 10, 25),
    )

    result = rank_options(
        farmer=farmer,
        machines=[],
        buyers=[],
        constants=constants,
        weather=[],
        today=date(2026, 10, 10),
    )

    assert isinstance(result, RankingResult)
    assert len(result.feasible) == 0
    assert len(result.infeasible) == 0
    assert result.best_option is None
    assert len(result) == 0


# =============================================================================
# CASE 8: Multi-Machine Comparison and Multi-Criteria Ranking Order
# =============================================================================
def test_case_multi_machine_comparison_and_ranking(constants: AgriculturalConstants) -> None:
    """Verifies that closer, cheaper, and faster machines achieve superior composite scores."""
    farmer = FarmerProfile(
        acres=5.0,
        lat=30.0000,
        lon=75.0000,
        sowing_deadline=date(2026, 10, 25),
    )
    today = date(2026, 10, 10)

    # Machine 1: Close, cheap (Expected Winner)
    m1 = Machine(
        machine_id="MCH_CHEAP",
        owner_name="Local Cheap CHC",
        owner_phone="+919876543210",
        machine_type=MachineType.SUPER_SEEDER,
        village="Nearby Village",
        district="Bathinda",
        lat=30.0010,
        lon=75.0010,  # ~0.15 km
        rate_per_acre=1800.0,
        travel_charge_per_km=150.0,
        service_radius_km=15.0,
        available_from=today,
    )

    # Machine 2: Far, expensive
    m2 = Machine(
        machine_id="MCH_EXPENSIVE",
        owner_name="Distant Expensive CHC",
        owner_phone="+919876543211",
        machine_type=MachineType.SUPER_SEEDER,
        village="Distant Village",
        district="Bathinda",
        lat=30.0800,
        lon=75.0800,  # ~11.8 km
        rate_per_acre=2400.0,
        travel_charge_per_km=300.0,
        service_radius_km=20.0,
        available_from=today,
    )

    result = rank_options(
        farmer=farmer,
        machines=[m1, m2],
        buyers=[],
        constants=constants,
        weather=[],
        today=today,
    )

    assert len(result.feasible) == 2
    # Machine 1 should be ranked #1 with score 100.0
    assert result.feasible[0].target_id == "MCH_CHEAP"
    assert result.feasible[0].score == 100.0
    assert result.feasible[1].target_id == "MCH_EXPENSIVE"
    assert result.feasible[1].score < result.feasible[0].score


# =============================================================================
# CASE 9: NASA FIRMS Hotspot Machinery Coverage Gap Analysis
# =============================================================================
def test_case_hotspot_gap_computation() -> None:
    """Verifies spatial clustering of fire hotspots and detection of unserviced coverage gaps."""
    # Cluster 1 in Ludhiana (30.82, 75.89)
    # Cluster 2 in remote desert/field area (29.10, 74.20)
    hotspots = [
        Hotspot(grid_cell="30.80_75.90", lat=30.8210, lon=75.8910, acq_date=date(2026, 10, 10), frp=45.5, confidence="high"),
        Hotspot(grid_cell="30.80_75.90", lat=30.8230, lon=75.8930, acq_date=date(2026, 10, 10), frp=32.0, confidence="high"),
        Hotspot(grid_cell="29.10_74.20", lat=29.1000, lon=74.2000, acq_date=date(2026, 10, 10), frp=80.0, confidence="nominal"),
    ]

    # Machine only near Ludhiana (within 5 km of Cluster 1, > 150 km from Cluster 2)
    ludhiana_machine = Machine(
        machine_id="MCH_LDH_01",
        owner_name="Ludhiana CHC",
        owner_phone="+919876543210",
        machine_type=MachineType.SUPER_SEEDER,
        village="Kaind",
        district="Ludhiana",
        lat=30.8200,
        lon=75.8900,
        rate_per_acre=2000.0,
        travel_charge_per_km=200.0,
        service_radius_km=15.0,
        available_from=date(2026, 10, 10),
    )

    gaps = compute_gap(
        hotspots=hotspots,
        machines=[ludhiana_machine],
        grid_size=0.1,
        radius_km=15.0,
    )

    assert len(gaps) == 2
    # First entry should be the unserviced gap (is_gap=True)
    unserviced = next(g for g in gaps if g.grid_cell == "29.10_74.20")
    serviced = next(g for g in gaps if g.grid_cell == "30.80_75.90")

    assert unserviced.is_gap is True
    assert unserviced.fire_count == 1
    assert unserviced.total_frp == 80.0
    assert unserviced.nearest_machine_distance_km is not None
    assert unserviced.nearest_machine_distance_km > 100.0

    assert serviced.is_gap is False
    assert serviced.fire_count == 2
    assert serviced.total_frp == 77.5
    assert serviced.nearest_machine_id == "MCH_LDH_01"
    assert serviced.nearest_machine_distance_km < 5.0


# =============================================================================
# CASE 10: Blocked Dates Simulation
# =============================================================================
def test_case_machine_blocked_dates_skipping(constants: AgriculturalConstants) -> None:
    """When a machine has pre-existing booked dates, the engine skips them."""
    today = date(2026, 10, 10)
    farmer = FarmerProfile(
        acres=5.0,
        lat=30.0000,
        lon=75.0000,
        sowing_deadline=date(2026, 10, 20),
    )

    machine = Machine(
        machine_id="MCH_BUSY",
        owner_name="Busy CHC",
        owner_phone="+919876543210",
        machine_type=MachineType.ROTAVATOR,
        village="Central Village",
        district="Bathinda",
        lat=30.0000,
        lon=75.0000,
        rate_per_acre=1500.0,
        travel_charge_per_km=150.0,
        service_radius_km=15.0,
        available_from=today,
        blocked_dates=[date(2026, 10, 10), date(2026, 10, 11)],
    )

    result = rank_options(
        farmer=farmer,
        machines=[machine],
        buyers=[],
        constants=constants,
        weather=[],
        today=today,
    )

    assert len(result.feasible) == 1
    opt = result.feasible[0]
    # Blocked on 10th and 11th -> earliest execution date is 12th
    assert opt.earliest_date == date(2026, 10, 12)
    assert opt.completion_date == date(2026, 10, 12)


# =============================================================================
# CASE 11: FarmerSession and Dict Input Flexibility
# =============================================================================
def test_case_farmer_session_and_dict_inputs(constants: AgriculturalConstants) -> None:
    """Verifies that rank_options accepts FarmerSession and plain dict structures."""
    session = FarmerSession(
        chat_id=12345678,
        language="pa",
        acres=6.0,
        lat=30.8200,
        lon=75.8900,
        sowing_deadline=date(2026, 10, 25),
    )

    machine = Machine(
        machine_id="MCH_01",
        owner_name="Test CHC",
        owner_phone="+919876543210",
        machine_type=MachineType.SUPER_SEEDER,
        village="Kaind",
        district="Ludhiana",
        lat=30.8200,
        lon=75.8900,
        rate_per_acre=2000.0,
        travel_charge_per_km=100.0,
        service_radius_km=15.0,
        available_from=date(2026, 10, 10),
    )

    # 1. Test with FarmerSession object
    res_session = rank_options(
        farmer=session,
        machines=[machine],
        buyers=[],
        constants=constants,
        weather=[],
        today=date(2026, 10, 10),
    )
    assert len(res_session.feasible) == 1

    # 2. Test with plain dictionary
    raw_dict = {
        "acres": 6.0,
        "lat": 30.8200,
        "lon": 75.8900,
        "sowing_deadline": date(2026, 10, 25),
    }
    res_dict = rank_options(
        farmer=raw_dict,
        machines=[machine],
        buyers=[],
        constants=constants,
        weather=[],
        today=date(2026, 10, 10),
    )
    assert len(res_dict.feasible) == 1


# =============================================================================
# CASE 12: Custom Ranking Weights
# =============================================================================
def test_case_custom_ranking_weights(constants: AgriculturalConstants) -> None:
    """Verifies custom weights adjust scoring preference."""
    farmer = FarmerProfile(
        acres=5.0,
        lat=30.0000,
        lon=75.0000,
        sowing_deadline=date(2026, 10, 25),
    )
    today = date(2026, 10, 10)

    # M1: Super cheap (₹1000/acre), but available later (slack = 5 days)
    m1 = Machine(
        machine_id="MCH_CHEAP_LATE",
        owner_name="Cheap Late CHC",
        owner_phone="+919876543210",
        machine_type=MachineType.SUPER_SEEDER,
        village="V1",
        district="Bathinda",
        lat=30.0000,
        lon=75.0000,
        rate_per_acre=1000.0,
        travel_charge_per_km=0.0,
        service_radius_km=15.0,
        available_from=date(2026, 10, 20),
    )

    # M2: More expensive (₹2500/acre), but available immediately (slack = 15 days)
    m2 = Machine(
        machine_id="MCH_EXP_FAST",
        owner_name="Exp Fast CHC",
        owner_phone="+919876543211",
        machine_type=MachineType.SUPER_SEEDER,
        village="V2",
        district="Bathinda",
        lat=30.0000,
        lon=75.0000,
        rate_per_acre=2500.0,
        travel_charge_per_km=0.0,
        service_radius_km=15.0,
        available_from=today,
    )

    # Weight heavily favoring time slack over cost
    slack_first_weights = RankingWeights(cost_weight=0.05, slack_weight=0.90, distance_weight=0.05)
    res_slack = rank_options(
        farmer=farmer,
        machines=[m1, m2],
        buyers=[],
        constants=constants,
        weather=[],
        today=today,
        weights=slack_first_weights,
    )
    assert res_slack.feasible[0].target_id == "MCH_EXP_FAST"

    # Weight heavily favoring cost
    cost_first_weights = RankingWeights(cost_weight=0.90, slack_weight=0.05, distance_weight=0.05)
    res_cost = rank_options(
        farmer=farmer,
        machines=[m1, m2],
        buyers=[],
        constants=constants,
        weather=[],
        today=today,
        weights=cost_first_weights,
    )
    assert res_cost.feasible[0].target_id == "MCH_CHEAP_LATE"


# =============================================================================
# CASE 13: Ex-Situ Delivered Transport Terms Calculation
# =============================================================================
def test_case_ex_situ_delivered_transport_terms(constants: AgriculturalConstants) -> None:
    """Verifies road transport charges are accurately added when buyer terms are DELIVERED."""
    farmer = FarmerProfile(
        acres=10.0,
        lat=30.0000,
        lon=76.0000,
        sowing_deadline=date(2026, 10, 25),
    )
    today = date(2026, 10, 10)

    baler = Machine(
        machine_id="MCH_BALER",
        owner_name="Baler Hub",
        owner_phone="+919876543210",
        machine_type=MachineType.BALER,
        village="Village A",
        district="Patiala",
        lat=30.0000,
        lon=76.0000,
        rate_per_acre=1600.0,
        travel_charge_per_km=0.0,
        service_radius_km=20.0,
        available_from=today,
    )

    # Plant 10.0 km away with DELIVERED terms
    # Biomass: 10 acres * 2.8 = 28 tonnes
    # Transport cost: 28 tonnes * 10 km * 8.0 INR/tonne-km = ₹2,240.00
    buyer = Buyer(
        buyer_id="BYR_DELIVERED",
        name="Delivered Bio Plant",
        buyer_type=BuyerType.CBG_PLANT,
        lat=30.0900,
        lon=76.0000,  # ~10.0 km north
        price_per_tonne=2500.0,
        min_quantity_tonnes=20.0,
        transport_terms=TransportTerms.DELIVERED,
        phone="+919876543210",
    )

    res = rank_options(
        farmer=farmer,
        machines=[baler],
        buyers=[buyer],
        constants=constants,
        weather=[],
        today=today,
    )

    assert len(res.feasible) == 1
    opt = res.feasible[0]
    assert opt.cost_breakdown["transport_cost"] > 0.0
    assert opt.cost_breakdown["gross_revenue"] == 28.0 * 2500.0

