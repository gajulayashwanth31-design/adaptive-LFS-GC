"""
Unit and integration tests for baseline GC policies (FIFO and Greedy).
"""

import pytest
from src.filesystem.lfs_core import LFSCore
from src.gc.fifo import FIFOPolicy
from src.gc.greedy import GreedyPolicy
from src.gc.collector import GarbageCollector


def test_fifo_victim_selection():
    lfs = LFSCore(total_segments=6, blocks_per_segment=4, block_size=4096)
    gc = GarbageCollector(lfs=lfs)
    fifo = FIFOPolicy()

    # Fill segment 0 (4 blocks)
    for i in range(4):
        lfs.write("/file0.bin", i * 4096, b"A" * 4096)
    # Fill segment 1 (4 blocks)
    for i in range(4):
        lfs.write("/file1.bin", i * 4096, b"B" * 4096)

    # Both segment 0 and 1 are sealed
    candidates = lfs.segment_manager.get_eligible_candidates()
    assert len(candidates) >= 2

    victim = fifo.select_victim(candidates)
    assert victim is not None
    assert victim.segment_id == 0  # Older segment

    # Run GC with FIFO
    event = gc.clean_segment(victim, policy_name=fifo.name)
    assert event.victim_segment_id == 0
    assert event.policy == "FIFO"
    assert lfs.segment_manager.segments[0].state.value == "FREE"

    # Verify file0 data is still completely readable
    read_data = lfs.read("/file0.bin", 0, 4096 * 4)
    assert read_data == b"A" * (4096 * 4)


def test_greedy_victim_selection():
    lfs = LFSCore(total_segments=6, blocks_per_segment=4, block_size=4096)
    gc = GarbageCollector(lfs=lfs)
    greedy = GreedyPolicy()

    # Fill segment 0 (4 blocks)
    for i in range(4):
        lfs.write("/file0.bin", i * 4096, b"A" * 4096)

    # Fill segment 1 (4 blocks)
    for i in range(4):
        lfs.write("/file1.bin", i * 4096, b"B" * 4096)

    # Invalidate 3 blocks in segment 0 by overwriting /file0.bin
    for i in range(3):
        lfs.write("/file0.bin", i * 4096, b"MODIFIED" * 100)

    candidates = lfs.segment_manager.get_eligible_candidates()
    # Segment 0 has 3 invalid blocks (valid_ratio = 1/4 = 0.25)
    # Segment 1 has 0 invalid blocks (valid_ratio = 4/4 = 1.0)
    victim = greedy.select_victim(candidates)
    assert victim is not None
    assert victim.segment_id == 0

    # Run GC
    event = gc.clean_segment(victim, policy_name=greedy.name)
    assert event.reclaimed_bytes == 3 * 4096
    assert event.copied_bytes == 1 * 4096
