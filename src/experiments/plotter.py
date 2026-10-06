"""
Experiment Plotter: Generates research visualization dashboard and plots (PRD Section 39).
"""

from __future__ import annotations
import os
from typing import List
import matplotlib
matplotlib.use("Agg")  # Headless backend for automation
import matplotlib.pyplot as plt

from src.experiments.metrics import BenchmarkSummary


class ExperimentPlotter:
    """
    Generates comparison charts and graphs from benchmark summaries.
    """

    def __init__(self, output_dir: str = "plots"):
        self.output_dir: str = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate_all_plots(self, summaries: List[BenchmarkSummary]) -> List[str]:
        """Generates all standard comparison plots and returns list of image paths."""
        generated = []
        p1 = self.plot_write_amplification(summaries)
        p2 = self.plot_reclaimed_space(summaries)
        p3 = self.plot_gc_latency(summaries)
        p4 = self.plot_overhead_and_throughput(summaries)
        p5 = self.plot_comprehensive_dashboard(summaries)
        generated.extend([p1, p2, p3, p4, p5])
        return generated

    def plot_write_amplification(self, summaries: List[BenchmarkSummary]) -> str:
        names = [s.policy_name.upper() for s in summaries]
        was = [s.write_amplification for s in summaries]

        fig, ax = plt.subplots(figsize=(8, 5))
        bars = ax.bar(names, was, color=["#4A90E2", "#50E3C2", "#F5A623", "#9013FE", "#E74C3C"], edgecolor="black")
        ax.set_ylabel("Write Amplification (WA)")
        ax.set_title("Write Amplification by Garbage Collection Policy")
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=1, label="Ideal WA (1.0)")

        for bar in bars:
            height = bar.get_height()
            ax.annotate(f"{height:.2f}x",
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontweight="bold")

        ax.legend()
        plt.tight_layout()
        out_path = os.path.join(self.output_dir, "write_amplification_comparison.png")
        plt.savefig(out_path, dpi=300)
        plt.close()
        return out_path

    def plot_reclaimed_space(self, summaries: List[BenchmarkSummary]) -> str:
        names = [s.policy_name.upper() for s in summaries]
        mean_reclaimed_kb = [s.mean_reclaimed_per_gc / 1024.0 for s in summaries]

        fig, ax = plt.subplots(figsize=(8, 5))
        bars = ax.bar(names, mean_reclaimed_kb, color="#2ECC71", edgecolor="black")
        ax.set_ylabel("Mean Space Reclaimed per GC (KB)")
        ax.set_title("Space Reclamation Efficiency")

        for bar in bars:
            height = bar.get_height()
            ax.annotate(f"{height:.1f} KB",
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom")

        plt.tight_layout()
        out_path = os.path.join(self.output_dir, "space_reclamation_comparison.png")
        plt.savefig(out_path, dpi=300)
        plt.close()
        return out_path

    def plot_gc_latency(self, summaries: List[BenchmarkSummary]) -> str:
        names = [s.policy_name.upper() for s in summaries]
        mean_lat = [s.mean_gc_latency_ms for s in summaries]
        p95_lat = [s.p95_gc_latency_ms for s in summaries]

        x = range(len(names))
        width = 0.35

        fig, ax = plt.subplots(figsize=(9, 5))
        ax.bar([i - width/2 for i in x], mean_lat, width, label="Mean Latency (ms)", color="#3498DB", edgecolor="black")
        ax.bar([i + width/2 for i in x], p95_lat, width, label="p95 Latency (ms)", color="#E67E22", edgecolor="black")

        ax.set_xticks(list(x))
        ax.set_xticklabels(names)
        ax.set_ylabel("Cleaning Latency (ms)")
        ax.set_title("GC Latency Distribution (Mean vs. 95th Percentile)")
        ax.legend()

        plt.tight_layout()
        out_path = os.path.join(self.output_dir, "gc_latency_distribution.png")
        plt.savefig(out_path, dpi=300)
        plt.close()
        return out_path

    def plot_overhead_and_throughput(self, summaries: List[BenchmarkSummary]) -> str:
        names = [s.policy_name.upper() for s in summaries]
        overheads = [s.mean_decision_overhead_ms for s in summaries]
        throughputs = [s.throughput_ops_sec for s in summaries]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        ax1.bar(names, overheads, color="#9B59B6", edgecolor="black")
        ax1.set_ylabel("Decision Overhead (ms)")
        ax1.set_title("Policy Decision Overhead")
        ax1.tick_params(axis='x', rotation=20)

        ax2.bar(names, throughputs, color="#1ABC9C", edgecolor="black")
        ax2.set_ylabel("Throughput (ops/sec)")
        ax2.set_title("System Throughput")
        ax2.tick_params(axis='x', rotation=20)

        plt.tight_layout()
        out_path = os.path.join(self.output_dir, "overhead_and_throughput.png")
        plt.savefig(out_path, dpi=300)
        plt.close()
        return out_path

    def plot_comprehensive_dashboard(self, summaries: List[BenchmarkSummary]) -> str:
        names = [s.policy_name.upper() for s in summaries]
        fig, axs = plt.subplots(2, 2, figsize=(14, 10))

        # 1. Write Amplification
        axs[0, 0].bar(names, [s.write_amplification for s in summaries], color="#4A90E2", edgecolor="black")
        axs[0, 0].set_title("Write Amplification")
        axs[0, 0].set_ylabel("Physical / Logical Bytes")
        axs[0, 0].tick_params(axis='x', rotation=15)

        # 2. GC Cycles count
        axs[0, 1].bar(names, [s.gc_count for s in summaries], color="#E67E22", edgecolor="black")
        axs[0, 1].set_title("Total GC Invocations")
        axs[0, 1].set_ylabel("Number of GC Cycles")
        axs[0, 1].tick_params(axis='x', rotation=15)

        # 3. Space Reclaimed Total (MB)
        axs[1, 0].bar(names, [s.total_reclaimed_bytes / (1024 * 1024) for s in summaries], color="#2ECC71", edgecolor="black")
        axs[1, 0].set_title("Total Reclaimed Space (MB)")
        axs[1, 0].set_ylabel("Reclaimed (MB)")
        axs[1, 0].tick_params(axis='x', rotation=15)

        # 4. Fallback & Exploration Rates (for adaptive policies)
        fb_rates = [s.fallback_rate * 100.0 for s in summaries]
        exp_rates = [s.exploration_rate * 100.0 for s in summaries]
        x = range(len(names))
        w = 0.35
        axs[1, 1].bar([i - w/2 for i in x], fb_rates, w, label="Fallback %", color="#E74C3C", edgecolor="black")
        axs[1, 1].bar([i + w/2 for i in x], exp_rates, w, label="Exploration %", color="#F1C40F", edgecolor="black")
        axs[1, 1].set_xticks(list(x))
        axs[1, 1].set_xticklabels(names, rotation=15)
        axs[1, 1].set_title("Fallback and Exploration Percentages")
        axs[1, 1].set_ylabel("Percentage (%)")
        axs[1, 1].legend()

        plt.suptitle("Workload-Adaptive LFS GC — Comprehensive Evaluation Dashboard", fontsize=15, fontweight="bold")
        plt.tight_layout()
        out_path = os.path.join(self.output_dir, "evaluation_dashboard.png")
        plt.savefig(out_path, dpi=300)
        plt.close()
        return out_path
