"""
Optional FUSE adapter for LFS using fusepy.
Allows mounting the LFS prototype as a real filesystem mount on Linux/macOS/WinFsp.
"""

from __future__ import annotations
import os
import sys
import errno
from typing import Dict, Any

from src.filesystem.lfs_core import LFSCore


try:
    from fuse import FUSE, FuseOSError, Operations
    HAS_FUSE = True
except ImportError:
    HAS_FUSE = False
    Operations = object  # Dummy base class
    class FuseOSError(Exception):
        pass


class LFSFuseOperations(Operations):
    """
    Exposes LFSCore through standard FUSE operations.
    """

    def __init__(self, lfs_core: LFSCore):
        self.lfs = lfs_core

    def getattr(self, path: str, fh=None) -> Dict[str, Any]:
        try:
            return self.lfs.getattr(path)
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)

    def readdir(self, path: str, fh=None):
        try:
            return self.lfs.readdir(path)
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)
        except NotADirectoryError:
            raise FuseOSError(errno.ENOTDIR)

    def mkdir(self, path: str, mode: int):
        try:
            self.lfs.mkdir(path, mode)
            return 0
        except FileExistsError:
            raise FuseOSError(errno.EEXIST)
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)

    def create(self, path: str, mode: int, fi=None):
        try:
            self.lfs.create(path, mode)
            return 0
        except FileExistsError:
            raise FuseOSError(errno.EEXIST)

    def read(self, path: str, size: int, offset: int, fh=None) -> bytes:
        try:
            return self.lfs.read(path, offset, size)
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)

    def write(self, path: str, data: bytes, offset: int, fh=None) -> int:
        return self.lfs.write(path, offset, data)

    def truncate(self, path: str, length: int, fh=None):
        try:
            self.lfs.truncate(path, length)
            return 0
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)

    def unlink(self, path: str):
        try:
            self.lfs.unlink(path)
            return 0
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)


def mount_lfs(mountpoint: str, lfs_core: LFSCore, foreground: bool = True):
    """Mounts LFS to mountpoint if FUSE is available."""
    if not HAS_FUSE:
        print("[LFS FUSE] Warning: fusepy not installed or FUSE driver unavailable.", file=sys.stderr)
        print("[LFS FUSE] LFSCore is fully functional in user space / benchmark mode.", file=sys.stderr)
        return
    FUSE(LFSFuseOperations(lfs_core), mountpoint, foreground=foreground, nothreads=True)
