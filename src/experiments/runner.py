"""
Experiment Runner: Executes comparative benchmarks and ablation studies.
"""

from __future__ import annotations
import time
from typing import Dict, List, Tuple, Optional, Any

from src.filesystem.lfs_core import LFSCore
from src.workload.monitor import WorkloadMonitor
from src.workload.drift import DriftDetector
from src.workload.generator import WorkloadGenerator
from src.gc.collector import GarbageCollector
from src.gc.fifo import FIFOPolicy
from src.gc.greedy import GreedyPolicy
from src.gc.adaptive import AdaptiveGCPolicy
from src.gc.trigger import GCTrigger
from src.experiments.metrics import MetricsCalculator, BenchmarkSummary
from src.experiments.logger import ExperimentLogger
from src.config.config_loader import load_config


class ExperimentRunner:
    """
    Coordinates end-to-end benchmark execution across policies and workloads.
    """

    def __init__(self, config_path: str = "src/config/config.yaml"):
        self.config = load_config(config_path)
        self.logger = ExperimentLogger(output_dir="results")

    def run_workload_for_policy(
        self,
        policy_type: str,
        workload_ops: List[Tuple],
        total_segments: int = 16,
        blocks_per_segment: int = 16,
        block_size: int = 4096,
        # Ablation flags
        enable_drift: bool = True,
        enable_exploration: bool = True,
        enable_safety: bool = True,
        enable_workload_features: bool = True,
    ) -> BenchmarkSummary:
        """
        Runs an operation stream against a clean LFS using the specified GC policy.
        """
        lfs = LFSCore(
            total_segments=total_segments,
            blocks_per_segment=blocks_per_segment,
            block_size=block_size,
        )
        monitor = WorkloadMonitor(window_size=self.config["workload"]["window_size"])
        trigger = GCTrigger(
            free_space_threshold=self.config["gc"]["free_space_threshold"],
            hard_free_space_threshold=self.config["gc"]["hard_free_space_threshold"],
        )

        decision_overheads: List[float] = []
        adaptive_policy: Optional[AdaptiveGCPolicy] = None
        fifo_policy: Optional[FIFOPolicy] = None
        greedy_policy: Optional[GreedyPolicy] = None

        if policy_type in ("adaptive", "drift_aware", "online_lr", "ablation"):
            adaptive_policy = AdaptiveGCPolicy(
                segment_manager=lfs.segment_manager,
                workload_monitor=monitor,
                enable_drift_detection=enable_drift,
                enable_exploration=enable_exploration,
                enable_safety_fallback=enable_safety,
                enable_workload_features=enable_workload_features,
            )
            gc = GarbageCollector(
                lfs=lfs,
                trigger=trigger,
                on_gc_complete_callback=adaptive_policy.on_gc_completed,
            )
        elif policy_type == "fifo":
            fifo_policy = FIFOPolicy()
            gc = GarbageCollector(lfs=lfs, trigger=trigger)
        elif policy_type == "greedy":
            greedy_policy = GreedyPolicy()
            gc = GarbageCollector(lfs=lfs, trigger=trigger)
        else:
            raise ValueError(f"Unknown policy type: {policy_type}")

        start_time = time.perf_counter()
        op_count = 0
        current_phase_label = "DEFAULT"

        def do_gc(trigger_reason: str = "CAPACITY_WATERMARK") -> bool:
            nonlocal op_count, current_phase_label
            candidates = lfs.segment_manager.get_eligible_candidates()
            if not candidates:
                return False

            d_start = time.perf_counter()
            if adaptive_policy is not None:
                victim, expl, pred_util, is_exp, fb, fb_reason = adaptive_policy.select_victim(
                    eligible_candidates=candidates,
                    current_op_count=op_count,
                )
                decision_overheads.append(time.perf_counter() - d_start)
                ev = gc.clean_segment(
                    victim=victim,
                    policy_name=f"{policy_type.upper()}",
                    trigger_reason=trigger_reason,
                    predicted_utility=pred_util,
                    confidence=expl.confidence,
                    is_exploration=is_exp,
                    fallback_used=fb,
                    fallback_reason=fb_reason,
                    workload_phase=current_phase_label,
                )
                return ev is not None
            elif fifo_policy is not None:
                victim = fifo_policy.select_victim(candidates)
                decision_overheads.append(time.perf_counter() - d_start)
                if victim:
                    ev = gc.clean_segment(
                        victim=victim,
                        policy_name="FIFO",
                        trigger_reason=trigger_reason,
                        workload_phase=current_phase_label,
                    )
                    return ev is not None
            elif greedy_policy is not None:
                victim = greedy_policy.select_victim(candidates)
                decision_overheads.append(time.perf_counter() - d_start)
                if victim:
                    ev = gc.clean_segment(
                        victim=victim,
                        policy_name="Greedy",
                        trigger_reason=trigger_reason,
                        workload_phase=current_phase_label,
                    )
                    return ev is not None
            return False

        def emergency_gc():
            # Clean segments until at least 1 segment is returned to free pool
            for _ in range(len(lfs.segment_manager.segments)):
                if len(lfs.segment_manager.free_segment_ids) > 0:
                    break
                success = do_gc("EMERGENCY_LOW_SPACE")
                if not success:
                    break

        lfs.segment_manager.gc_callback = emergency_gc

        # Run operation stream
        for op in workload_ops:
            op_count += 1
            op_type = op[0]
            path = op[1]
            offset = op[2]
            data = op[3]
            current_phase_label = op[4] if len(op) > 4 else "DEFAULT"

            # Check GC trigger before write operations
            should_gc, reason = trigger.should_trigger(lfs.segment_manager)
            if should_gc:
                do_gc(reason)

            # 1. Execute filesystem operation
            if op_type == "WRITE":
                lfs.write(path, offset, data)
                monitor.record_op("WRITE", path, offset, len(data), 0)
            elif op_type == "UPDATE":
                lfs.write(path, offset, data)
                monitor.record_op("UPDATE", path, offset, len(data), 1)
            elif op_type == "READ":
                try:
                    lfs.read(path, offset, block_size)
                    monitor.record_op("READ", path, offset, block_size, 0)
                except FileNotFoundError:
                    pass
            elif op_type in ("DELETE", "UNLINK"):
                try:
                    lfs.unlink(path)
                    monitor.record_op("DELETE", path, 0, 0, 1)
                except FileNotFoundError:
                    pass

        elapsed_sec = time.perf_counter() - start_time
        regret = adaptive_policy.feedback_loop.cumulative_regret if adaptive_policy else 0.0
        fallback_rate = adaptive_policy.safety_filter.fallback_rate if adaptive_policy else 0.0
        exploration_rate = adaptive_policy.exploration_policy.exploration_rate if adaptive_policy else 0.0

        summary = MetricsCalculator.summarize(
            policy_name=policy_type,
            total_ops=op_count,
            elapsed_sec=elapsed_sec,
            logical_bytes=lfs.segment_manager.block_manager.logical_bytes_written,
            physical_bytes=lfs.segment_manager.block_manager.physical_bytes_written,
            gc_events=gc.history,
            cumulative_regret=regret,
            fallback_rate=fallback_rate,
            exploration_rate=exploration_rate,
            decision_overhead_list_sec=decision_overheads,
        )

        # Log GC events
        self.logger.log_gc_events(policy_type, gc.history)
        return summary

    def run_comparative_benchmark(
        self,
        ops_per_phase: int = 300,
        seed: int = 42,
    ) -> List[BenchmarkSummary]:
        """
        Runs the phase-changing benchmark comparing FIFO, Greedy, Static Online LR,
        Drift-Aware, and Full Adaptive Policy.
        """
        generator = WorkloadGenerator(seed=seed)
        phase_ops = list(generator.workload_phase_changing(ops_per_phase=ops_per_phase))

        configs = [
            ("fifo", {"enable_drift": False, "enable_exploration": False, "enable_safety": True}),
            ("greedy", {"enable_drift": False, "enable_exploration": False, "enable_safety": True}),
            ("online_lr", {"enable_drift": False, "enable_exploration": False, "enable_safety": True, "enable_workload_features": False}),
            ("drift_aware", {"enable_drift": True, "enable_exploration": False, "enable_safety": True, "enable_workload_features": True}),
            ("full_adaptive", {"enable_drift": True, "enable_exploration": True, "enable_safety": True, "enable_workload_features": True}),
        ]

        summaries = []
        for policy_name, flags in configs:
            ptype = "fifo" if policy_name == "fifo" else ("greedy" if policy_name == "greedy" else "adaptive")
            print(f"--> Running benchmark for policy: {policy_name.upper()}...")
            summary = self.run_workload_for_policy(
                policy_type=ptype,
                workload_ops=phase_ops,
                total_segments=self.config["filesystem"]["total_segments"],
                blocks_per_segment=self.config["filesystem"]["blocks_per_segment"],
                enable_drift=flags.get("enable_drift", True),
                enable_exploration=flags.get("enable_exploration", True),
                enable_safety=flags.get("enable_safety", True),
                enable_workload_features=flags.get("enable_workload_features", True),
            )
            # Tag clean policy name
            summary.policy_name = policy_name
            summaries.append(summary)

        # Save all summaries
        self.logger.log_benchmark_summaries(summaries)
        return summaries
