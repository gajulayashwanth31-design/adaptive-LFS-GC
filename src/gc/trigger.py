"""
GC Trigger: Evaluates filesystem capacity and determines whether GC should fire.
Enforces hard safety watermarks that can never be disabled by learned models.
"""

from __future__ import annotations
from typing import Tuple, Optional
from src.storage.segment_manager import SegmentManager


class GCTrigger:
    """
    Evaluates whether garbage collection should be triggered.
    Combines space-based capacity watermarks with optional learned benefit scores.
    """

    def __init__(
        self,
        free_space_threshold: float = 0.20,
        hard_free_space_threshold: float = 0.05,
        min_sealed_segments: int = 1,
    ):
        self.free_space_threshold: float = free_space_threshold
        self.hard_free_space_threshold: float = hard_free_space_threshold
        self.min_sealed_segments: int = min_sealed_segments

    def should_trigger(
        self,
        segment_manager: SegmentManager,
        learned_trigger_score: Optional[float] = None,
        learned_threshold: float = 0.50,
    ) -> Tuple[bool, str]:
        """
        Determines if GC should trigger.
        Returns (should_gc: bool, reason: str).

        Hard invariants:
        1. If free space is below HARD limit -> trigger immediately (EMERGENCY_LOW_SPACE).
        2. If free space is below SOFT limit -> trigger (CAPACITY_WATERMARK).
        3. If no sealed candidate segments exist -> cannot trigger (NO_ELIGIBLE_SEGMENTS).
        4. If learned trigger is enabled and score > threshold -> trigger (LEARNED_BENEFIT).
        """
        eligible = segment_manager.get_eligible_candidates()
        if len(eligible) < self.min_sealed_segments:
            return False, "NO_ELIGIBLE_SEGMENTS"

        free_ratio = segment_manager.free_space_ratio

        # Invariant 1: Hard free space threshold override
        if free_ratio <= self.hard_free_space_threshold or segment_manager.free_segments_count == 0:
            return True, "EMERGENCY_LOW_SPACE"

        # Invariant 2: Standard capacity watermark
        if free_ratio <= self.free_space_threshold:
            return True, "CAPACITY_WATERMARK"

        # Invariant 3: Optional adaptive/learned trigger
        if learned_trigger_score is not None:
            if learned_trigger_score >= learned_threshold:
                return True, "LEARNED_PROACTIVE_TRIGGER"

        return False, "ENOUGH_FREE_SPACE"
