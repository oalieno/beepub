"""Short-TTL cache of verified per-request credentials.

bcrypt verification costs ~100ms and e-reader protocols (OPDS Basic auth,
kosync headers) resend credentials on every request — a feed page plus its
covers is 50+ verifications. Successful verifications are cached briefly,
keyed by a hash of the exact credentials. A password change invalidates
naturally on TTL expiry; account deletion/deactivation is handled by
callers re-loading the user row on every request.
"""

import hashlib
import time
import uuid


class CredentialCache:
    def __init__(self, ttl_seconds: float = 300.0, max_entries: int = 1000):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: dict[str, tuple[uuid.UUID, float]] = {}

    @staticmethod
    def key(*parts: str) -> str:
        return hashlib.sha256("\x00".join(parts).encode()).hexdigest()

    def get(self, key: str) -> uuid.UUID | None:
        entry = self._entries.get(key)
        if entry is None or entry[1] <= time.monotonic():
            return None
        return entry[0]

    def put(self, key: str, user_id: uuid.UUID) -> None:
        if len(self._entries) >= self._max:
            self._entries.clear()
        self._entries[key] = (user_id, time.monotonic() + self._ttl)

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)
