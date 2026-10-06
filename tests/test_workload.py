"""
Unit tests for workload monitoring, drift detection, and synthetic generators.
"""

import pytest
from src.workload.monitor import WorkloadMonitor
from src.workload.drift import DriftDetector
from src.workload.generator import WorkloadGenerator


def test_workload_monitor_statistics():
    wm = WorkloadMonitor(window_size=10)
    # Record 6 writes (sequential)
    for i in range(6):
        wm.record_op("WRITE", "/file.bin", offset=i * 4096, size=4096, invalidated_blocks=0)
    # Record 4 reads
    for i in range(4):
        wm.record_op("READ", "/file.bin", offset=0, size=4096, invalidated_blocks=0)

    feats = wm.get_features()
    assert feats["write_rate"] == 0.6
    assert feats["read_rate"] == 0.4
    assert feats["update_rate"] == 0.0
    assert feats["delete_rate"] == 0.0
    # Sequential writes were adjacent
    assert feats["sequentiality"] > 0.5


def test_drift_detector_detects_phase_change():
    dd = DriftDetector(threshold=0.25, min_window_ops=10, cooldown_ops=10)

    # Initial baseline: mostly reads
    read_feats = {
        "read_rate": 0.9,
        "write_rate": 0.1,
        "update_rate": 0.0,
        "delete_rate": 0.0,
        "sequentiality": 0.0,
        "randomness": 1.0,
        "invalidation_rate": 0.0,
    }
    drift, score, phase = dd.update(read_feats, total_ops=10)
    assert drift is False
    assert phase == 0

    # Shift to update-heavy phase
    update_feats = {
        "read_rate": 0.0,
        "write_rate": 0.2,
        "update_rate": 0.8,
        "delete_rate": 0.0,
        "sequentiality": 0.1,
        "randomness": 0.9,
        "invalidation_rate": 0.8,
    }
    drift, score, phase = dd.update(update_feats, total_ops=25)
    assert drift is True
    assert phase == 1
    assert score >= 0.25


def test_workload_generator_phases():
    wg = WorkloadGenerator(seed=123)
    ops = list(wg.workload_phase_changing(ops_per_phase=20))
    # 5 phases * 20 ops = 100 ops
    assert len(ops) == 100
    phases_seen = set(op[4] for op in ops)
    assert "SEQUENTIAL" in phases_seen
    assert "RANDOM" in phases_seen
    assert "UPDATE_HEAVY" in phases_seen
    assert "DELETE_HEAVY" in phases_seen
    assert "MIXED" in phases_seen
