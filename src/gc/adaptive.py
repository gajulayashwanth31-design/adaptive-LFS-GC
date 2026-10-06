"""
Adaptive GC: Integrates online utility prediction, workload drift awareness,
exploration/exploitation, and deterministic safety fallbacks.
"""

from __future__ import annotations
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass

from src.storage.segment import Segment
from src.storage.segment_manager import SegmentManager
from src.workload.monitor import WorkloadMonitor
from src.workload.drift import DriftDetector
from src.learning.online_model import OnlineUtilityModel
from src.learning.utility import UtilityModel
from src.learning.exploration import ExplorationPolicy
from src.learning.feedback import FeedbackLoop
from src.gc.safety import SafetyFilter
from src.gc.collector import GarbageCollector, GCEvent


@dataclass
class DecisionExplanation:
    gc_id: int
    timestamp: float
    phase_id: int
    selected_segment_id: int
    predicted_utility: float
    confidence: float
    is_exploration: bool
    fallback_used: bool
    fallback_reason: Optional[str]
    candidate_scores: Dict[int, float]
    top_factors: List[str]

    def to_formatted_string(self) -> str:
        factors = "\n".join(f"  - {f}" for f in self.top_factors)
        return (
            f"=== GC Decision #{self.gc_id} ===\n"
            f"Phase ID: {self.phase_id}\n"
            f"Victim Segment: {self.selected_segment_id}\n"
            f"Predicted Utility: {self.predicted_utility:.3f}\n"
            f"Confidence: {self.confidence:.3f}\n"
            f"Policy: {'EXPLORATION' if self.is_exploration else 'EXPLOITATION'}\n"
            f"Fallback: {self.fallback_reason if self.fallback_used else 'NOT USED'}\n"
            f"Key Factors:\n{factors}\n"
            f"=============================="
        )


class AdaptiveGCPolicy:
    """
    Workload-Adaptive Online Decision-Making Policy for LFS Garbage Collection.
    """

    def __init__(
        self,
        segment_manager: SegmentManager,
        workload_monitor: WorkloadMonitor,
        drift_detector: Optional[DriftDetector] = None,
        model: Optional[OnlineUtilityModel] = None,
        utility_model: Optional[UtilityModel] = None,
        exploration_policy: Optional[ExplorationPolicy] = None,
        safety_filter: Optional[SafetyFilter] = None,
        enable_drift_detection: bool = True,
        enable_exploration: bool = True,
        enable_safety_fallback: bool = True,
        enable_workload_features: bool = True,
    ):
        self.name = "Adaptive-GC"
        self.segment_manager: SegmentManager = segment_manager
        self.workload_monitor: WorkloadMonitor = workload_monitor
        self.drift_detector: DriftDetector = drift_detector or DriftDetector()
        self.model: OnlineUtilityModel = model or OnlineUtilityModel()
        self.utility_model: UtilityModel = utility_model or UtilityModel()
        self.exploration_policy: ExplorationPolicy = exploration_policy or ExplorationPolicy()
        self.safety_filter: SafetyFilter = safety_filter or SafetyFilter()

        # Ablation control flags
        self.enable_drift_detection = enable_drift_detection
        self.enable_exploration = enable_exploration
        self.enable_safety_fallback = enable_safety_fallback
        self.enable_workload_features = enable_workload_features

        self.feedback_loop: FeedbackLoop = FeedbackLoop(
            model=self.model,
            utility_calculator=self.utility_model,
        )

        self.explanations: List[DecisionExplanation] = []
        self.current_phase_id: int = 0

    def select_victim(
        self,
        eligible_candidates: List[Segment],
        current_op_count: int = 0,
    ) -> Tuple[Segment, DecisionExplanation, float, bool, bool, Optional[str]]:
        """
        Executes the adaptive selection pipeline:
        1. Read workload features & detect drift.
        2. Score candidates using online utility model.
        3. Apply exploration/exploitation.
        4. Apply safety filter and fallback.
        5. Build explainability record.
        Returns:
            (victim_segment, explanation, predicted_utility, is_exploration, fallback_used, fallback_reason)
        """
        if not eligible_candidates:
            raise RuntimeError("No eligible candidate segments available for selection")

        # Step 1: Workload features and drift detection
        if self.enable_workload_features:
            workload_feats = self.workload_monitor.get_features()
        else:
            # Ablation D: No workload features
            workload_feats = {
                "read_rate": 0.0, "write_rate": 0.0, "update_rate": 0.0,
                "delete_rate": 0.0, "sequentiality": 0.0, "randomness": 1.0,
                "invalidation_rate": 0.0,
            }

        if self.enable_drift_detection:
            drift_detected, score, phase_id = self.drift_detector.update(
                current_features=workload_feats,
                total_ops=current_op_count,
            )
            self.current_phase_id = phase_id
            if drift_detected and self.enable_exploration:
                self.exploration_policy.on_phase_drift()
        else:
            self.current_phase_id = 0

        # Step 2: Score all eligible candidates
        candidate_scores: Dict[int, float] = {}
        candidates_with_scores: List[Tuple[Segment, float]] = []

        for seg in eligible_candidates:
            seg_feats = seg.get_features()
            score = self.model.predict_one(
                segment_features=seg_feats,
                workload_features=workload_feats,
                phase_id=self.current_phase_id,
            )
            candidate_scores[seg.segment_id] = score
            candidates_with_scores.append((seg, score))

        # Best available utility among candidates
        best_predicted_score = max(candidate_scores.values())

        # Step 3: Exploration vs. Exploitation
        proposed_seg, is_exploration = self.exploration_policy.select_candidate(
            candidates_with_scores=candidates_with_scores,
            enable_exploration=self.enable_exploration,
        )

        proposed_score = candidate_scores[proposed_seg.segment_id]
        confidence = self.model.get_confidence()

        # Step 4: Safety filter & Deterministic Fallback
        if self.enable_safety_fallback:
            victim_seg, fallback_used, fallback_reason = self.safety_filter.validate_and_filter(
                selected_segment_id=proposed_seg.segment_id,
                confidence=confidence,
                segment_manager=self.segment_manager,
                eligible_candidates=eligible_candidates,
            )
        else:
            # Ablation C: Safety fallback disabled
            victim_seg = proposed_seg
            fallback_used = False
            fallback_reason = "FALLBACK_DISABLED"

        # Step 5: Explainability
        top_factors = []
        top_factors.append(f"Invalid ratio: {victim_seg.invalid_ratio:.2f}")
        top_factors.append(f"Valid ratio: {victim_seg.valid_ratio:.2f}")
        top_factors.append(f"Reclaimable bytes: {victim_seg.reclaimable_bytes}")
        top_factors.append(f"Age: {victim_seg.age:.1f}s")
        top_factors.append(f"Historical cleaning count: {victim_seg.cleaning_count}")

        explanation = DecisionExplanation(
            gc_id=len(self.explanations) + 1,
            timestamp=time.time(),
            phase_id=self.current_phase_id,
            selected_segment_id=victim_seg.segment_id,
            predicted_utility=proposed_score,
            confidence=confidence,
            is_exploration=is_exploration,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason if fallback_used else None,
            candidate_scores=candidate_scores,
            top_factors=top_factors,
        )
        self.explanations.append(explanation)

        return (
            victim_seg,
            explanation,
            proposed_score,
            is_exploration,
            fallback_used,
            fallback_reason if fallback_used else None,
        )

    def on_gc_completed(self, event: GCEvent, chosen_seg_features: Dict[str, float]) -> None:
        """
        Feedback handler called by GarbageCollector after segment cleaning.
        Updates model weights and records regret.
        """
        workload_feats = self.workload_monitor.get_features()
        seg_capacity = self.segment_manager.blocks_per_segment * self.segment_manager.block_size
        self.feedback_loop.process_gc_outcome(
            event=event,
            chosen_segment_features=chosen_seg_features,
            workload_features=workload_feats,
            phase_id=self.current_phase_id,
            segment_capacity=seg_capacity,
            best_possible_predicted_utility=event.predicted_utility,
        )
