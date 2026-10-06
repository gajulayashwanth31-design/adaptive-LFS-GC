"""
Workload Generator: Generates deterministic synthetic storage workloads (A through F).
"""

from __future__ import annotations
import random
from typing import Generator, Tuple, Optional, List
from src.filesystem.lfs_core import LFSCore
from src.workload.monitor import WorkloadMonitor


class WorkloadGenerator:
    """
    Produces deterministic streams of filesystem operations.
    Supports individual workload types (A-E) and phase-changing transitions (F).
    """

    def __init__(self, seed: int = 42, block_size: int = 4096):
        self.seed: int = seed
        self.block_size: int = block_size
        self.rng = random.Random(seed)

    def reseed(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed if seed is not None else self.seed)

    # -------------------------------------------------------------------------
    # Workload A: Sequential Writes
    # -------------------------------------------------------------------------
    def workload_sequential(
        self,
        num_ops: int = 1000,
        blocks_per_file: int = 4,
    ) -> Generator[Tuple[str, str, int, bytes], None, None]:
        """
        Creates files and writes blocks in strictly sequential order.
        """
        file_idx = 0
        curr_offset = 0
        for _ in range(num_ops):
            path = f"/seq_file_{file_idx}.dat"
            data = self.rng.randbytes(self.block_size)
            yield ("WRITE", path, curr_offset, data)
            curr_offset += self.block_size
            if (curr_offset // self.block_size) >= blocks_per_file:
                file_idx += 1
                curr_offset = 0

    # -------------------------------------------------------------------------
    # Workload B: Random Writes & Updates
    # -------------------------------------------------------------------------
    def workload_random(
        self,
        num_ops: int = 1000,
        num_files: int = 20,
        max_blocks: int = 8,
    ) -> Generator[Tuple[str, str, int, bytes], None, None]:
        """
        Randomly selects among existing files and random block offsets to write/overwrite.
        """
        for _ in range(num_ops):
            file_id = self.rng.randint(0, num_files - 1)
            path = f"/rand_file_{file_id}.dat"
            blk_offset = self.rng.randint(0, max_blocks - 1) * self.block_size
            data = self.rng.randbytes(self.block_size)
            yield ("WRITE", path, blk_offset, data)

    # -------------------------------------------------------------------------
    # Workload C: Update-Heavy (High Invalidation)
    # -------------------------------------------------------------------------
    def workload_update_heavy(
        self,
        num_ops: int = 1000,
        working_set_files: int = 5,
        blocks_per_file: int = 4,
    ) -> Generator[Tuple[str, str, int, bytes], None, None]:
        """
        Concentrates continuous overwrites on a tight working set.
        Generates rapid block invalidations.
        """
        for _ in range(num_ops):
            f_id = self.rng.randint(0, working_set_files - 1)
            path = f"/hot_file_{f_id}.dat"
            blk_offset = self.rng.randint(0, blocks_per_file - 1) * self.block_size
            data = self.rng.randbytes(self.block_size)
            yield ("UPDATE", path, blk_offset, data)

    # -------------------------------------------------------------------------
    # Workload D: Delete-Heavy
    # -------------------------------------------------------------------------
    def workload_delete_heavy(
        self,
        num_ops: int = 1000,
        pool_size: int = 20,
    ) -> Generator[Tuple[str, str, int, Optional[bytes]], None, None]:
        """
        Creates batches of files, writes data, and then deletes them.
        """
        active_files: List[str] = []
        file_counter = 0

        for _ in range(num_ops):
            if len(active_files) >= pool_size or (active_files and self.rng.random() < 0.45):
                # Delete an existing file
                idx = self.rng.randint(0, len(active_files) - 1)
                victim_path = active_files.pop(idx)
                yield ("DELETE", victim_path, 0, None)
            else:
                # Create and write a new file
                file_counter += 1
                new_path = f"/temp_file_{file_counter}.dat"
                active_files.append(new_path)
                data = self.rng.randbytes(self.block_size)
                yield ("WRITE", new_path, 0, data)

    # -------------------------------------------------------------------------
    # Workload E: Mixed (Reads, Writes, Updates, Deletes)
    # -------------------------------------------------------------------------
    def workload_mixed(
        self,
        num_ops: int = 1000,
        num_files: int = 15,
        blocks_per_file: int = 6,
    ) -> Generator[Tuple[str, str, int, Optional[bytes]], None, None]:
        """
        Realistic enterprise mix:
        40% Read, 25% Sequential Append, 25% In-place Update, 10% Delete.
        """
        files = [f"/mix_file_{i}.dat" for i in range(num_files)]
        for _ in range(num_ops):
            r = self.rng.random()
            path = self.rng.choice(files)
            blk_offset = self.rng.randint(0, blocks_per_file - 1) * self.block_size

            if r < 0.40:
                yield ("READ", path, blk_offset, None)
            elif r < 0.65:
                data = self.rng.randbytes(self.block_size)
                yield ("WRITE", path, blk_offset, data)
            elif r < 0.90:
                data = self.rng.randbytes(self.block_size)
                yield ("UPDATE", path, blk_offset, data)
            else:
                yield ("DELETE", path, 0, None)

    # -------------------------------------------------------------------------
    # Workload F: Phase-Changing (Core Research Workload)
    # -------------------------------------------------------------------------
    def workload_phase_changing(
        self,
        ops_per_phase: int = 500,
    ) -> Generator[Tuple[str, str, int, Optional[bytes], str], None, None]:
        """
        Executes distinct phases sequentially:
        Phase 1: Sequential -> Phase 2: Random -> Phase 3: Update-Heavy ->
        Phase 4: Delete-Heavy -> Phase 5: Mixed.
        Yields: (op_type, path, offset, data, phase_name)
        """
        phases = [
            ("SEQUENTIAL", self.workload_sequential(ops_per_phase)),
            ("RANDOM", self.workload_random(ops_per_phase)),
            ("UPDATE_HEAVY", self.workload_update_heavy(ops_per_phase)),
            ("DELETE_HEAVY", self.workload_delete_heavy(ops_per_phase)),
            ("MIXED", self.workload_mixed(ops_per_phase)),
        ]

        for phase_name, gen in phases:
            for item in gen:
                op_type, path, offset, data = item
                yield (op_type, path, offset, data, phase_name)
