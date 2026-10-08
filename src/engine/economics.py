"""Pure deterministic agronomic and economic calculations for residue management."""

from __future__ import annotations

from src.common.constants import AgriculturalConstants
from src.common.models import Buyer, Machine, TransportTerms


def get_burning_fine(acres: float, constants: AgriculturalConstants) -> float:
    """Computes the statutory NGT fine for stubble burning based on landholding.
    
    Args:
        acres: Landholding in acres.
        constants: Agricultural constants containing statutory fine tiers.
        
    Returns:
        Fine amount in INR.
    """
    if acres < 2.0:
        return constants.burning_fine_under_2_acres
    elif acres <= 5.0:
        return constants.burning_fine_2_to_5_acres
    else:
        return constants.burning_fine_above_5_acres


def compute_in_situ_cost(
    acres: float,
    machine: Machine,
    distance_km: float,
) -> tuple[float, dict[str, float]]:
    """Calculates deterministic in-situ machinery hiring and travel costs.
    
    Args:
        acres: Land area to be processed in acres.
        machine: Selected machinery model.
        distance_km: Distance from machine base to farm in km.
        
    Returns:
        Tuple of (net_cost, breakdown_dict)
    """
    rental_cost = round(machine.rate_per_acre * acres, 2)
    travel_cost = round(machine.travel_charge_per_km * distance_km, 2)
    total_cost = round(rental_cost + travel_cost, 2)

    breakdown = {
        "acres": float(acres),
        "rate_per_acre": float(machine.rate_per_acre),
        "rental_cost": float(rental_cost),
        "distance_km": float(distance_km),
        "travel_charge_per_km": float(machine.travel_charge_per_km),
        "travel_cost": float(travel_cost),
        "gross_cost": float(total_cost),
        "net_cost": float(total_cost),
    }
    return total_cost, breakdown


def compute_ex_situ_economics(
    acres: float,
    baler: Machine,
    buyer: Buyer,
    distance_farmer_baler_km: float,
    distance_farmer_buyer_km: float,
    constants: AgriculturalConstants,
) -> tuple[float, dict[str, float], bool, str | None]:
    """Calculates ex-situ residue collection, transport, sale revenue, and incentives.
    
    Args:
        acres: Land area in acres.
        baler: Selected baler machinery.
        buyer: Selected commercial biomass buyer.
        distance_farmer_baler_km: Distance from baler CHC to farm in km.
        distance_farmer_buyer_km: Distance from farm to buyer facility in km.
        constants: Agricultural constants.
        
    Returns:
        Tuple of (net_cost, breakdown_dict, is_volume_feasible, reason_if_infeasible)
    """
    residue_tonnes = round(acres * constants.residue_tonnes_per_acre, 2)
    min_tonnes = float(buyer.min_quantity_tonnes)

    is_volume_feasible = residue_tonnes >= min_tonnes
    reason_if_infeasible = None
    if not is_volume_feasible:
        reason_if_infeasible = (
            f"Residue yield ({residue_tonnes:.1f} tonnes from {acres:.1f} acres) is below "
            f"buyer minimum procurement threshold ({min_tonnes:.1f} tonnes)."
        )

    # 1. Baler operational & transit costs
    baler_rental = round(baler.rate_per_acre * acres, 2)
    baler_travel = round(baler.travel_charge_per_km * distance_farmer_baler_km, 2)
    total_baling_cost = round(baler_rental + baler_travel, 2)

    # 2. Road transport logistics cost
    transport_terms = str(
        buyer.transport_terms.value if hasattr(buyer.transport_terms, "value") else buyer.transport_terms
    ).upper()

    if transport_terms == TransportTerms.EX_FARM.value:
        transport_cost = 0.0
    else:
        # Delivered or negotiable: Farmer pays road transport
        transport_cost = round(
            residue_tonnes * distance_farmer_buyer_km * constants.default_transport_cost_per_tonne_km,
            2,
        )

    # 3. Off-take revenue
    gross_revenue = round(residue_tonnes * buyer.price_per_tonne, 2)

    # 4. CRM Government incentive
    govt_incentive = round(acres * constants.govt_ex_situ_incentive_per_acre, 2)

    # 5. Net Cost (negative = net profit)
    total_gross_cost = round(total_baling_cost + transport_cost, 2)
    total_benefit = round(gross_revenue + govt_incentive, 2)
    net_cost = round(total_gross_cost - total_benefit, 2)

    breakdown = {
        "acres": float(acres),
        "residue_tonnes": float(residue_tonnes),
        "baler_rate_per_acre": float(baler.rate_per_acre),
        "baler_rental_cost": float(baler_rental),
        "baler_travel_cost": float(baler_travel),
        "total_baling_cost": float(total_baling_cost),
        "buyer_distance_km": float(distance_farmer_buyer_km),
        "transport_cost": float(transport_cost),
        "gross_cost": float(total_gross_cost),
        "buyer_price_per_tonne": float(buyer.price_per_tonne),
        "gross_revenue": float(gross_revenue),
        "govt_incentive": float(govt_incentive),
        "total_benefit": float(total_benefit),
        "net_cost": float(net_cost),
    }

    return net_cost, breakdown, is_volume_feasible, reason_if_infeasible
