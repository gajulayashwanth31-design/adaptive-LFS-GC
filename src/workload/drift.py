"""
Workload Drift Detector: Detects statistical phase changes in workload streams.
"""

from __future__ import annotations
import math
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class PhaseTransitionEvent:
    timestamp: float
    old_phase: int
    new_phase: int
    drift_score: float
    trigger_features: Dict[str, float]

    def to_dict(self) -> Dict:
        return asdict(self)


class DriftDetector:
    """
    Online Workload Drift Detector.
    Monitors statistical changes between the current window and baseline reference window.
    """

    FEATURE_WEIGHTS = {
        "read_rate": 1.0,
        "write_rate": 1.5,
        "update_rate": 2.0,
        "delete_rate": 1.5,
        "sequentiality": 1.5,
        "randomness": 1.5,
        "invalidation_rate": 2.0,
    }

    def __init__(
        self,
        threshold: float = 0.30,
        min_window_ops: int = 100,
        cooldown_ops: int = 200,
    ):
        self.threshold: float = threshold
        self.min_window_ops: int = min_window_ops
        self.cooldown_ops: int = cooldown_ops

        self.current_phase_id: int = 0
        self.reference_features: Optional[Dict[str, float]] = None
        self.last_transition_op: int = 0
        self.transitions: List[PhaseTransitionEvent] = []

    def update(
        self,
        current_features: Dict[str, float],
        total_ops: int,
        timestamp: Optional[float] = None,
    ) -> Tuple[bool, float, int]:
        """
        Evaluates drift given current window features.
        Returns: (drift_detected: bool, drift_score: float, phase_id: int)
        """
        now = timestamp if timestamp is not None else time.time()

        # Initialize reference features with the first observed window
        if self.reference_features is None:
            if total_ops >= self.min_window_ops:
                self.reference_features = dict(current_features)
            return False, 0.0, self.current_phase_id

        # Cooldown check: prevent rapid oscillations
        if (total_ops - self.last_transition_op) < self.cooldown_ops:
            drift_score = self.compute_distance(current_features, self.reference_features)
            return False, drift_score, self.current_phase_id

        drift_score = self.compute_distance(current_features, self.reference_features)

        if drift_score >= self.threshold:
            # Phase change detected!
            old_phase = self.current_phase_id
            self.current_phase_id += 1
            self.last_transition_op = total_ops

            event = PhaseTransitionEvent(
                timestamp=now,
                old_phase=old_phase,
                new_phase=self.current_phase_id,
                drift_score=drift_score,
                trigger_features=dict(current_features),
            )
            self.transitions.append(event)

            # Update reference baseline to current distribution
            self.reference_features = dict(current_features)
            return True, drift_score, self.current_phase_id

        return False, drift_score, self.current_phase_id

    def compute_distance(
        self,
        feat_a: Dict[str, float],
        feat_b: Dict[str, float],
    ) -> float:
        """Computes weighted Euclidean distance between normalized feature vectors."""
        total_weight = 0.0
        weighted_sq_diff = 0.0

        for key, weight in self.FEATURE_WEIGHTS.items():
            val_a = feat_a.get(key, 0.0)
            val_b = feat_b.get(key, 0.0)
            weighted_sq_diff += weight * ((val_a - val_b) ** 2)
            total_weight += weight

        if total_weight == 0.0:
            return 0.0

        return math.sqrt(weighted_sq_diff / total_weight)
