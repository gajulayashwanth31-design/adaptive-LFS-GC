"""
FIFO Segment Cleaning Baseline: Selects the oldest eligible segment.
"""

from __future__ import annotations
from typing import List, Optional
from src.storage.segment import Segment


class FIFOPolicy:
    """
    FIFO Segment Cleaner:
    Selects the oldest eligible segment based on creation_time.
    Deterministic, zero ML overhead.
    """

    def __init__(self):
        self.name = "FIFO"

    def select_victim(self, eligible_candidates: List[Segment]) -> Optional[Segment]:
        if not eligible_candidates:
            return None
        return min(eligible_candidates, key=lambda s: s.creation_time)
