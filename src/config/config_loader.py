"""
Configuration loader for LFS experiments.
"""

from __future__ import annotations
import os
from typing import Dict, Any
import yaml


DEFAULT_CONFIG: Dict[str, Any] = {
    "filesystem": {
        "total_segments": 32,
        "blocks_per_segment": 64,
        "block_size": 4096,
    },
    "gc": {
        "free_space_threshold": 0.25,
        "hard_free_space_threshold": 0.08,
        "min_sealed_segments": 1,
    },
    "workload": {
        "window_size": 500,
        "cooldown_ops": 150,
    },
    "drift": {
        "threshold": 0.30,
        "min_window_ops": 100,
    },
    "learning": {
        "learning_rate": 0.02,
        "l2_reg": 0.001,
        "initial_confidence": 0.40,
    },
    "exploration": {
        "epsilon": 0.10,
        "decay": 0.995,
        "min_epsilon": 0.02,
        "uncertainty_weight": 0.15,
    },
    "utility": {
        "reclaim_weight": 1.0,
        "copy_cost_weight": 0.5,
        "latency_weight": 0.2,
    },
    "safety": {
        "confidence_threshold": 0.55,
        "fallback_policy": "greedy",
    },
}


def load_config(config_path: str = "src/config/config.yaml") -> Dict[str, Any]:
    """Loads configuration from YAML file or returns defaults."""
    if not os.path.exists(config_path):
        return DEFAULT_CONFIG

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            return cfg or DEFAULT_CONFIG
    except Exception:
        return DEFAULT_CONFIG
