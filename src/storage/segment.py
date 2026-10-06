"""
Segment metadata and block validity management for Log-Structured File System (LFS).
"""

from __future__ import annotations
import time
from enum import Enum
from typing import Dict, Optional, Set, List


class SegmentState(Enum):
    FREE = "FREE"          # Available in free segment pool
    ACTIVE = "ACTIVE"      # Currently receiving appends
    SEALED = "SEALED"      # Closed for writes, eligible for GC
    CLEANING = "CLEANING"  # Currently being cleaned by GC


class BlockMetadata:
    """Metadata for an individual physical block within a segment."""
    __slots__ = (
        "block_id",
        "segment_id",
        "offset",
        "inode_number",
        "file_block_offset",
        "is_valid",
        "write_timestamp",
    )

    def __init__(
        self,
        block_id: int,
        segment_id: int,
        offset: int,
        inode_number: int,
        file_block_offset: int,
        is_valid: bool = True,
        write_timestamp: Optional[float] = None,
    ):
        self.block_id = block_id
        self.segment_id = segment_id
        self.offset = offset
        self.inode_number = inode_number
        self.file_block_offset = file_block_offset
        self.is_valid = is_valid
        self.write_timestamp = write_timestamp if write_timestamp is not None else time.time()


class Segment:
    """
    Represents a contiguous storage segment in LFS.
    Tracks validity, access patterns, age, and historical GC metrics.
    """

    def __init__(
        self,
        segment_id: int,
        total_blocks: int = 64,
        block_size: int = 4096,
        creation_time: Optional[float] = None,
    ):
        self.segment_id: int = segment_id
        self.total_blocks: int = total_blocks
        self.block_size: int = block_size
        self.segment_size: int = total_blocks * block_size

        self.state: SegmentState = SegmentState.FREE
        self.creation_time: float = creation_time if creation_time is not None else time.time()
        self.sealed_time: Optional[float] = None
        self.last_update_time: float = self.creation_time

        # Block tracking
        # offset -> BlockMetadata
        self.blocks: Dict[int, BlockMetadata] = {}
        # Set of offsets that currently contain live data
        self.valid_offsets: Set[int] = set()
        # Set of offsets that were written and subsequently invalidated
        self.invalid_offsets: Set[int] = set()

        # Activity and access counters
        self.write_pointer: int = 0  # Next block offset to write into
        self.update_count: int = 0
        self.access_count: int = 0

        # Historical GC metrics
        self.cleaning_count: int = 0
        self.last_cleaned_time: Optional[float] = None
        self.historical_cleaning_cost: float = 0.0
        self.historical_reclaimed_bytes: int = 0

    @property
    def valid_blocks(self) -> int:
        return len(self.valid_offsets)

    @property
    def invalid_blocks(self) -> int:
        return len(self.invalid_offsets)

    @property
    def free_blocks(self) -> int:
        return self.total_blocks - self.write_pointer

    @property
    def is_full(self) -> bool:
        return self.write_pointer >= self.total_blocks

    @property
    def valid_ratio(self) -> float:
        if self.total_blocks == 0:
            return 0.0
        return self.valid_blocks / self.total_blocks

    @property
    def invalid_ratio(self) -> float:
        if self.total_blocks == 0:
            return 0.0
        return self.invalid_blocks / self.total_blocks

    @property
    def age(self) -> float:
        """Elapsed time since creation in seconds."""
        return max(0.0, time.time() - self.creation_time)

    @property
    def time_since_last_update(self) -> float:
        """Elapsed time since the last write or block invalidation in seconds."""
        return max(0.0, time.time() - self.last_update_time)

    @property
    def reclaimable_bytes(self) -> int:
        """Bytes that can be reclaimed by cleaning this segment."""
        # Unwritten blocks + invalidated blocks are reclaimable
        return (self.invalid_blocks + self.free_blocks) * self.block_size

    def append_block(
        self,
        block_id: int,
        inode_number: int,
        file_block_offset: int,
        timestamp: Optional[float] = None,
    ) -> BlockMetadata:
        """
        Appends a block at the current write pointer.
        Raises ValueError if segment is full or not active.
        """
        if self.is_full:
            raise ValueError(f"Segment {self.segment_id} is full ({self.total_blocks} blocks)")
        if self.state not in (SegmentState.ACTIVE, SegmentState.FREE):
            raise ValueError(f"Segment {self.segment_id} is not writable (state: {self.state})")

        now = timestamp if timestamp is not None else time.time()
        offset = self.write_pointer
        meta = BlockMetadata(
            block_id=block_id,
            segment_id=self.segment_id,
            offset=offset,
            inode_number=inode_number,
            file_block_offset=file_block_offset,
            is_valid=True,
            write_timestamp=now,
        )

        self.blocks[offset] = meta
        self.valid_offsets.add(offset)
        self.write_pointer += 1
        self.last_update_time = now
        self.update_count += 1
        self.state = SegmentState.ACTIVE

        return meta

    def invalidate_block(self, offset: int, timestamp: Optional[float] = None) -> bool:
        """
        Marks the block at offset as invalid.
        Returns True if the block was previously valid, False otherwise.
        """
        if offset in self.valid_offsets:
            self.valid_offsets.remove(offset)
            self.invalid_offsets.add(offset)
            if offset in self.blocks:
                self.blocks[offset].is_valid = False
            now = timestamp if timestamp is not None else time.time()
            self.last_update_time = now
            self.update_count += 1
            return True
        return False

    def record_access(self) -> None:
        """Increments read access count for this segment."""
        self.access_count += 1

    def seal(self, timestamp: Optional[float] = None) -> None:
        """Transitions active segment to SEALED once full or explicitly closed."""
        self.state = SegmentState.SEALED
        self.sealed_time = timestamp if timestamp is not None else time.time()

    def reset_for_reuse(self, timestamp: Optional[float] = None) -> None:
        """Resets segment state after cleaning so it can re-enter the free pool."""
        now = timestamp if timestamp is not None else time.time()
        self.state = SegmentState.FREE
        self.creation_time = now
        self.sealed_time = None
        self.last_update_time = now
        self.blocks.clear()
        self.valid_offsets.clear()
        self.invalid_offsets.clear()
        self.write_pointer = 0
        self.update_count = 0
        self.access_count = 0
        # Historical metrics are preserved across reclaims
        self.cleaning_count += 1
        self.last_cleaned_time = now

    def get_features(self, current_time: Optional[float] = None) -> Dict[str, float]:
        """
        Returns feature vector for candidate ranking and ML utility prediction.
        """
        now = current_time if current_time is not None else time.time()
        age_sec = max(0.0, now - self.creation_time)
        time_since_update_sec = max(0.0, now - self.last_update_time)

        return {
            "segment_id": float(self.segment_id),
            "total_blocks": float(self.total_blocks),
            "valid_blocks": float(self.valid_blocks),
            "invalid_blocks": float(self.invalid_blocks),
            "free_blocks": float(self.free_blocks),
            "valid_ratio": float(self.valid_ratio),
            "invalid_ratio": float(self.invalid_ratio),
            "age": age_sec,
            "time_since_update": time_since_update_sec,
            "update_count": float(self.update_count),
            "access_count": float(self.access_count),
            "reclaimable_bytes": float(self.reclaimable_bytes),
            "cleaning_count": float(self.cleaning_count),
            "historical_cleaning_cost": float(self.historical_cleaning_cost),
            "historical_reclaimed_bytes": float(self.historical_reclaimed_bytes),
        }

    def __repr__(self) -> str:
        return (
            f"<Segment id={self.segment_id} state={self.state.value} "
            f"valid={self.valid_blocks}/{self.total_blocks} "
            f"invalid={self.invalid_blocks} "
            f"valid_ratio={self.valid_ratio:.2f}>"
        )
