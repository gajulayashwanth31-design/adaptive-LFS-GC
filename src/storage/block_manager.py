"""
Physical block storage and data buffer management for LFS.
"""

from __future__ import annotations
from typing import Dict, Tuple, Optional


class BlockManager:
    """
    Manages physical storage blocks in memory (or virtual disk image).
    Tracks physical vs logical bytes written to accurately calculate Write Amplification.
    """

    def __init__(self, block_size: int = 4096):
        self.block_size: int = block_size
        # (segment_id, offset) -> bytes (block payload)
        self._storage: Dict[Tuple[int, int], bytes] = {}
        self._next_block_id: int = 1

        # Write amplification counters
        self.logical_bytes_written: int = 0
        self.physical_bytes_written: int = 0
        self.gc_bytes_copied: int = 0

    @property
    def write_amplification(self) -> float:
        """
        Write Amplification = Total Physical Bytes Written / Total Logical Bytes Written.
        Returns 1.0 if no logical bytes have been written yet.
        """
        if self.logical_bytes_written == 0:
            return 1.0
        return self.physical_bytes_written / self.logical_bytes_written

    def allocate_block_id(self) -> int:
        bid = self._next_block_id
        self._next_block_id += 1
        return bid

    def write_block(
        self,
        segment_id: int,
        offset: int,
        data: bytes,
        is_gc_relocation: bool = False,
    ) -> None:
        """
        Writes data into the specified segment offset.
        If data is smaller than block_size, it is padded with null bytes.
        """
        if len(data) > self.block_size:
            raise ValueError(f"Block data size {len(data)} exceeds block_size {self.block_size}")

        padded_data = data.ljust(self.block_size, b"\x00")
        self._storage[(segment_id, offset)] = padded_data

        # Track physical writes
        self.physical_bytes_written += self.block_size
        if is_gc_relocation:
            self.gc_bytes_copied += len(data)
        else:
            self.logical_bytes_written += len(data)

    def read_block(self, segment_id: int, offset: int) -> bytes:
        """Reads block payload from segment at offset."""
        return self._storage.get((segment_id, offset), b"\x00" * self.block_size)

    def erase_segment_blocks(self, segment_id: int, total_blocks: int) -> None:
        """Removes all stored blocks for a segment upon reclaim."""
        for offset in range(total_blocks):
            self._storage.pop((segment_id, offset), None)
