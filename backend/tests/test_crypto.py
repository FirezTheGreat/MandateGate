"""crypto.py + clock.py: canonical JSON, HMAC sign/verify, ids, nonces, ISO timestamps."""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app import crypto
from app.clock import parse_iso, to_iso
from app.crypto import canonical_json, new_id, new_nonce, sign, verify

KEY = "ab" * 32
OBJ = {"invoice_id": "INV-1048", "amount_paise": 485000, "payee_account": "ACME-4410-2291"}


# --------------------------------------------------------------------------- canonical JSON


def test_canonical_json_is_sorted_compact_utf8() -> None:
    assert canonical_json({"b": 1, "a": "₹"}) == '{"a":"₹","b":1}'.encode("utf-8")


def test_canonical_json_ignores_key_order() -> None:
    assert canonical_json({"a": 1, "b": {"y": 2, "x": 1}}) == canonical_json({"b": {"x": 1, "y": 2}, "a": 1})


@pytest.mark.parametrize("bad", [4850.0, {"amount": 1.5}, [1, 2.0], float("nan")])
def test_canonical_json_refuses_floats(bad: object) -> None:
    """Invariant 8: nothing signed may contain a float (money is integer paise)."""
    with pytest.raises(TypeError):
        canonical_json(bad)


# --------------------------------------------------------------------------- sign / verify


def test_sign_verify_round_trip() -> None:
    sig = sign(KEY, OBJ)
    assert re.fullmatch(r"[0-9a-f]{64}", sig)
    assert verify(KEY, OBJ, sig)


def test_verify_rejects_wrong_key() -> None:
    assert not verify("cd" * 32, OBJ, sign(KEY, OBJ))


@pytest.mark.parametrize("field,value", [("amount_paise", 485001), ("payee_account", "EVE-777"), ("invoice_id", "INV-1")])
def test_verify_rejects_tampered_object(field: str, value: object) -> None:
    sig = sign(KEY, OBJ)
    assert not verify(KEY, {**OBJ, field: value}, sig)


@pytest.mark.parametrize("sig", ["", "0" * 64, "zz" * 32, "é" * 64, "AB" * 32])
def test_verify_rejects_bad_signatures_without_raising(sig: str) -> None:
    assert not verify(KEY, OBJ, sig)


def test_verify_rejects_non_string_signature() -> None:
    assert not verify(KEY, OBJ, None)  # type: ignore[arg-type]


def test_verify_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invariant 9: signatures are compared with hmac.compare_digest."""
    calls: list[tuple[object, object]] = []
    real = crypto.hmac.compare_digest

    def spy(a, b):  # type: ignore[no-untyped-def]
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(crypto.hmac, "compare_digest", spy)
    assert verify(KEY, OBJ, sign(KEY, OBJ))
    assert calls


def test_sign_refuses_empty_key() -> None:
    with pytest.raises(ValueError):
        sign("", OBJ)


# --------------------------------------------------------------------------- ids and nonces


def test_new_nonce_is_32_hex_and_unique() -> None:
    nonces = {new_nonce() for _ in range(1000)}
    assert len(nonces) == 1000
    assert all(re.fullmatch(r"[0-9a-f]{32}", n) for n in nonces)


def test_new_id_has_prefix_and_16_hex() -> None:
    assert re.fullmatch(r"mdt_[0-9a-f]{16}", new_id("mdt"))


# --------------------------------------------------------------------------- timestamps


def test_iso_round_trip_is_utc_z() -> None:
    dt = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)
    assert to_iso(dt) == "2026-10-17T09:00:00Z"
    assert parse_iso("2026-10-17T09:00:00Z") == dt


def test_parse_iso_converts_offsets_to_utc() -> None:
    assert parse_iso("2026-10-17T14:30:00+05:30") == datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


def test_to_iso_converts_aware_non_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    assert to_iso(datetime(2026, 10, 17, 14, 30, tzinfo=ist)) == "2026-10-17T09:00:00Z"


@pytest.mark.parametrize("bad", ["2026-10-17T09:00:00", "2026-10-17", "yesterday", ""])
def test_parse_iso_rejects_naive_or_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_iso(bad)


def test_to_iso_rejects_naive() -> None:
    with pytest.raises(ValueError):
        to_iso(datetime(2026, 10, 17, 9, 0))
