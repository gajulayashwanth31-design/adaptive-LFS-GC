"""
GarbageCollector: Coordinates segment cleaning, block relocation, space reclamation,
performance measurement, and event logging.
"""

from __future__ import annotations
import time
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, asdict

from src.storage.segment import Segment, SegmentState
from src.storage.segment_manager import SegmentManager
from src.filesystem.lfs_core import LFSCore
from src.gc.trigger import GCTrigger


@dataclass
class GCEvent:
    """Records full telemetry for a single GC execution event."""
    gc_id: int
    timestamp: float
    trigger_reason: str
    victim_segment_id: int
    policy: str
    candidate_count: int
    valid_blocks_before: int
    invalid_blocks_before: int
    free_blocks_before: int
    copied_bytes: int
    reclaimed_bytes: int
    latency_sec: float
    write_amplification: float
    predicted_utility: Optional[float] = None
    confidence: Optional[float] = None
    is_exploration: bool = False
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    observed_utility: Optional[float] = None
    workload_phase: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GarbageCollector:
    """
    Central GC engine responsible for executing segment cleaning cycles.
    Relocates valid blocks to the active log and returns reclaimed segments to the free pool.
    """

    def __init__(
        self,
        lfs: LFSCore,
        trigger: Optional[GCTrigger] = None,
        on_gc_complete_callback: Optional[Callable[[GCEvent, Dict[str, float]], None]] = None,
    ):
        self.lfs: LFSCore = lfs
        self.segment_manager: SegmentManager = lfs.segment_manager
        self.trigger: GCTrigger = trigger or GCTrigger()
        self.on_gc_complete_callback = on_gc_complete_callback

        self.gc_count: int = 0
        self.total_gc_latency_sec: float = 0.0
        self.total_reclaimed_bytes: int = 0
        self.total_copied_bytes: int = 0
        self.history: List[GCEvent] = []
        self._is_cleaning: bool = False

    def clean_segment(
        self,
        victim: Segment,
        policy_name: str,
        trigger_reason: str = "CAPACITY_WATERMARK",
        predicted_utility: Optional[float] = None,
        confidence: Optional[float] = None,
        is_exploration: bool = False,
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
        workload_phase: Optional[str] = None,
    ) -> GCEvent:
        """
        Executes cleaning on a chosen victim segment:
        1. Relocates all live blocks to active segment.
        2. Reclaims victim segment back into free pool.
        3. Records detailed metrics and triggers feedback callback.
        """
        if self._is_cleaning:
            return None
        self._is_cleaning = True

        try:
            start_time = time.perf_counter()
            self.gc_count += 1
            gc_id = self.gc_count

            victim.state = SegmentState.CLEANING
            candidate_count = len(self.segment_manager.get_eligible_candidates()) + 1
            valid_before = victim.valid_blocks
            invalid_before = victim.invalid_blocks
            free_before = victim.free_blocks

            # Relocate live blocks
            valid_offsets = list(victim.valid_offsets)
            bytes_copied = 0

            for off in valid_offsets:
                meta = victim.blocks.get(off)
                if meta and meta.is_valid:
                    success = self.lfs.relocate_valid_block(
                        inode_number=meta.inode_number,
                        file_block_offset=meta.file_block_offset,
                        old_segment_id=victim.segment_id,
                        old_offset=off,
                    )
                    if success:
                        bytes_copied += self.segment_manager.block_size

            # Bytes reclaimed = space freed from invalid + unused blocks
            bytes_reclaimed = (invalid_before + free_before) * self.segment_manager.block_size

            # Reclaim segment
            victim_id = victim.segment_id
            self.segment_manager.reclaim_segment(victim_id)

            latency = time.perf_counter() - start_time
            self.total_gc_latency_sec += latency
            self.total_reclaimed_bytes += bytes_reclaimed
            self.total_copied_bytes += bytes_copied

            # Compute observed utility (PRD Section 15)
            # Utility = ReclaimedBytes - 0.5 * CopiedBytes - 0.2 * Latency (normalized or absolute)
            observed_utility = (
                float(bytes_reclaimed)
                - 0.5 * float(bytes_copied)
                - 1000.0 * latency
            )

            event = GCEvent(
                gc_id=gc_id,
                timestamp=time.time(),
                trigger_reason=trigger_reason,
                victim_segment_id=victim_id,
                policy=policy_name,
                candidate_count=candidate_count,
                valid_blocks_before=valid_before,
                invalid_blocks_before=invalid_before,
                free_blocks_before=free_before,
                copied_bytes=bytes_copied,
                reclaimed_bytes=bytes_reclaimed,
                latency_sec=latency,
                write_amplification=self.segment_manager.block_manager.write_amplification,
                predicted_utility=predicted_utility,
                confidence=confidence,
                is_exploration=is_exploration,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
                observed_utility=observed_utility,
                workload_phase=workload_phase,
            )

            self.history.append(event)

            # Notify feedback loop
            if self.on_gc_complete_callback:
                candidate_features = victim.get_features()
                self.on_gc_complete_callback(event, candidate_features)

            return event
        finally:
            self._is_cleaning = False
