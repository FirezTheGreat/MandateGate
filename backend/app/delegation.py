"""Macaroon-style delegation tokens (CLAUDE.md §6).

    sig0 = HMAC(ROOT_KEY, mandate_id);  sig_i = HMAC(sig_{i-1}, caveat_i);  sig = sig_n

Anyone holding a token can append caveats (attenuate) without the root key. Nobody can
remove, edit, or reorder one without breaking the chain. Caveats are conjunctive, and
amount caveats feed the step-up limit (`amount_limit`) instead of `evaluate`.

Grammar (exact spacing, unknown or malformed caveat → fail closed):
    agent = X | agent in A,B | tool = X | tool in A,B | invoice_id = X
    max_amount_paise <= N | expires_before <ISO-8601 with offset>

Pure functions only: no I/O, the caller supplies keys and the time.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.clock import parse_iso
from app.crypto import constant_time_equal, hmac_sha256, new_id
from app.models import MAX_CAVEATS, DelegationToken
from app.verdict import Verdict

MAX_CAVEAT_CHARS = 256
MAX_CHAIN_LENGTH = MAX_CAVEATS

SetField = Literal["agent", "tool", "invoice_id"]
SET_FIELDS: tuple[SetField, ...] = ("agent", "tool", "invoice_id")

_NAME = r"[a-z0-9_]+"
_INVOICE = r"[A-Za-z0-9_-]+"
_PATTERNS: list[tuple[SetField, re.Pattern[str]]] = [
    ("agent", re.compile(rf"agent = ({_NAME})")),
    ("agent", re.compile(rf"agent in ({_NAME}(?:,{_NAME})*)")),
    ("tool", re.compile(rf"tool = ({_NAME})")),
    ("tool", re.compile(rf"tool in ({_NAME}(?:,{_NAME})*)")),
    ("invoice_id", re.compile(rf"invoice_id = ({_INVOICE})")),
]
_AMOUNT = re.compile(r"max_amount_paise <= (0|[1-9][0-9]{0,15})")
_EXPIRES = re.compile(r"expires_before (\S+)")


class CaveatError(ValueError):
    pass


@dataclass(frozen=True)
class Caveat:
    field: Literal["agent", "tool", "invoice_id", "max_amount_paise", "expires_before"]
    allowed: frozenset[str] = frozenset()  # agent / tool / invoice_id
    bound: int | None = None  # max_amount_paise
    deadline: datetime | None = None  # expires_before


@dataclass(frozen=True)
class EvalContext:
    agent: str
    tool: str
    invoice_id: str | None  # None = this action references no invoice (e.g. list_inbox)
    now: datetime


def parse_caveat(text: str) -> Caveat:
    """Strict: the whole string must match one rule exactly (re.fullmatch, ASCII only)."""
    if not isinstance(text, str) or len(text) > MAX_CAVEAT_CHARS or not text.isascii():
        raise CaveatError(f"unknown caveat: {text!r}")
    for field, pattern in _PATTERNS:
        if m := pattern.fullmatch(text):
            return Caveat(field=field, allowed=frozenset(m.group(1).split(",")))
    if m := _AMOUNT.fullmatch(text):
        return Caveat(field="max_amount_paise", bound=int(m.group(1)))
    if m := _EXPIRES.fullmatch(text):
        try:
            return Caveat(field="expires_before", deadline=parse_iso(m.group(1)))
        except ValueError:
            pass
    raise CaveatError(f"unknown caveat: {text!r}")


def root_caveats(max_amount_paise: int) -> list[str]:
    """Caveats on the root token minted with every mandate."""
    return [
        "agent in planner,finance",
        "tool in list_inbox,read_email,get_invoice,get_vendor,fetch_page,propose_payment",
        f"max_amount_paise <= {max_amount_paise}",
    ]


# --------------------------------------------------------------------------- the HMAC chain


def _chain_sig(mandate_id: str, caveats: list[str], root_key: str) -> str:
    if not root_key:
        raise ValueError("empty root key")
    sig = hmac_sha256(root_key.encode("utf-8"), mandate_id.encode("utf-8"))
    for caveat in caveats:
        sig = hmac_sha256(sig, caveat.encode("utf-8"))
    return sig.hex()


def mint_root(mandate_id: str, caveats: list[str], *, root_key: str) -> DelegationToken:
    for c in caveats:
        parse_caveat(c)
    return DelegationToken(
        token_id=new_id("tok"),
        mandate_id=mandate_id,
        caveats=list(caveats),
        parent_token_id=None,
        sig=_chain_sig(mandate_id, list(caveats), root_key),
    )


def attenuate(token: DelegationToken, new_caveats: list[str]) -> DelegationToken:
    """Append caveats. Needs only the token's own sig, never the root key."""
    if len(token.caveats) + len(new_caveats) > MAX_CHAIN_LENGTH:
        raise CaveatError(f"chain would exceed {MAX_CHAIN_LENGTH} caveats and could never verify")
    for c in new_caveats:
        parse_caveat(c)
    try:
        sig = bytes.fromhex(token.sig)
    except ValueError as e:
        raise CaveatError("token signature is not hex") from e
    for c in new_caveats:
        sig = hmac_sha256(sig, c.encode("utf-8"))
    return DelegationToken(
        token_id=new_id("tok"),
        mandate_id=token.mandate_id,
        caveats=[*token.caveats, *new_caveats],
        parent_token_id=token.token_id,
        sig=sig.hex(),
    )


def verify_chain(token: DelegationToken, *, root_key: str) -> Verdict:
    """Recompute the chain from ROOT_KEY. Catches removed, edited, reordered or re-bound caveats."""
    if len(token.caveats) > MAX_CHAIN_LENGTH:
        return Verdict(False, f"token has more than {MAX_CHAIN_LENGTH} caveats")
    expected = _chain_sig(token.mandate_id, token.caveats, root_key)
    if not constant_time_equal(expected, token.sig):
        return Verdict(False, "token signature chain invalid")
    return Verdict(True, f"chain of {len(token.caveats)} caveats verifies")


# --------------------------------------------------------------------------- evaluation


def _holds(c: Caveat, ctx: EvalContext) -> bool:
    if c.field == "agent":
        return ctx.agent in c.allowed
    if c.field == "tool":
        return ctx.tool in c.allowed
    if c.field == "invoice_id":
        return ctx.invoice_id is None or ctx.invoice_id in c.allowed
    if c.field == "expires_before":
        return c.deadline is not None and ctx.now < c.deadline
    if c.field == "max_amount_paise":
        return True  # enforced by amount_limit() in the step-up check, not here
    return False  # unreachable; fail closed anyway


def evaluate(caveats: list[str], ctx: EvalContext) -> Verdict:
    """All non-amount caveats must hold. Any unparseable caveat fails the whole token."""
    failed: list[str] = []
    for text in caveats:
        try:
            caveat = parse_caveat(text)
        except CaveatError:
            return Verdict(False, f"unknown caveat {text!r}")
        if not _holds(caveat, ctx):
            failed.append(text)
    if failed:
        return Verdict(False, "caveat failed: " + "; ".join(failed))
    return Verdict(True, f"{len(caveats)} caveats hold for agent={ctx.agent}, tool={ctx.tool}")


def amount_limit(caveats: list[str]) -> int | None:
    """Tightest max_amount_paise bound in the chain, or None if there is none. Raises on bad caveats."""
    bounds = [c.bound for c in map(parse_caveat, caveats) if c.field == "max_amount_paise" and c.bound is not None]
    return min(bounds) if bounds else None


def detect_escalation(caveats: list[str]) -> list[str]:
    """Caveats that tried to widen authority (no effect thanks to conjunction, but worth flagging)."""
    flagged: list[str] = []
    limit: int | None = None
    allowed: dict[str, frozenset[str]] = {}
    for text in caveats:
        c = parse_caveat(text)
        if c.field == "max_amount_paise" and c.bound is not None:
            if limit is not None and c.bound > limit:
                flagged.append(text)
            limit = c.bound if limit is None else min(limit, c.bound)
        elif c.field in SET_FIELDS:
            current = allowed.get(c.field)
            if current is not None and not c.allowed <= current:
                flagged.append(text)
            allowed[c.field] = c.allowed if current is None else current & c.allowed
    return flagged
