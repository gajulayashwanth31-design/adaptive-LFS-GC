"""
SegmentManager: Coordinates segment allocation, tracking, free pool, and GC eligibility.
"""

from __future__ import annotations
import time
from typing import Dict, List, Optional, Set, Callable
from src.storage.segment import Segment, SegmentState, BlockMetadata
from src.storage.block_manager import BlockManager


class SegmentManager:
    """
    Manages the collection of segments comprising the LFS storage system.
    Maintains the free list, active writing segment, and candidate eligibility.
    """

    def __init__(
        self,
        total_segments: int = 32,
        blocks_per_segment: int = 64,
        block_size: int = 4096,
        block_manager: Optional[BlockManager] = None,
        gc_callback: Optional[Callable[[], None]] = None,
    ):
        self.total_segments: int = total_segments
        self.blocks_per_segment: int = blocks_per_segment
        self.block_size: int = block_size
        self.total_capacity_bytes: int = total_segments * blocks_per_segment * block_size
        self.total_system_blocks: int = total_segments * blocks_per_segment
        self.gc_callback = gc_callback

        self.block_manager: BlockManager = block_manager or BlockManager(block_size=block_size)

        # Segments index: segment_id -> Segment
        self.segments: Dict[int, Segment] = {}
        for sid in range(total_segments):
            self.segments[sid] = Segment(
                segment_id=sid,
                total_blocks=blocks_per_segment,
                block_size=block_size,
            )

        # Free segment pool (list of segment IDs)
        self.free_segment_ids: List[int] = list(range(total_segments))

        # Active segment for writing appends
        self.active_segment: Optional[Segment] = None
        self._allocate_new_active_segment()

    @property
    def free_segments_count(self) -> int:
        return len(self.free_segment_ids)

    @property
    def free_space_ratio(self) -> float:
        """
        Calculates the ratio of immediately writable free space in the system:
        (free_segments * blocks_per_seg + active_free_blocks) / total_system_blocks.
        Sealed segments with invalid blocks are dirty and must be cleaned by GC to become free.
        """
        free_blocks_in_pool = len(self.free_segment_ids) * self.blocks_per_segment
        active_free_blocks = self.active_segment.free_blocks if self.active_segment else 0
        return (free_blocks_in_pool + active_free_blocks) / self.total_system_blocks

    @property
    def dirty_space_ratio(self) -> float:
        """Ratio of space occupied by invalid/dead blocks awaiting GC reclamation."""
        sealed_invalid_blocks = sum(
            s.invalid_blocks for s in self.segments.values() if s.state == SegmentState.SEALED
        )
        return sealed_invalid_blocks / self.total_system_blocks

    def _allocate_new_active_segment(self, is_gc_relocation: bool = False) -> Segment:
        """
        Pulls a segment from the free pool and sets it as the active segment.
        Maintains a cleaning reserve of 1 segment so GC can always relocate live blocks.
        """
        # Regular user writes trigger GC when approaching the cleaning reserve
        if not is_gc_relocation and len(self.free_segment_ids) <= 1 and self.gc_callback is not None:
            self.gc_callback()

        if not self.free_segment_ids and self.gc_callback is not None:
            self.gc_callback()

        if not self.free_segment_ids:
            raise RuntimeError("Out of segments: free segment pool is exhausted and no reclaimable segments remain.")

        new_sid = self.free_segment_ids.pop(0)
        seg = self.segments[new_sid]
        seg.state = SegmentState.ACTIVE
        seg.creation_time = time.time()
        seg.last_update_time = seg.creation_time
        self.active_segment = seg
        return seg

    def ensure_active_capacity(self, is_gc_relocation: bool = False) -> Segment:
        """
        Returns an active segment with space for at least one block.
        If current active segment is full, seals it and allocates a new one.
        """
        if self.active_segment is None or self.active_segment.is_full:
            if self.active_segment is not None:
                self.active_segment.seal()
            return self._allocate_new_active_segment(is_gc_relocation=is_gc_relocation)
        return self.active_segment

    def write_block(
        self,
        inode_number: int,
        file_block_offset: int,
        data: bytes,
        is_gc_relocation: bool = False,
    ) -> BlockMetadata:
        """
        Writes a data block to the append head (active segment).
        Handles segment rolling if the active segment fills up.
        """
        seg = self.ensure_active_capacity(is_gc_relocation=is_gc_relocation)
        block_id = self.block_manager.allocate_block_id()
        offset = seg.write_pointer

        # Write to physical storage
        self.block_manager.write_block(
            segment_id=seg.segment_id,
            offset=offset,
            data=data,
            is_gc_relocation=is_gc_relocation,
        )

        # Record metadata
        meta = seg.append_block(
            block_id=block_id,
            inode_number=inode_number,
            file_block_offset=file_block_offset,
        )

        if seg.is_full:
            seg.seal()
            self.active_segment = None

        return meta

    def invalidate_block(self, segment_id: int, offset: int) -> bool:
        """Marks a block invalid when overwritten or truncated/deleted."""
        if segment_id not in self.segments:
            return False
        return self.segments[segment_id].invalidate_block(offset)

    def read_block(self, segment_id: int, offset: int) -> bytes:
        """Reads block data from physical block manager and records segment access."""
        seg = self.segments.get(segment_id)
        if seg:
            seg.record_access()
        return self.block_manager.read_block(segment_id, offset)

    def get_eligible_candidates(self) -> List[Segment]:
        """
        Deterministic Candidate Eligibility (PRD Section 12 & 36):
        - Must be in SEALED state (not ACTIVE writing head, not FREE, not CLEANING).
        - Must have at least some invalid blocks OR be sealed and cleanable.
        """
        candidates: List[Segment] = []
        for seg in self.segments.values():
            if seg.state == SegmentState.SEALED:
                # Segments with invalid blocks are prime candidates
                candidates.append(seg)
        return candidates

    def get_candidate_features(self, current_time: Optional[float] = None) -> Dict[int, Dict[str, float]]:
        """
        Extracts feature dictionaries for all eligible candidate segments.
        Returns: {segment_id: feature_dict}
        """
        eligible = self.get_eligible_candidates()
        features = {}
        for seg in eligible:
            features[seg.segment_id] = seg.get_features(current_time=current_time)
        return features

    def reclaim_segment(self, segment_id: int) -> None:
        """
        Reclaims a cleaned segment, erases its physical blocks,
        resets its state, and returns it to the free pool.
        """
        seg = self.segments.get(segment_id)
        if not seg:
            raise KeyError(f"Segment {segment_id} does not exist")

        self.block_manager.erase_segment_blocks(segment_id, seg.total_blocks)
        seg.reset_for_reuse()
        self.free_segment_ids.append(segment_id)
