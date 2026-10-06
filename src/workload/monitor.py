"""
Workload Monitor: Tracks operation streams in a sliding window and extracts online workload statistics.
"""

from __future__ import annotations
import time
from collections import deque
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class OpRecord:
    op_type: str         # "READ", "WRITE", "UPDATE", "DELETE", "TRUNCATE"
    path: str
    offset: int
    size: int
    timestamp: float
    invalidated_blocks: int = 0


class WorkloadMonitor:
    """
    Monitors filesystem operations using a sliding window of recent operations.
    Extracts continuous statistical features representing current workload behavior.
    """

    def __init__(self, window_size: int = 500):
        self.window_size: int = window_size
        self.window: deque[OpRecord] = deque(maxlen=window_size)
        self.total_ops_recorded: int = 0
        self._last_write_path: Optional[str] = None
        self._last_write_end: int = 0

    def record_op(
        self,
        op_type: str,
        path: str,
        offset: int = 0,
        size: int = 0,
        invalidated_blocks: int = 0,
        timestamp: Optional[float] = None,
    ) -> None:
        """Records an operation into the sliding window."""
        now = timestamp if timestamp is not None else time.time()
        record = OpRecord(
            op_type=op_type.upper(),
            path=path,
            offset=offset,
            size=size,
            timestamp=now,
            invalidated_blocks=invalidated_blocks,
        )
        self.window.append(record)
        self.total_ops_recorded += 1

    def is_window_full(self) -> bool:
        return len(self.window) >= self.window_size

    def get_features(self) -> Dict[str, float]:
        """
        Computes normalized workload features over the current sliding window.
        Returns:
            - read_rate
            - write_rate
            - update_rate
            - delete_rate
            - sequentiality
            - randomness
            - average_request_size
            - invalidation_rate
            - ops_per_second
        """
        n = len(self.window)
        if n == 0:
            return {
                "read_rate": 0.0,
                "write_rate": 0.0,
                "update_rate": 0.0,
                "delete_rate": 0.0,
                "sequentiality": 0.0,
                "randomness": 1.0,
                "average_request_size": 0.0,
                "invalidation_rate": 0.0,
                "ops_per_second": 0.0,
            }

        reads = 0
        writes = 0
        updates = 0
        deletes = 0
        total_size = 0
        invalidations = 0
        sequential_writes = 0
        write_count = 0

        prev_path: Optional[str] = None
        prev_end: int = 0

        for r in self.window:
            if r.op_type == "READ":
                reads += 1
            elif r.op_type == "WRITE":
                writes += 1
                write_count += 1
                if prev_path == r.path and r.offset == prev_end:
                    sequential_writes += 1
                prev_path = r.path
                prev_end = r.offset + r.size
            elif r.op_type == "UPDATE":
                updates += 1
                write_count += 1
                if prev_path == r.path and r.offset == prev_end:
                    sequential_writes += 1
                prev_path = r.path
                prev_end = r.offset + r.size
            elif r.op_type in ("DELETE", "UNLINK"):
                deletes += 1

            total_size += r.size
            invalidations += r.invalidated_blocks

        # Rates
        read_rate = reads / n
        write_rate = writes / n
        update_rate = updates / n
        delete_rate = deletes / n

        # Sequentiality
        sequentiality = (sequential_writes / write_count) if write_count > 0 else 0.0
        randomness = 1.0 - sequentiality

        avg_req_size = total_size / n
        inval_rate = invalidations / n

        # Ops per second
        time_span = max(0.001, self.window[-1].timestamp - self.window[0].timestamp)
        ops_per_sec = n / time_span

        return {
            "read_rate": float(read_rate),
            "write_rate": float(write_rate),
            "update_rate": float(update_rate),
            "delete_rate": float(delete_rate),
            "sequentiality": float(sequentiality),
            "randomness": float(randomness),
            "average_request_size": float(avg_req_size),
            "invalidation_rate": float(inval_rate),
            "ops_per_second": float(ops_per_sec),
        }
