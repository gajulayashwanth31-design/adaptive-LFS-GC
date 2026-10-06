"""
LFS Core: Log-Structured File System core operations, path resolution,
append-only writes, block invalidation, and data relocation.
"""

from __future__ import annotations
import math
import time
from typing import Dict, List, Optional, Tuple, Any

from src.storage.segment_manager import SegmentManager
from src.filesystem.metadata import Inode, InodeMap


class LFSCore:
    """
    Core implementation of the Log-Structured File System.
    Provides standard POSIX-like filesystem semantics backed by an append-only log.
    """

    def __init__(
        self,
        segment_manager: Optional[SegmentManager] = None,
        block_size: int = 4096,
        total_segments: int = 32,
        blocks_per_segment: int = 64,
    ):
        self.block_size: int = block_size
        self.segment_manager: SegmentManager = segment_manager or SegmentManager(
            total_segments=total_segments,
            blocks_per_segment=blocks_per_segment,
            block_size=block_size,
        )
        self.inode_map: InodeMap = InodeMap()

        # Operational metrics
        self.total_reads: int = 0
        self.total_writes: int = 0
        self.total_updates: int = 0
        self.total_deletes: int = 0
        self.total_truncates: int = 0
        self.last_op_time: float = time.time()

    # -------------------------------------------------------------------------
    # Path Resolution Helpers
    # -------------------------------------------------------------------------

    def _split_path(self, path: str) -> List[str]:
        parts = [p for p in path.strip("/").split("/") if p]
        return parts

    def _resolve_path(self, path: str) -> Optional[Inode]:
        """Traverses path components starting from root inode (1)."""
        parts = self._split_path(path)
        curr_inode = self.inode_map.get_inode(1)
        if not curr_inode:
            return None

        for part in parts:
            if not curr_inode.is_directory:
                return None
            next_ino = curr_inode.dir_entries.get(part)
            if next_ino is None:
                return None
            curr_inode = self.inode_map.get_inode(next_ino)
            if curr_inode is None:
                return None
        return curr_inode

    def _resolve_parent(self, path: str) -> Tuple[Optional[Inode], Optional[str]]:
        """Resolves the parent directory inode and filename of the target."""
        parts = self._split_path(path)
        if not parts:
            return None, None
        filename = parts[-1]
        parent_parts = parts[:-1]

        curr_inode = self.inode_map.get_inode(1)
        if not curr_inode:
            return None, None

        for part in parent_parts:
            if not curr_inode.is_directory:
                return None, None
            next_ino = curr_inode.dir_entries.get(part)
            if next_ino is None:
                return None, None
            curr_inode = self.inode_map.get_inode(next_ino)
            if curr_inode is None:
                return None, None

        return curr_inode, filename

    # -------------------------------------------------------------------------
    # Filesystem Operations
    # -------------------------------------------------------------------------

    def create(self, path: str, mode: int = 0o644) -> Inode:
        """Creates a new regular file."""
        parent_inode, filename = self._resolve_parent(path)
        if parent_inode is None or filename is None:
            raise FileNotFoundError(f"Parent directory not found for path: {path}")
        if filename in parent_inode.dir_entries:
            raise FileExistsError(f"File already exists: {path}")

        new_inode = self.inode_map.allocate_inode(is_directory=False, mode=mode)
        parent_inode.dir_entries[filename] = new_inode.inode_number
        parent_inode.mtime = time.time()
        self.last_op_time = time.time()
        return new_inode

    def mkdir(self, path: str, mode: int = 0o755) -> Inode:
        """Creates a new directory."""
        parent_inode, dirname = self._resolve_parent(path)
        if parent_inode is None or dirname is None:
            raise FileNotFoundError(f"Parent directory not found for path: {path}")
        if dirname in parent_inode.dir_entries:
            raise FileExistsError(f"Directory already exists: {path}")

        new_dir_inode = self.inode_map.allocate_inode(is_directory=True, mode=mode)
        new_dir_inode.dir_entries[".."] = parent_inode.inode_number
        parent_inode.dir_entries[dirname] = new_dir_inode.inode_number
        parent_inode.mtime = time.time()
        self.last_op_time = time.time()
        return new_dir_inode

    def getattr(self, path: str) -> Dict[str, Any]:
        """Returns file attributes dictionary (stat info)."""
        inode = self._resolve_path(path)
        if not inode:
            raise FileNotFoundError(f"Path not found: {path}")

        return {
            "st_mode": inode.mode,
            "st_ino": inode.inode_number,
            "st_nlink": inode.nlink,
            "st_size": inode.size,
            "st_uid": inode.uid,
            "st_gid": inode.gid,
            "st_atime": inode.atime,
            "st_mtime": inode.mtime,
            "st_ctime": inode.ctime,
        }

    def readdir(self, path: str) -> List[str]:
        """Lists directory entries."""
        inode = self._resolve_path(path)
        if not inode:
            raise FileNotFoundError(f"Directory not found: {path}")
        if not inode.is_directory:
            raise NotADirectoryError(f"Not a directory: {path}")

        return list(inode.dir_entries.keys())

    def read(self, path: str, offset: int, size: int) -> bytes:
        """
        Reads data from a file at specified offset and size.
        """
        inode = self._resolve_path(path)
        if not inode:
            raise FileNotFoundError(f"File not found: {path}")
        if inode.is_directory:
            raise IsADirectoryError(f"Cannot read directory as file: {path}")

        self.total_reads += 1
        self.last_op_time = time.time()
        inode.atime = self.last_op_time

        if offset >= inode.size:
            return b""

        bytes_to_read = min(size, inode.size - offset)
        if bytes_to_read <= 0:
            return b""

        start_block = offset // self.block_size
        end_block = (offset + bytes_to_read - 1) // self.block_size

        result = bytearray()
        bytes_read = 0

        for block_idx in range(start_block, end_block + 1):
            block_loc = inode.get_block_location(block_idx)
            if block_loc is None:
                # Sparse block: read zeros
                block_data = b"\x00" * self.block_size
            else:
                seg_id, seg_offset = block_loc
                block_data = self.segment_manager.read_block(seg_id, seg_offset)

            block_start = 0 if block_idx > start_block else (offset % self.block_size)
            needed = bytes_to_read - bytes_read
            chunk = block_data[block_start : block_start + needed]
            result.extend(chunk)
            bytes_read += len(chunk)

        return bytes(result)

    def write(self, path: str, offset: int, data: bytes) -> int:
        """
        Writes data sequentially into the LFS append log.
        If rewriting existing blocks, invalidates prior block locations.
        """
        inode = self._resolve_path(path)
        if not inode:
            # Auto-create if not existing
            inode = self.create(path)

        if inode.is_directory:
            raise IsADirectoryError(f"Cannot write directly to directory: {path}")

        data_len = len(data)
        if data_len == 0:
            return 0

        is_update = offset < inode.size
        if is_update:
            self.total_updates += 1
        else:
            self.total_writes += 1

        self.last_op_time = time.time()
        inode.mtime = self.last_op_time

        start_block = offset // self.block_size
        end_block = (offset + data_len - 1) // self.block_size

        data_written = 0

        for block_idx in range(start_block, end_block + 1):
            block_start = 0 if block_idx > start_block else (offset % self.block_size)
            chunk_len = min(data_len - data_written, self.block_size - block_start)
            new_chunk = data[data_written : data_written + chunk_len]

            # Read existing block if partial write to merge
            if block_start > 0 or chunk_len < self.block_size:
                old_loc = inode.get_block_location(block_idx)
                if old_loc:
                    old_seg, old_off = old_loc
                    base_data = bytearray(self.segment_manager.read_block(old_seg, old_off))
                else:
                    base_data = bytearray(self.block_size)
                base_data[block_start : block_start + chunk_len] = new_chunk
                full_block = bytes(base_data)
            else:
                full_block = new_chunk

            # Invalidate old block location if present
            old_loc = inode.get_block_location(block_idx)
            if old_loc is not None:
                old_seg, old_off = old_loc
                self.segment_manager.invalidate_block(old_seg, old_off)

            # Append new block to active segment
            meta = self.segment_manager.write_block(
                inode_number=inode.inode_number,
                file_block_offset=block_idx,
                data=full_block,
                is_gc_relocation=False,
            )

            # Update inode mapping
            inode.set_block_location(block_idx, meta.segment_id, meta.offset)
            data_written += chunk_len

        # Update file size
        new_size = max(inode.size, offset + data_len)
        inode.size = new_size
        return data_len

    def truncate(self, path: str, length: int) -> None:
        """
        Truncates file to a specified length.
        Invalidates removed blocks.
        """
        inode = self._resolve_path(path)
        if not inode:
            raise FileNotFoundError(f"File not found: {path}")

        self.total_truncates += 1
        self.last_op_time = time.time()
        inode.mtime = self.last_op_time

        if length < inode.size:
            first_removed_block = math.ceil(length / self.block_size)
            blocks_to_remove = [b for b in inode.block_map.keys() if b >= first_removed_block]
            for b in blocks_to_remove:
                loc = inode.remove_block_location(b)
                if loc:
                    seg_id, seg_offset = loc
                    self.segment_manager.invalidate_block(seg_id, seg_offset)

        inode.size = length

    def unlink(self, path: str) -> None:
        """
        Deletes a regular file and invalidates all its blocks.
        """
        parent_inode, filename = self._resolve_parent(path)
        if parent_inode is None or filename is None:
            raise FileNotFoundError(f"File not found: {path}")

        ino = parent_inode.dir_entries.get(filename)
        if ino is None:
            raise FileNotFoundError(f"File not found: {path}")

        target_inode = self.inode_map.get_inode(ino)
        if not target_inode:
            raise FileNotFoundError(f"Inode {ino} not found")
        if target_inode.is_directory:
            raise IsADirectoryError(f"Cannot unlink directory with unlink(): {path}")

        # Invalidate all allocated blocks
        for block_idx, (seg_id, seg_off) in list(target_inode.block_map.items()):
            self.segment_manager.invalidate_block(seg_id, seg_off)

        # Remove from directory and inode map
        del parent_inode.dir_entries[filename]
        self.inode_map.remove_inode(ino)
        self.total_deletes += 1
        self.last_op_time = time.time()

    # -------------------------------------------------------------------------
    # Garbage Collection Support: Block Relocation
    # -------------------------------------------------------------------------

    def relocate_valid_block(
        self,
        inode_number: int,
        file_block_offset: int,
        old_segment_id: int,
        old_offset: int,
    ) -> bool:
        """
        Relocates a live block from a cleaning victim segment to the active log.
        Updates the file's inode block map atomically.
        Returns True if relocated, False if block was already superseded/invalidated.
        """
        inode = self.inode_map.get_inode(inode_number)
        if not inode:
            # Inode deleted in the meantime
            return False

        curr_loc = inode.get_block_location(file_block_offset)
        if curr_loc != (old_segment_id, old_offset):
            # Block was overwritten elsewhere; old block is dead
            return False

        # Read live data from old segment
        data = self.segment_manager.read_block(old_segment_id, old_offset)

        # Append to active segment marked as GC relocation
        meta = self.segment_manager.write_block(
            inode_number=inode_number,
            file_block_offset=file_block_offset,
            data=data,
            is_gc_relocation=True,
        )

        # Invalidate old block location
        self.segment_manager.invalidate_block(old_segment_id, old_offset)

        # Update inode block pointer to new location
        inode.set_block_location(file_block_offset, meta.segment_id, meta.offset)
        return True
