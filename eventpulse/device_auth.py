"""Edge device token helpers.

This module implements a small, dependency-free per-device token model.

Design goals:
- No shared fleet secret.
- Tokens can be revoked/rotated server-side.
- No plaintext tokens stored in the database.

Implementation:
- Token: random URL-safe string generated on provisioning/rotation.
- Storage: PBKDF2-HMAC-SHA256 derived key with per-device random salt.

If you need stronger password hashing, consider swapping PBKDF2 for Argon2/bcrypt.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass


DEFAULT_PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
TOKEN_BYTES = 32


def generate_device_token(*, nbytes: int = TOKEN_BYTES) -> str:
    """Generate a new device token suitable for use as a bearer secret."""

    return secrets.token_urlsafe(nbytes)


@dataclass(frozen=True)
class TokenHash:
    salt_b64: str
    hash_b64: str
    iterations: int = DEFAULT_PBKDF2_ITERATIONS


def hash_device_token(
    token: str,
    *,
    salt: bytes | None = None,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
) -> TokenHash:
    """Derive a stable hash for a device token."""

    if not token or not str(token).strip():
        raise ValueError("token is required")

    if salt is None:
        salt = secrets.token_bytes(SALT_BYTES)

    dk = hashlib.pbkdf2_hmac(
        "sha256",
        str(token).encode("utf-8"),
        salt,
        int(iterations),
    )

    return TokenHash(
        salt_b64=base64.b64encode(salt).decode("ascii"),
        hash_b64=base64.b64encode(dk).decode("ascii"),
        iterations=int(iterations),
    )


def verify_device_token(
    token: str,
    *,
    salt_b64: str,
    hash_b64: str,
    iterations: int = DEFAULT_PBKDF2_ITERATIONS,
) -> bool:
    """Verify a provided token against stored parameters."""

    try:
        salt = base64.b64decode(str(salt_b64).encode("ascii"))
        expected = base64.b64decode(str(hash_b64).encode("ascii"))
    except Exception:
        return False

    dk = hashlib.pbkdf2_hmac(
        "sha256",
        str(token).encode("utf-8"),
        salt,
        int(iterations),
    )

    return secrets.compare_digest(dk, expected)


def redact_token(token: str, *, show: int = 6) -> str:
    """Return a safe-to-log token preview."""

    t = str(token or "")
    if len(t) <= show:
        return "***"
    return f"{t[:show]}…***"
