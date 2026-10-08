"""Spatial clustering and machinery coverage gap analysis for active fire hotspots."""

from __future__ import annotations

from collections import defaultdict
from src.common.models import Hotspot, Machine
from src.engine.geo import get_grid_cell_id, haversine_distance
from src.engine.models import GridCellGap


def compute_gap(
    hotspots: list[Hotspot],
    machines: list[Machine],
    grid_size: float = 0.1,
    radius_km: float = 15.0,
) -> list[GridCellGap]:
    """Aggregates active fire hotspots into spatial grid cells and flags coverage gaps.
    
    A grid cell with active fires is flagged as a gap (is_gap=True) if there are no registered
    CRM machines available within the specified radius_km.
    
    Args:
        hotspots: List of active fire detections.
        machines: List of registered CRM machinery.
        grid_size: Grid discretization size in degrees (default 0.1 deg ~= 11 km).
        radius_km: Operational coverage radius threshold in km (default 15.0 km).
        
    Returns:
        List of GridCellGap records, prioritizing critical unserviced gap clusters first.
    """
    if not hotspots:
        return []

    # 1. Cluster hotspots into spatial grid cells
    cell_clusters: dict[str, list[Hotspot]] = defaultdict(list)
    for h in hotspots:
        cell_id = get_grid_cell_id(h.lat, h.lon, grid_size=grid_size)
        cell_clusters[cell_id].append(h)

    results: list[GridCellGap] = []

    for cell_id, cluster in cell_clusters.items():
        count = len(cluster)
        avg_lat = round(sum(h.lat for h in cluster) / count, 4)
        avg_lon = round(sum(h.lon for h in cluster) / count, 4)
        total_frp = round(sum(h.frp for h in cluster), 2)
        max_frp = round(max(h.frp for h in cluster), 2)

        if not machines:
            results.append(
                GridCellGap(
                    grid_cell=cell_id,
                    lat=avg_lat,
                    lon=avg_lon,
                    fire_count=count,
                    total_frp=total_frp,
                    max_frp=max_frp,
                    nearest_machine_id=None,
                    nearest_machine_name=None,
                    nearest_machine_distance_km=None,
                    is_gap=True,
                )
            )
            continue

        # Find closest machine to the centroid of the fire cluster
        nearest_m = None
        min_dist = float("inf")
        for m in machines:
            dist = haversine_distance(avg_lat, avg_lon, m.lat, m.lon)
            if dist < min_dist:
                min_dist = dist
                nearest_m = m

        is_gap = min_dist > radius_km
        results.append(
            GridCellGap(
                grid_cell=cell_id,
                lat=avg_lat,
                lon=avg_lon,
                fire_count=count,
                total_frp=total_frp,
                max_frp=max_frp,
                nearest_machine_id=nearest_m.machine_id if nearest_m else None,
                nearest_machine_name=nearest_m.owner_name if nearest_m else None,
                nearest_machine_distance_km=round(min_dist, 2) if nearest_m else None,
                is_gap=is_gap,
            )
        )

    # Sort gaps first (is_gap=True), then by fire count descending, then total_frp descending
    results.sort(key=lambda g: (0 if g.is_gap else 1, -g.fire_count, -g.total_frp))
    return results
