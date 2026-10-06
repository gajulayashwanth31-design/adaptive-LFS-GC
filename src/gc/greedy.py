"""
Greedy Segment Cleaning Baseline: Selects the candidate with lowest valid ratio / highest reclaimable space.
"""

from __future__ import annotations
from typing import List, Optional
from src.storage.segment import Segment


class GreedyPolicy:
    """
    Greedy Segment Cleaner:
    Selects the segment with the lowest valid block ratio (highest invalid ratio).
    Breaks ties by maximum reclaimable invalid blocks, then oldest age.
    """

    def __init__(self):
        self.name = "Greedy"

    def select_victim(self, eligible_candidates: List[Segment]) -> Optional[Segment]:
        if not eligible_candidates:
            return None
        # Primary: lowest valid ratio
        # Secondary: highest invalid block count
        # Tertiary: oldest creation time
        return min(
            eligible_candidates,
            key=lambda s: (s.valid_ratio, -s.invalid_blocks, s.creation_time),
        )
