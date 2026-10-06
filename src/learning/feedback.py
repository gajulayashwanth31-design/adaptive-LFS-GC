"""
Feedback Loop: Connects GC cleaning outcomes back into the online learning pipeline.
Tracks observed rewards, prediction error, and cumulative regret.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from src.learning.online_model import OnlineUtilityModel
from src.learning.utility import UtilityModel
from src.gc.collector import GCEvent


@dataclass
class FeedbackSample:
    gc_id: int
    predicted_utility: float
    observed_utility: float
    error: float
    regret: float
    is_exploration: bool
    fallback_used: bool


class FeedbackLoop:
    """
    Closes the online learning loop:
    Measures observed performance post-GC and updates the model weights.
    """

    def __init__(
        self,
        model: OnlineUtilityModel,
        utility_calculator: Optional[UtilityModel] = None,
    ):
        self.model: OnlineUtilityModel = model
        self.utility_calculator: UtilityModel = utility_calculator or UtilityModel()

        self.samples: List[FeedbackSample] = []
        self.cumulative_regret: float = 0.0
        self.total_prediction_error: float = 0.0

    def process_gc_outcome(
        self,
        event: GCEvent,
        chosen_segment_features: Dict[str, float],
        workload_features: Dict[str, float],
        phase_id: int,
        segment_capacity: int,
        best_possible_predicted_utility: Optional[float] = None,
    ) -> FeedbackSample:
        """
        Calculates observed utility and updates online learner.
        """
        # Ground-truth observed utility
        observed_util = self.utility_calculator.compute_observed_utility(
            reclaimed_bytes=event.reclaimed_bytes,
            copied_bytes=event.copied_bytes,
            latency_sec=event.latency_sec,
            segment_capacity=segment_capacity,
        )

        event.observed_utility = observed_util

        # Online model weight update
        err = self.model.learn_one(
            segment_features=chosen_segment_features,
            workload_features=workload_features,
            target_utility=observed_util,
            phase_id=phase_id,
        )

        # Regret calculation
        pred_util = event.predicted_utility if event.predicted_utility is not None else 0.5
        best_util = best_possible_predicted_utility if best_possible_predicted_utility is not None else pred_util
        regret = max(0.0, best_util - pred_util)
        self.cumulative_regret += regret
        self.total_prediction_error += err

        sample = FeedbackSample(
            gc_id=event.gc_id,
            predicted_utility=pred_util,
            observed_utility=observed_util,
            error=err,
            regret=regret,
            is_exploration=event.is_exploration,
            fallback_used=event.fallback_used,
        )
        self.samples.append(sample)
        return sample
