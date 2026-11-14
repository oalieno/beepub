"""A limit on guessing an account's password — at the login form, and at
OPDS and kosync, which check the same password on every request.

Counted per account, not per address: the address a request claims is
the client's to write (X-Forwarded-For), an account name is not. And
counted in *different* wrong passwords, not in attempts: an e-reader
left with an old password repeats one wrong value all day and must not
lock its owner out of the web, while someone guessing has to try a new
value each time. A value already known to be wrong is refused without
being checked again, so repeating it costs no password hashing either.

In memory, per process: a restart forgets, which only ever errs towards
letting someone try again.
"""

import hashlib
import time

WINDOW_SECONDS = 15 * 60
MAX_WRONG_PASSWORDS = 10
_MAX_ACCOUNTS = 10_000

# account name → {digest of a wrong password: when it was tried}
_wrong: dict[str, dict[str, float]] = {}


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8", "surrogatepass")).hexdigest()


def _recent(username: str) -> dict[str, float]:
    key = username.casefold()
    tried = _wrong.get(key)
    if not tried:
        return {}
    cutoff = time.monotonic() - WINDOW_SECONDS
    for digest in [d for d, at in tried.items() if at < cutoff]:
        del tried[digest]
    if not tried:
        del _wrong[key]
    return tried


def refused(username: str, secret: str) -> bool:
    """Whether this attempt is turned away without being checked: the
    value is one already found wrong, or the account has had its share of
    wrong ones for now."""
    tried = _recent(username)
    return _digest(secret) in tried or len(tried) >= MAX_WRONG_PASSWORDS


def locked(username: str) -> bool:
    """Whether the account has had its share of wrong passwords for now
    (for telling the person so, rather than "wrong password")."""
    return len(_recent(username)) >= MAX_WRONG_PASSWORDS


def record_wrong(username: str, secret: str) -> None:
    if len(_wrong) >= _MAX_ACCOUNTS:
        # Names that were never accounts, most likely: start over rather
        # than grow without bound.
        _wrong.clear()
    _wrong.setdefault(username.casefold(), {})[_digest(secret)] = time.monotonic()


def record_right(username: str) -> None:
    _wrong.pop(username.casefold(), None)
