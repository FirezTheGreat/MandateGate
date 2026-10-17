"""Crypto primitives: canonical JSON, HMAC-SHA-256 sign/verify, ids, nonces.

`canonical_json` is THE ONE way to turn an object into signed bytes (CLAUDE.md §2.10).
Never re-implement it. All signature checks go through `hmac.compare_digest` (§2.9).
Keys are the env strings (e.g. 64 hex chars) used as UTF-8 bytes.
"""

import hashlib
import hmac
import json
import secrets
from typing import Any


def _refuse_floats(obj: Any) -> None:
    """Signed data must not contain floats: money is integer paise and float text is unstable."""
    if isinstance(obj, float):
        raise TypeError("floats are not allowed in signed data")
    if isinstance(obj, dict):
        for v in obj.values():
            _refuse_floats(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _refuse_floats(v)


def canonical_json(obj: Any) -> bytes:
    _refuse_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _key_bytes(key: str) -> bytes:
    if not key:
        raise ValueError("empty signing key")
    return key.encode("utf-8")


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def constant_time_equal(a: str, b: str) -> bool:
    """Compare two signature strings in constant time. Non-strings are never equal."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def sign(key: str, obj: Any) -> str:
    """Hex HMAC-SHA-256 of canonical_json(obj)."""
    return hmac_sha256(_key_bytes(key), canonical_json(obj)).hex()


def verify(key: str, obj: Any, sig: str) -> bool:
    return constant_time_equal(sign(key, obj), sig)


def new_nonce() -> str:
    """32 hex chars (128 bits)."""
    return secrets.token_hex(16)


def new_id(prefix: str) -> str:
    """e.g. new_id("mdt") → "mdt_3f9a1c0b7d2e4a65"."""
    return f"{prefix}_{secrets.token_hex(8)}"
