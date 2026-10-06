"""
Safety Filter & Deterministic Fallback Hierarchy for GC.
Separates machine learning decisions from filesystem correctness.
"""

from __future__ import annotations
from typing import List, Optional, Tuple, Dict, Any
from src.storage.segment import Segment, SegmentState
from src.storage.segment_manager import SegmentManager


class SafetyFilter:
    """
    Enforces filesystem correctness and safety invariants on candidate selections.
    Provides deterministic fallback when learning predictions are invalid or uncertain.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.60,
        fallback_policy: str = "greedy",
    ):
        self.confidence_threshold: float = confidence_threshold
        self.fallback_policy: str = fallback_policy.lower()
        self.total_decisions: int = 0
        self.fallback_count: int = 0

    @property
    def fallback_rate(self) -> float:
        if self.total_decisions == 0:
            return 0.0
        return self.fallback_count / self.total_decisions

    def select_fallback_victim(
        self,
        eligible_candidates: List[Segment],
        policy: Optional[str] = None,
    ) -> Optional[Segment]:
        """
        Deterministic fallback selector:
        - greedy: lowest valid ratio
        - fifo: oldest creation time
        """
        if not eligible_candidates:
            return None

        chosen_policy = (policy or self.fallback_policy).lower()
        if chosen_policy == "fifo":
            return min(eligible_candidates, key=lambda s: s.creation_time)
        else:
            # Default to Greedy
            return min(eligible_candidates, key=lambda s: (s.valid_ratio, -s.invalid_blocks))

    def validate_and_filter(
        self,
        selected_segment_id: Optional[int],
        confidence: float,
        segment_manager: SegmentManager,
        eligible_candidates: List[Segment],
    ) -> Tuple[Segment, bool, str]:
        """
        Validates the proposed victim segment against safety constraints.
        Returns: (final_victim_segment, fallback_used: bool, reason: str)
        """
        self.total_decisions += 1

        if not eligible_candidates:
            raise RuntimeError("Cannot execute GC: no eligible candidate segments available.")

        candidate_ids = {s.segment_id: s for s in eligible_candidates}

        # Check 1: Did model return a null or non-existent segment ID?
        if selected_segment_id is None or selected_segment_id not in candidate_ids:
            self.fallback_count += 1
            victim = self.select_fallback_victim(eligible_candidates)
            return victim, True, "FALLBACK_INVALID_CANDIDATE_ID"

        candidate = candidate_ids[selected_segment_id]

        # Check 2: Segment state invariant (must be SEALED, never ACTIVE or FREE)
        if candidate.state != SegmentState.SEALED:
            self.fallback_count += 1
            victim = self.select_fallback_victim(eligible_candidates)
            return victim, True, f"FALLBACK_INVALID_STATE_{candidate.state.value}"

        # Check 3: Confidence threshold
        if confidence < self.confidence_threshold:
            self.fallback_count += 1
            victim = self.select_fallback_victim(eligible_candidates)
            return victim, True, f"FALLBACK_LOW_CONFIDENCE_{confidence:.2f}"

        # Decision is safe and confident
        return candidate, False, "ACCEPTED_ADAPTIVE_DECISION"
