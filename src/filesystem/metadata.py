"""
Filesystem metadata structures (Inodes, directory entries, and Inode Map) for LFS.
"""

from __future__ import annotations
import time
from typing import Dict, Tuple, Optional, List


class Inode:
    """
    Logical inode representing a file or directory.
    Maintains block pointers mapping file_block_offset -> (segment_id, segment_offset).
    """

    def __init__(
        self,
        inode_number: int,
        is_directory: bool = False,
        mode: int = 0o644,
        uid: int = 1000,
        gid: int = 1000,
    ):
        self.inode_number: int = inode_number
        self.is_directory: bool = is_directory
        self.mode: int = mode | (0o40000 if is_directory else 0o100000)
        self.uid: int = uid
        self.gid: int = gid
        self.size: int = 0
        self.nlink: int = 2 if is_directory else 1

        now = time.time()
        self.atime: float = now
        self.mtime: float = now
        self.ctime: float = now

        # file_block_offset -> (segment_id, segment_offset)
        self.block_map: Dict[int, Tuple[int, int]] = {}

        # If directory: filename -> inode_number
        self.dir_entries: Dict[str, int] = {}
        if is_directory:
            self.dir_entries["."] = inode_number

    def get_block_location(self, block_offset: int) -> Optional[Tuple[int, int]]:
        return self.block_map.get(block_offset)

    def set_block_location(self, block_offset: int, segment_id: int, segment_offset: int) -> None:
        self.block_map[block_offset] = (segment_id, segment_offset)
        self.mtime = time.time()

    def remove_block_location(self, block_offset: int) -> Optional[Tuple[int, int]]:
        return self.block_map.pop(block_offset, None)


class InodeMap:
    """
    Tracks all active inodes in the LFS.
    Provides allocation and lookup for inodes.
    """

    def __init__(self):
        self._inodes: Dict[int, Inode] = {}
        self._next_ino: int = 1

        # Allocate root directory inode 1
        root_inode = self.allocate_inode(is_directory=True)
        root_inode.dir_entries[".."] = 1

    def allocate_inode(self, is_directory: bool = False, mode: int = 0o644) -> Inode:
        ino = self._next_ino
        self._next_ino += 1
        inode = Inode(inode_number=ino, is_directory=is_directory, mode=mode)
        self._inodes[ino] = inode
        return inode

    def get_inode(self, inode_number: int) -> Optional[Inode]:
        return self._inodes.get(inode_number)

    def remove_inode(self, inode_number: int) -> Optional[Inode]:
        return self._inodes.pop(inode_number, None)

    def all_inodes(self) -> List[Inode]:
        return list(self._inodes.values())
