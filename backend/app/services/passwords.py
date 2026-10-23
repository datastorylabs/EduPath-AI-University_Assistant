"""Argon2id password hashing helpers."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id baseline: 19 MiB memory, 2 iterations, one lane.
_password_hasher = PasswordHasher(time_cost=2, memory_cost=19_456, parallelism=1)


def hash_password(password: str) -> str:
    """Return a unique Argon2id hash; never log or persist the raw password."""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify without leaking hash parsing or mismatch exceptions."""
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError, ValueError):
        return False


def password_hash_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except (VerificationError, InvalidHashError, TypeError, ValueError):
        return True
