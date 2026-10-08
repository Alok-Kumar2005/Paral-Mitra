"""Geo-spatial distance and grid computation utilities for Parali Mitra."""

from __future__ import annotations

import math


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points on Earth in kilometers.
    
    Args:
        lat1: Latitude of point 1 in degrees.
        lon1: Longitude of point 1 in degrees.
        lat2: Latitude of point 2 in degrees.
        lon2: Longitude of point 2 in degrees.
        
    Returns:
        Distance in kilometers rounded to 3 decimal places.
    """
    # Earth radius in kilometers (WGS-84 mean radius)
    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(radius_km * c, 3)


def get_grid_cell_id(lat: float, lon: float, grid_size: float = 0.1) -> str:
    """Generates a spatial grid cell identifier based on discretized lat/lon coordinates.
    
    Args:
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        grid_size: Grid spacing in degrees (default 0.1 deg ~= 11 km).
        
    Returns:
        String key representing the center of the grid cell, e.g. "30.10_75.80".
    """
    rounded_lat = round(lat / grid_size) * grid_size
    rounded_lon = round(lon / grid_size) * grid_size
    return f"{rounded_lat:.2f}_{rounded_lon:.2f}"
