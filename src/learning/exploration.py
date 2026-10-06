"""
Exploration vs Exploitation Policy for Adaptive Segment Cleaning.
Implements epsilon-greedy and uncertainty-aware candidate exploration.
"""

from __future__ import annotations
import random
from typing import List, Tuple, Dict, Optional
from src.storage.segment import Segment


class ExplorationPolicy:
    """
    Balances exploiting high-utility segments with exploring uncertain candidates.
    Supports epsilon-greedy selection and uncertainty-bonus scoring.
    """

    def __init__(
        self,
        epsilon: float = 0.10,
        decay: float = 0.995,
        min_epsilon: float = 0.02,
        uncertainty_weight: float = 0.15,
        seed: int = 42,
    ):
        self.epsilon: float = epsilon
        self.initial_epsilon: float = epsilon
        self.decay: float = decay
        self.min_epsilon: float = min_epsilon
        self.uncertainty_weight: float = uncertainty_weight
        self.rng = random.Random(seed)

        self.total_decisions: int = 0
        self.exploration_decisions: int = 0

    @property
    def exploration_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.exploration_decisions / self.total_decisions

    def on_phase_drift(self) -> None:
        """Temporarily increases exploration rate when workload drift is detected."""
        self.epsilon = min(0.30, self.epsilon * 2.0)

    def select_candidate(
        self,
        candidates_with_scores: List[Tuple[Segment, float]],
        enable_exploration: bool = True,
    ) -> Tuple[Segment, bool]:
        """
        Selects a segment among candidates:
        - If enable_exploration is False: purely exploit highest score.
        - If exploring (probability epsilon): choose among uncertain candidates.
        - Otherwise exploit highest score.
        Returns: (chosen_segment, is_exploration: bool)
        """
        self.total_decisions += 1

        if not candidates_with_scores:
            raise ValueError("No candidates provided for selection")

        # Sort candidates descending by predicted utility score
        candidates_with_scores.sort(key=lambda item: item[1], reverse=True)

        if not enable_exploration or len(candidates_with_scores) == 1:
            return candidates_with_scores[0][0], False

        # Check epsilon exploration trigger
        if self.rng.random() < self.epsilon:
            self.exploration_decisions += 1
            # Step decay
            self.epsilon = max(self.min_epsilon, self.epsilon * self.decay)

            # Uncertainty exploration: pick candidate with lowest cleaning count
            # or from the top-k competitive set
            top_k = candidates_with_scores[: min(len(candidates_with_scores), 4)]
            # Rank top-k by least frequently cleaned (highest uncertainty)
            uncertain_choice = min(top_k, key=lambda item: item[0].cleaning_count)
            return uncertain_choice[0], True

        # Exploit: best predicted candidate
        self.epsilon = max(self.min_epsilon, self.epsilon * self.decay)
        return candidates_with_scores[0][0], False
