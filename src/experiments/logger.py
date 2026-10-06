"""
Structured Experiment Logger: Exports GC event logs and benchmark summaries to CSV and JSON.
"""

from __future__ import annotations
import csv
import json
import os
from typing import List, Dict, Any

from src.gc.collector import GCEvent
from src.experiments.metrics import BenchmarkSummary


class ExperimentLogger:
    """
    Saves machine-readable experiment results according to PRD requirements.
    """

    def __init__(self, output_dir: str = "results"):
        self.output_dir: str = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def log_gc_events(self, policy_name: str, events: List[GCEvent]) -> Tuple[str, str]:
        """Saves individual GC events to CSV and JSON."""
        safe_name = policy_name.lower().replace(" ", "_").replace("-", "_")
        csv_path = os.path.join(self.output_dir, f"gc_events_{safe_name}.csv")
        json_path = os.path.join(self.output_dir, f"gc_events_{safe_name}.json")

        if not events:
            return csv_path, json_path

        # Write CSV
        fields = list(events[0].to_dict().keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for e in events:
                writer.writerow(e.to_dict())

        # Write JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([e.to_dict() for e in events], f, indent=2)

        return csv_path, json_path

    def log_benchmark_summaries(self, summaries: List[BenchmarkSummary]) -> str:
        """Saves aggregated comparison summaries across policies."""
        csv_path = os.path.join(self.output_dir, "benchmark_summary.csv")
        json_path = os.path.join(self.output_dir, "benchmark_summary.json")

        if not summaries:
            return csv_path

        fields = list(summaries[0].to_dict().keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for s in summaries:
                writer.writerow(s.to_dict())

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in summaries], f, indent=2)

        return csv_path
