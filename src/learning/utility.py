"""
Utility Formulation: Cost-benefit model for evaluating candidate segments.
"""

from __future__ import annotations
from typing import Dict, Any


class UtilityModel:
    """
    Computes candidate utility based on expected space reclaimed,
    block copying overhead, cleaning latency, and workload context.
    """

    def __init__(
        self,
        reclaim_weight: float = 1.0,
        copy_cost_weight: float = 0.5,
        latency_weight: float = 0.2,
    ):
        self.reclaim_weight: float = reclaim_weight
        self.copy_cost_weight: float = copy_cost_weight
        self.latency_weight: float = latency_weight

    def compute_heuristic_utility(
        self,
        segment_features: Dict[str, float],
        workload_features: Dict[str, float],
    ) -> float:
        """
        Calculates normalized heuristic utility score in [0.0, 1.0].
        Favors segments with high invalid ratio, low valid ratio, and older age,
        especially when current workload has high write/update rates.
        """
        valid_ratio = segment_features.get("valid_ratio", 1.0)
        invalid_ratio = segment_features.get("invalid_ratio", 0.0)

        # Benefit is primarily the reclaimable fraction
        reclaim_benefit = invalid_ratio

        # Cost is the fraction of live data that must be copied
        copy_cost = valid_ratio

        # Workload-dependent weighting:
        # Under update-heavy workloads, segments with recent updates are likely to become
        # further invalidated in the future, so cleaning cold segments is better.
        update_rate = workload_features.get("update_rate", 0.0)
        time_since_update = segment_features.get("time_since_update", 1.0)
        coldness_factor = min(1.0, time_since_update / 10.0)

        raw_utility = (
            self.reclaim_weight * reclaim_benefit
            - self.copy_cost_weight * copy_cost
            + (0.2 * coldness_factor if update_rate > 0.3 else 0.0)
        )

        # Normalize to roughly [0.0, 1.0]
        normalized = (raw_utility + self.copy_cost_weight) / (
            self.reclaim_weight + self.copy_cost_weight + 0.2
        )
        return max(0.0, min(1.0, normalized))

    def compute_observed_utility(
        self,
        reclaimed_bytes: int,
        copied_bytes: int,
        latency_sec: float,
        segment_capacity: int,
    ) -> float:
        """
        Calculates ground-truth observed utility after cleaning a segment.
        Normalized to [0.0, 1.0].
        """
        if segment_capacity <= 0:
            return 0.5

        norm_reclaim = reclaimed_bytes / segment_capacity
        norm_copy = copied_bytes / segment_capacity
        # Normalized latency penalty (assuming typical GC latency is < 100ms)
        norm_latency = min(1.0, latency_sec / 0.1)

        utility = (
            self.reclaim_weight * norm_reclaim
            - self.copy_cost_weight * norm_copy
            - self.latency_weight * norm_latency
        )

        # Map from [-copy_weight - latency_weight, reclaim_weight] to [0.0, 1.0]
        min_possible = -(self.copy_cost_weight + self.latency_weight)
        max_possible = self.reclaim_weight
        span = max_possible - min_possible
        if span == 0:
            return 0.5
        normalized = (utility - min_possible) / span
        return max(0.0, min(1.0, normalized))
