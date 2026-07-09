"""KOReader-compatible partial-MD5 document digest.

KOReader identifies a book for progress sync (kosync) by hashing 1 KiB
samples at exponentially spaced offsets — util.partialMD5 in the KOReader
source: ``md5 of file[o : o+1024] for o in 1024 << (2*i), i = -1..10``.

The i = -1 step matters: LuaJIT BitOp masks shift counts to 5 bits, so
``lshift(1024, -2)`` is ``(1024 << 30) mod 2^32 = 0`` — the sample at the
file head. Reproducing that quirk exactly is what makes our digests match
the ones KOReader computes on-device.
"""

import hashlib

_STEP = 1024
_SAMPLE_SIZE = 1024


def compute_partial_md5(path: str) -> str | None:
    """Digest of the file at ``path``, or None when it cannot be read."""
    digest = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for i in range(-1, 11):
                offset = (_STEP << ((2 * i) & 31)) & 0xFFFFFFFF
                f.seek(offset)
                chunk = f.read(_SAMPLE_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
