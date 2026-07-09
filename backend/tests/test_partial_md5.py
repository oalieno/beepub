"""KOReader partial-MD5 digest — offset semantics.

True cross-validation happens against a real KOReader device; these tests
pin the properties the algorithm must have: the file head IS sampled
(the LuaJIT shift-mask quirk), unsampled gaps don't affect the digest,
and sampled regions do.
"""

import hashlib

from app.services.partial_md5 import compute_partial_md5


def _write(tmp_path, data: bytes) -> str:
    path = tmp_path / "book.bin"
    path.write_bytes(data)
    return str(path)


def test_small_file_digest_is_plain_md5(tmp_path):
    # A file under 1 KiB is fully covered by the sample at offset 0.
    data = b"beepub" * 100
    assert compute_partial_md5(_write(tmp_path, data)) == hashlib.md5(data).hexdigest()


def test_head_change_changes_digest(tmp_path):
    base = bytearray(8192)
    changed = bytearray(base)
    changed[100] = 0xFF
    assert compute_partial_md5(_write(tmp_path, bytes(base))) != compute_partial_md5(
        _write(tmp_path, bytes(changed))
    )


def test_unsampled_gap_does_not_change_digest(tmp_path):
    # Samples cover [0,2048) and [4096,5120); byte 3000 sits in the gap.
    base = bytearray(8192)
    changed = bytearray(base)
    changed[3000] = 0xFF
    assert compute_partial_md5(_write(tmp_path, bytes(base))) == compute_partial_md5(
        _write(tmp_path, bytes(changed))
    )


def test_sampled_offset_4096_changes_digest(tmp_path):
    base = bytearray(8192)
    changed = bytearray(base)
    changed[4200] = 0xFF
    assert compute_partial_md5(_write(tmp_path, bytes(base))) != compute_partial_md5(
        _write(tmp_path, bytes(changed))
    )


def test_missing_file_returns_none(tmp_path):
    assert compute_partial_md5(str(tmp_path / "nope.epub")) is None
