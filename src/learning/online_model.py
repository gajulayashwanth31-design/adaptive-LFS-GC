"""
Online Machine Learning Model: Predicts candidate segment utility from combined features.
Uses River online SGD / Linear Regression with an internal pure-Python fallback.
"""

from __future__ import annotations
import math
import random
from typing import Dict, Any, Optional

try:
    from river import linear_model, preprocessing, optim
    HAS_RIVER = True
except ImportError:
    HAS_RIVER = False


class OnlineUtilityModel:
    """
    Online learning model for continuous segment utility prediction.
    Consumes segment-level features, workload features, and phase IDs.
    """

    def __init__(
        self,
        learning_rate: float = 0.05,
        l2_reg: float = 0.001,
        initial_confidence: float = 0.40,
    ):
        self.learning_rate: float = learning_rate
        self.l2_reg: float = l2_reg
        self.initial_confidence: float = initial_confidence

        self.samples_seen: int = 0
        self.smoothed_mae: float = 0.50
        self._init_model()

    def _init_model(self) -> None:
        if HAS_RIVER:
            # River pipeline: StandardScaler | LinearRegression with SGD optimizer
            self.model = preprocessing.StandardScaler() | linear_model.LinearRegression(
                optimizer=optim.SGD(lr=self.learning_rate),
                l2=self.l2_reg,
            )
        else:
            # Fallback pure-Python SGD linear regressor
            self.weights: Dict[str, float] = {}
            self.bias: float = 0.5

    def reset(self) -> None:
        """Resets model state upon strong concept drift detection."""
        self.samples_seen = 0
        self.smoothed_mae = 0.50
        self._init_model()

    def _prepare_features(
        self,
        segment_features: Dict[str, float],
        workload_features: Dict[str, float],
        phase_id: int = 0,
    ) -> Dict[str, float]:
        """Combines and normalizes input features for inference and learning."""
        return {
            "valid_ratio": segment_features.get("valid_ratio", 0.0),
            "invalid_ratio": segment_features.get("invalid_ratio", 0.0),
            "age_norm": min(1.0, segment_features.get("age", 0.0) / 100.0),
            "time_since_update_norm": min(1.0, segment_features.get("time_since_update", 0.0) / 50.0),
            "update_count_norm": min(1.0, segment_features.get("update_count", 0.0) / 20.0),
            "read_rate": workload_features.get("read_rate", 0.0),
            "write_rate": workload_features.get("write_rate", 0.0),
            "update_rate": workload_features.get("update_rate", 0.0),
            "delete_rate": workload_features.get("delete_rate", 0.0),
            "sequentiality": workload_features.get("sequentiality", 0.0),
            "invalidation_rate": workload_features.get("invalidation_rate", 0.0),
            "phase_id": float(phase_id),
        }

    def predict_one(
        self,
        segment_features: Dict[str, float],
        workload_features: Dict[str, float],
        phase_id: int = 0,
    ) -> float:
        """Predicts expected cleaning utility in [0.0, 1.0]."""
        x = self._prepare_features(segment_features, workload_features, phase_id)

        if HAS_RIVER:
            pred = self.model.predict_one(x)
            if pred is None:
                pred = 0.5
        else:
            pred = self.bias + sum(self.weights.get(k, 0.0) * v for k, v in x.items())

        # Clamp prediction to [0.0, 1.0]
        return max(0.0, min(1.0, float(pred)))

    def learn_one(
        self,
        segment_features: Dict[str, float],
        workload_features: Dict[str, float],
        target_utility: float,
        phase_id: int = 0,
    ) -> float:
        """
        Incrementally updates online model weights using observed target utility.
        Returns the absolute prediction error for this sample.
        """
        x = self._prepare_features(segment_features, workload_features, phase_id)
        predicted = self.predict_one(segment_features, workload_features, phase_id)
        error = abs(target_utility - predicted)

        # Update smoothed error and sample counter
        self.samples_seen += 1
        alpha = 0.1
        self.smoothed_mae = (1 - alpha) * self.smoothed_mae + alpha * error

        if HAS_RIVER:
            self.model.learn_one(x, target_utility)
        else:
            # Pure-Python SGD update: w <- w + lr * (y - y_hat) * x - lr * l2 * w
            residual = target_utility - predicted
            self.bias += self.learning_rate * residual
            for k, val in x.items():
                w = self.weights.get(k, 0.0)
                grad = residual * val - self.l2_reg * w
                self.weights[k] = w + self.learning_rate * grad

        return error

    def get_confidence(self) -> float:
        """
        Calculates current model confidence score in [0.0, 1.0].
        Improves with more training observations and lower smoothed MAE.
        """
        # Warmup factor: saturates towards 1.0 after ~15 samples
        warmup = 1.0 - math.exp(-self.samples_seen / 15.0)
        # Accuracy factor: higher when smoothed prediction error is small
        accuracy = max(0.0, 1.0 - (self.smoothed_mae * 1.5))
        confidence = self.initial_confidence + (1.0 - self.initial_confidence) * (warmup * accuracy)
        return max(0.0, min(1.0, confidence))
