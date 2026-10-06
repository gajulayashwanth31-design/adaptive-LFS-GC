"""
Unit tests for storage subsystem (Segment, BlockManager, SegmentManager).
"""

import pytest
from src.storage.segment import Segment, SegmentState
from src.storage.block_manager import BlockManager
from src.storage.segment_manager import SegmentManager


def test_segment_append_and_invalidation():
    seg = Segment(segment_id=0, total_blocks=4, block_size=4096)
    assert seg.valid_blocks == 0
    assert seg.invalid_blocks == 0
    assert seg.free_blocks == 4
    assert seg.state == SegmentState.FREE

    meta0 = seg.append_block(block_id=1, inode_number=10, file_block_offset=0)
    assert seg.valid_blocks == 1
    assert seg.free_blocks == 3
    assert seg.state == SegmentState.ACTIVE

    meta1 = seg.append_block(block_id=2, inode_number=10, file_block_offset=1)
    assert seg.valid_blocks == 2
    assert seg.free_blocks == 2

    # Invalidate block 0
    invalidated = seg.invalidate_block(0)
    assert invalidated is True
    assert seg.valid_blocks == 1
    assert seg.invalid_blocks == 1
    assert seg.valid_ratio == 0.25
    assert seg.invalid_ratio == 0.25


def test_block_manager_wa_tracking():
    bm = BlockManager(block_size=4096)
    assert bm.write_amplification == 1.0

    # Logical write of 4096 bytes
    bm.write_block(segment_id=0, offset=0, data=b"hello", is_gc_relocation=False)
    assert bm.logical_bytes_written == 5
    assert bm.physical_bytes_written == 4096

    # Relocation of 4096 bytes
    bm.write_block(segment_id=0, offset=1, data=b"hello", is_gc_relocation=True)
    assert bm.logical_bytes_written == 5
    assert bm.gc_bytes_copied == 5
    assert bm.physical_bytes_written == 8192
    assert bm.write_amplification == 8192 / 5


def test_segment_manager_allocation_and_reclaim():
    sm = SegmentManager(total_segments=4, blocks_per_segment=4, block_size=4096)
    assert sm.free_segments_count == 3  # 1 active, 3 free
    assert sm.active_segment.segment_id == 0

    # Write 4 blocks to fill active segment
    for i in range(4):
        sm.write_block(inode_number=1, file_block_offset=i, data=f"data_{i}".encode())

    assert sm.segments[0].is_full is True
    # Writing 5th block should seal segment 0 and allocate segment 1
    sm.write_block(inode_number=1, file_block_offset=4, data=b"data_4")
    assert sm.segments[0].state == SegmentState.SEALED
    assert sm.active_segment.segment_id == 1

    # Candidate eligibility
    candidates = sm.get_eligible_candidates()
    assert len(candidates) == 1
    assert candidates[0].segment_id == 0

    # Reclaim segment 0
    sm.reclaim_segment(0)
    assert sm.segments[0].state == SegmentState.FREE
    assert sm.free_segments_count == 3
