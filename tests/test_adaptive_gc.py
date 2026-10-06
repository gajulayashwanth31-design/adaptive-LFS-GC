"""
Unit and integration tests for AdaptiveGCPolicy and learning feedback.
"""

import pytest
from src.filesystem.lfs_core import LFSCore
from src.workload.monitor import WorkloadMonitor
from src.gc.collector import GarbageCollector
from src.gc.adaptive import AdaptiveGCPolicy


def test_adaptive_gc_decision_cycle():
    lfs = LFSCore(total_segments=6, blocks_per_segment=4, block_size=4096)
    monitor = WorkloadMonitor(window_size=100)
    adaptive_policy = AdaptiveGCPolicy(
        segment_manager=lfs.segment_manager,
        workload_monitor=monitor,
        enable_exploration=False,  # deterministic exploit for testing
    )
    gc = GarbageCollector(
        lfs=lfs,
        on_gc_complete_callback=adaptive_policy.on_gc_completed,
    )

    # Fill segments and create distinct validity profiles
    # Segment 0: 4 blocks, 3 invalidated
    for i in range(4):
        lfs.write("/f0.bin", i * 4096, b"A" * 4096)
        monitor.record_op("WRITE", "/f0.bin", i * 4096, 4096)
    for i in range(3):
        lfs.write("/f0.bin", i * 4096, b"OVERWRITE" * 100)
        monitor.record_op("UPDATE", "/f0.bin", i * 4096, 4096, invalidated_blocks=1)

    # Segment 1: 4 blocks, 0 invalidated
    for i in range(4):
        lfs.write("/f1.bin", i * 4096, b"B" * 4096)
        monitor.record_op("WRITE", "/f1.bin", i * 4096, 4096)

    candidates = lfs.segment_manager.get_eligible_candidates()
    assert len(candidates) >= 2

    # Run adaptive selection
    victim, explanation, pred_util, is_explore, fallback, reason = adaptive_policy.select_victim(
        eligible_candidates=candidates,
        current_op_count=10,
    )

    assert victim is not None
    assert explanation is not None
    assert len(adaptive_policy.explanations) == 1

    # Clean the chosen segment
    event = gc.clean_segment(
        victim=victim,
        policy_name=adaptive_policy.name,
        predicted_utility=pred_util,
        confidence=explanation.confidence,
        is_exploration=is_explore,
        fallback_used=fallback,
        fallback_reason=reason,
    )

    assert event.reclaimed_bytes > 0
    # Verify feedback was processed and sample recorded
    assert len(adaptive_policy.feedback_loop.samples) == 1
    sample = adaptive_policy.feedback_loop.samples[0]
    assert sample.observed_utility >= 0.0

    # Test explanation format output
    expl_str = explanation.to_formatted_string()
    assert "=== GC Decision #" in expl_str
    assert "Victim Segment:" in expl_str


def test_safety_fallback_on_low_confidence():
    lfs = LFSCore(total_segments=6, blocks_per_segment=4, block_size=4096)
    monitor = WorkloadMonitor(window_size=100)
    # Require 0.99 confidence so fallback triggers
    adaptive_policy = AdaptiveGCPolicy(
        segment_manager=lfs.segment_manager,
        workload_monitor=monitor,
    )
    adaptive_policy.safety_filter.confidence_threshold = 0.99

    for i in range(4):
        lfs.write("/f0.bin", i * 4096, b"A" * 4096)
    for i in range(4):
        lfs.write("/f1.bin", i * 4096, b"B" * 4096)

    candidates = lfs.segment_manager.get_eligible_candidates()
    victim, expl, score, is_exp, fallback, reason = adaptive_policy.select_victim(
        eligible_candidates=candidates,
        current_op_count=8,
    )

    assert fallback is True
    assert "FALLBACK_LOW_CONFIDENCE" in reason
    assert victim is not None
