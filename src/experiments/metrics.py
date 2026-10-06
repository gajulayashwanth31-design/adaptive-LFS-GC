"""
Experiment Metrics: Aggregates, analyzes, and formats research performance indicators.
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

from src.gc.collector import GCEvent


@dataclass
class BenchmarkSummary:
    policy_name: str
    total_ops: int
    elapsed_time_sec: float
    throughput_ops_sec: float
    total_physical_bytes: int
    total_logical_bytes: int
    write_amplification: float
    gc_count: int
    total_reclaimed_bytes: int
    mean_reclaimed_per_gc: float
    total_copied_bytes: int
    mean_gc_latency_ms: float
    p50_gc_latency_ms: float
    p95_gc_latency_ms: float
    p99_gc_latency_ms: float
    cumulative_regret: float
    fallback_rate: float
    exploration_rate: float
    mean_decision_overhead_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MetricsCalculator:
    """
    Computes rigorous statistical summaries from filesystem and GC telemetry.
    """

    @staticmethod
    def summarize(
        policy_name: str,
        total_ops: int,
        elapsed_sec: float,
        logical_bytes: int,
        physical_bytes: int,
        gc_events: List[GCEvent],
        cumulative_regret: float = 0.0,
        fallback_rate: float = 0.0,
        exploration_rate: float = 0.0,
        decision_overhead_list_sec: Optional[List[float]] = None,
    ) -> BenchmarkSummary:
        gc_count = len(gc_events)
        throughput = total_ops / elapsed_sec if elapsed_sec > 0 else 0.0
        wa = physical_bytes / logical_bytes if logical_bytes > 0 else 1.0

        reclaimed_list = [e.reclaimed_bytes for e in gc_events]
        total_reclaimed = sum(reclaimed_list)
        mean_reclaimed = float(np.mean(reclaimed_list)) if reclaimed_list else 0.0

        copied_list = [e.copied_bytes for e in gc_events]
        total_copied = sum(copied_list)

        latencies_ms = [e.latency_sec * 1000.0 for e in gc_events]
        if latencies_ms:
            mean_lat = float(np.mean(latencies_ms))
            p50_lat = float(np.percentile(latencies_ms, 50))
            p95_lat = float(np.percentile(latencies_ms, 95))
            p99_lat = float(np.percentile(latencies_ms, 99))
        else:
            mean_lat = p50_lat = p95_lat = p99_lat = 0.0

        overhead_ms = 0.0
        if decision_overhead_list_sec:
            overhead_ms = float(np.mean([t * 1000.0 for t in decision_overhead_list_sec]))

        return BenchmarkSummary(
            policy_name=policy_name,
            total_ops=total_ops,
            elapsed_time_sec=elapsed_sec,
            throughput_ops_sec=throughput,
            total_physical_bytes=physical_bytes,
            total_logical_bytes=logical_bytes,
            write_amplification=wa,
            gc_count=gc_count,
            total_reclaimed_bytes=total_reclaimed,
            mean_reclaimed_per_gc=mean_reclaimed,
            total_copied_bytes=total_copied,
            mean_gc_latency_ms=mean_lat,
            p50_gc_latency_ms=p50_lat,
            p95_gc_latency_ms=p95_lat,
            p99_gc_latency_ms=p99_lat,
            cumulative_regret=cumulative_regret,
            fallback_rate=fallback_rate,
            exploration_rate=exploration_rate,
            mean_decision_overhead_ms=overhead_ms,
        )
