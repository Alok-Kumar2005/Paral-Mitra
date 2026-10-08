"""Multi-criteria scoring and normalization engine for residue management options."""

from __future__ import annotations

from src.engine.models import Option, RankingWeights


def score_and_rank_options(
    options: list[Option],
    weights: RankingWeights | None = None,
) -> list[Option]:
    """Calculates normalized multi-criteria scores and ranks feasible options.
    
    Criteria:
    1. Net Cost (weight: default 50%) - Lower is better.
    2. Time Slack (weight: default 30%) - Higher days to spare is better.
    3. Operational Distance (weight: default 20%) - Closer is better.
    
    Args:
        options: List of evaluated options.
        weights: Configurable weights.
        
    Returns:
        Sorted list of options with assigned scores (highest score first).
    """
    if not options:
        return []

    w = weights or RankingWeights()
    w_sum = w.cost_weight + w.slack_weight + w.distance_weight
    if w_sum <= 0:
        w_cost, w_slack, w_dist = 0.50, 0.30, 0.20
    else:
        w_cost = w.cost_weight / w_sum
        w_slack = w.slack_weight / w_sum
        w_dist = w.distance_weight / w_sum

    costs = [opt.net_cost for opt in options]
    slacks = [float(opt.slack_days) for opt in options]
    distances = [opt.distance_km for opt in options]

    min_cost, max_cost = min(costs), max(costs)
    min_slack, max_slack = min(slacks), max(slacks)
    min_dist, max_dist = min(distances), max(distances)

    scored_options: list[Option] = []
    for opt in options:
        # Net cost normalization (lower cost = higher score)
        if max_cost == min_cost:
            cost_norm = 1.0
        else:
            cost_norm = (max_cost - opt.net_cost) / (max_cost - min_cost)

        # Time slack normalization (more slack days = higher score)
        if max_slack == min_slack:
            slack_norm = 1.0
        else:
            slack_norm = (float(opt.slack_days) - min_slack) / (max_slack - min_slack)

        # Distance normalization (closer distance = higher score)
        if max_dist == min_dist:
            dist_norm = 1.0
        else:
            dist_norm = (max_dist - opt.distance_km) / (max_dist - min_dist)

        composite_score = round(100.0 * (w_cost * cost_norm + w_slack * slack_norm + w_dist * dist_norm), 2)
        opt_dict = opt.model_dump()
        opt_dict["score"] = composite_score
        scored_options.append(Option(**opt_dict))

    # Sort descending by score, tie-break by net_cost ascending, then slack_days descending
    scored_options.sort(key=lambda o: (-o.score, o.net_cost, -o.slack_days))
    return scored_options
