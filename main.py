"""
Main Entry Point for Workload-Adaptive LFS Garbage Collection Research Prototype.
"""

import sys
import argparse
from typing import List

from src.experiments.runner import ExperimentRunner
from src.experiments.plotter import ExperimentPlotter
from src.experiments.metrics import BenchmarkSummary
from src.workload.generator import WorkloadGenerator
from src.filesystem.lfs_core import LFSCore
from src.workload.monitor import WorkloadMonitor
from src.gc.adaptive import AdaptiveGCPolicy
from src.gc.collector import GarbageCollector
from src.gc.trigger import GCTrigger


def print_summary_table(summaries: List[BenchmarkSummary]):
    print("\n" + "=" * 92)
    print(f"{'POLICY':<16} | {'OPS':<6} | {'WA':<7} | {'GCs':<5} | {'RECLAIM (KB)':<14} | {'LATENCY (ms)':<14} | {'OVERHEAD (ms)':<13}")
    print("-" * 92)
    for s in summaries:
        mean_reclaim_kb = s.mean_reclaimed_per_gc / 1024.0
        print(
            f"{s.policy_name.upper():<16} | "
            f"{s.total_ops:<6} | "
            f"{s.write_amplification:<7.2f} | "
            f"{s.gc_count:<5} | "
            f"{mean_reclaim_kb:<14.1f} | "
            f"{s.mean_gc_latency_ms:<14.2f} | "
            f"{s.mean_decision_overhead_ms:<13.3f}"
        )
    print("=" * 92 + "\n")


def cmd_benchmark(args):
    print("================================================================================")
    print(" Running Workload-Adaptive LFS Comparative Benchmark (Phase-Changing Workload)")
    print(f" Operations per phase: {args.ops_per_phase} | Total phases: 5 | Seed: {args.seed}")
    print("================================================================================")

    runner = ExperimentRunner(config_path=args.config)
    summaries = runner.run_comparative_benchmark(
        ops_per_phase=args.ops_per_phase,
        seed=args.seed,
    )

    print_summary_table(summaries)

    print("--> Generating visualization plots in plots/...")
    plotter = ExperimentPlotter(output_dir="plots")
    plots = plotter.generate_all_plots(summaries)
    for p in plots:
        print(f"  [+] Saved plot: {p}")
    print("\nBenchmark completed successfully! Logs saved to results/")


def cmd_ablation(args):
    print("================================================================================")
    print(" Running Ablation Studies (PRD Section 30)")
    print("================================================================================")

    runner = ExperimentRunner(config_path=args.config)
    generator = WorkloadGenerator(seed=args.seed)
    phase_ops = list(generator.workload_phase_changing(ops_per_phase=args.ops_per_phase))

    ablations = [
        ("Full_Adaptive", {"enable_drift": True, "enable_exploration": True, "enable_safety": True, "enable_workload_features": True}),
        ("Ablation_A_NoDrift", {"enable_drift": False, "enable_exploration": True, "enable_safety": True, "enable_workload_features": True}),
        ("Ablation_B_NoExploration", {"enable_drift": True, "enable_exploration": False, "enable_safety": True, "enable_workload_features": True}),
        ("Ablation_C_NoSafety", {"enable_drift": True, "enable_exploration": True, "enable_safety": False, "enable_workload_features": True}),
        ("Ablation_D_NoWorkloadFeats", {"enable_drift": True, "enable_exploration": True, "enable_safety": True, "enable_workload_features": False}),
    ]

    summaries = []
    for name, flags in ablations:
        print(f"--> Running: {name}...")
        summary = runner.run_workload_for_policy(
            policy_type="adaptive",
            workload_ops=phase_ops,
            total_segments=runner.config["filesystem"]["total_segments"],
            blocks_per_segment=runner.config["filesystem"]["blocks_per_segment"],
            enable_drift=flags["enable_drift"],
            enable_exploration=flags["enable_exploration"],
            enable_safety=flags["enable_safety"],
            enable_workload_features=flags["enable_workload_features"],
        )
        summary.policy_name = name
        summaries.append(summary)

    print_summary_table(summaries)
    plotter = ExperimentPlotter(output_dir="plots")
    p = plotter.plot_write_amplification(summaries)
    print(f"  [+] Saved ablation plot: {p}")


def cmd_demo(args):
    print("================================================================================")
    print(" Interactive Explainability Demo — Live GC Decision Inspection")
    print("================================================================================")

    lfs = LFSCore(total_segments=8, blocks_per_segment=8, block_size=4096)
    monitor = WorkloadMonitor(window_size=50)
    policy = AdaptiveGCPolicy(
        segment_manager=lfs.segment_manager,
        workload_monitor=monitor,
        enable_exploration=True,
    )
    gc = GarbageCollector(lfs=lfs, on_gc_complete_callback=policy.on_gc_completed)
    trigger = GCTrigger(free_space_threshold=0.30)

    # Simulate dynamic writes and overwrites
    print("--> Simulating sequential appends followed by hot overwrites...")
    for i in range(24):
        path = f"/file_{i % 4}.dat"
        data = f"DATA_BLOCK_VERSION_1_{i}".encode() * 64
        lfs.write(path, (i // 4) * 4096, data)
        monitor.record_op("WRITE", path, 0, len(data))

    # Overwrite some blocks
    for i in range(8):
        path = f"/file_0.dat"
        data = f"OVERWRITE_VERSION_2_{i}".encode() * 64
        lfs.write(path, i * 4096, data)
        monitor.record_op("UPDATE", path, i * 4096, len(data), 1)

    candidates = lfs.segment_manager.get_eligible_candidates()
    print(f"--> Found {len(candidates)} eligible sealed candidate segments.")

    victim, explanation, score, is_exp, fb, fb_reason = policy.select_victim(
        eligible_candidates=candidates,
        current_op_count=32,
    )

    print("\n" + explanation.to_formatted_string() + "\n")

    event = gc.clean_segment(
        victim=victim,
        policy_name=policy.name,
        predicted_utility=score,
        confidence=explanation.confidence,
        is_exploration=is_exp,
        fallback_used=fb,
        fallback_reason=fb_reason,
    )

    print(f"GC Result: Cleaned Segment {event.victim_segment_id}")
    print(f"  Reclaimed: {event.reclaimed_bytes / 1024:.1f} KB")
    print(f"  Copied: {event.copied_bytes / 1024:.1f} KB")
    print(f"  Latency: {event.latency_sec * 1000.0:.3f} ms")
    print(f"  Observed Utility: {event.observed_utility:.3f}")
    print(f"  Write Amplification: {event.write_amplification:.2f}x")


def cmd_web(args):
    import uvicorn
    print("================================================================================")
    print(f" Launching LFS Adaptive GC Visual Dashboard on http://{args.host}:{args.port}")
    print(" Press Ctrl+C to stop the server.")
    print("================================================================================")
    uvicorn.run("src.ui.server:app", host=args.host, port=args.port, reload=False)


def main():
    parser = argparse.ArgumentParser(
        description="Workload-Adaptive Online Decision Making for LFS Garbage Collection"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # benchmark
    p_bench = subparsers.add_parser("benchmark", help="Run comparative benchmark across all policies")
    p_bench.add_argument("--ops-per-phase", type=int, default=300, help="Operations per workload phase (default: 300)")
    p_bench.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    p_bench.add_argument("--config", type=str, default="src/config/config.yaml", help="Path to config.yaml")

    # ablation
    p_ablate = subparsers.add_parser("ablation", help="Run ablation studies (NoDrift, NoExploration, etc.)")
    p_ablate.add_argument("--ops-per-phase", type=int, default=250, help="Operations per phase (default: 250)")
    p_ablate.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    p_ablate.add_argument("--config", type=str, default="src/config/config.yaml", help="Path to config.yaml")

    # demo
    subparsers.add_parser("demo", help="Run interactive explainability demo")

    # web
    p_web = subparsers.add_parser("web", help="Launch interactive real-time visual web dashboard")
    p_web.add_argument("--host", type=str, default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    p_web.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")

    args = parser.parse_args()
    if args.command == "benchmark":
        cmd_benchmark(args)
    elif args.command == "ablation":
        cmd_ablation(args)
    elif args.command == "demo":
        cmd_demo(args)
    elif args.command == "web":
        cmd_web(args)
    else:
        # Default to benchmark if no command provided
        parser.print_help()


if __name__ == "__main__":
    main()
