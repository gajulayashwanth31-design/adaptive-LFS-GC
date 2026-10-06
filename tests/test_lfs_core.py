"""
Integration and functional tests for LFSCore.
"""

import pytest
from src.filesystem.lfs_core import LFSCore


def test_lfs_create_write_read():
    lfs = LFSCore(total_segments=8, blocks_per_segment=8, block_size=4096)
    lfs.create("/file1.txt")
    data = b"Hello LFS World! Testing append-only storage."
    written = lfs.write("/file1.txt", 0, data)
    assert written == len(data)

    read_data = lfs.read("/file1.txt", 0, len(data))
    assert read_data == data

    # Verify stat attributes
    attr = lfs.getattr("/file1.txt")
    assert attr["st_size"] == len(data)


def test_lfs_overwrite_invalidates_prior_blocks():
    lfs = LFSCore(total_segments=8, blocks_per_segment=8, block_size=4096)
    data1 = b"A" * 4096
    data2 = b"B" * 4096

    # Write initial block
    lfs.write("/test.bin", 0, data1)
    seg0 = lfs.segment_manager.segments[0]
    assert seg0.valid_blocks == 1
    assert seg0.invalid_blocks == 0

    # Overwrite same block
    lfs.write("/test.bin", 0, data2)
    # Block 0 in seg0 should now be invalid
    assert seg0.invalid_blocks == 1

    # Read back should return data2
    read_back = lfs.read("/test.bin", 0, 4096)
    assert read_back == data2


def test_lfs_unlink_invalidates_blocks():
    lfs = LFSCore(total_segments=8, blocks_per_segment=8, block_size=4096)
    lfs.write("/temp.bin", 0, b"X" * 8192)  # 2 blocks
    seg0 = lfs.segment_manager.segments[0]
    assert seg0.valid_blocks == 2
    assert seg0.invalid_blocks == 0

    lfs.unlink("/temp.bin")
    assert seg0.valid_blocks == 0
    assert seg0.invalid_blocks == 2

    with pytest.raises(FileNotFoundError):
        lfs.read("/temp.bin", 0, 100)


def test_lfs_relocate_valid_block():
    lfs = LFSCore(total_segments=4, blocks_per_segment=4, block_size=4096)
    lfs.write("/important.dat", 0, b"CRITICAL_DATA_LFS")
    inode = lfs._resolve_path("/important.dat")
    old_loc = inode.get_block_location(0)
    assert old_loc is not None
    old_seg, old_off = old_loc

    # Relocate block
    relocated = lfs.relocate_valid_block(
        inode_number=inode.inode_number,
        file_block_offset=0,
        old_segment_id=old_seg,
        old_offset=old_off,
    )
    assert relocated is True

    # Check new location
    new_loc = inode.get_block_location(0)
    assert new_loc != old_loc

    # Verify content remains unchanged
    assert lfs.read("/important.dat", 0, len(b"CRITICAL_DATA_LFS")) == b"CRITICAL_DATA_LFS"
