"""Provenance: turn tool results into value observations, and match proposed values against them.

Pure functions only (no I/O). Persistence lives in db.py.

Trust is never read from the data. It comes from the Fragment, which the broker builds from
its own tool registry: which tool produced a value decides where it came from (CLAUDE.md §2.2).
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from app.models import SourceType, Trust, ValueRecord

# Zero-width / invisible characters (U+200B–U+200D, U+FEFF per §6, plus word joiner and soft hyphen).
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
# Separators removed by normalize(): whitespace, - . _ /, and the Unicode dashes and minus sign.
_SEPARATORS = re.compile(r"[\s\-._/‐-―−]")

# Account / ID-like runs in free text: starts with A-Z or a digit, ends with a digit, may contain
# spaces and dashes (so "E V E-7 7 7" survives). Matched on NFKC-folded text.
_ID_RUN = re.compile(r"[A-Z0-9][A-Z0-9 \-]{3,62}[0-9]")
_MAX_CHUNKS = 12
MIN_IDENTIFIER = 5  # normalized length

# Money in prose: ₹ / Rs / INR followed by a rupee amount with optional paise.
_MONEY = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?([0-9]{1,3}(?:,[0-9]{2,3})+|[0-9]{1,12})(?:\.([0-9]{1,2}))?", re.IGNORECASE)

# Containment matching only for values long enough not to collide by accident.
MIN_CONTAINED = 5

CRITICAL_FIELDS = ("bank.account_number", "amount_due_paise")


def fold(s: str) -> str:
    """NFKC (full-width → ASCII) and drop invisible characters. Case and spacing kept."""
    return unicodedata.normalize("NFKC", s).translate(_INVISIBLE)


def normalize(s: str) -> str:
    """CLAUDE.md §6: NFKC → remove zero-width → uppercase → strip whitespace and separators."""
    return _SEPARATORS.sub("", fold(s).upper())


def walk_leaves(obj: Any, path: str = "") -> Iterator[tuple[str, str | int]]:
    """Every string/int leaf with its JSON path ("bank.account_number", "[0].subject")."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_leaves(v, f"{path}[{i}]")
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (str, int)):
        yield path, obj


def extract_identifiers(text: str) -> list[str]:
    """Account-number / ID-like tokens buried in prose, in folded form, de-duplicated.

    A run like "PLEASE PAY EVE-777" also yields its space-separated sub-spans, so the
    identifier is captured whether or not neighbouring words are capitalised."""
    folded = fold(text)
    out: list[str] = []
    seen: set[str] = set()
    for run in _ID_RUN.finditer(folded):
        s = run.group(0)
        chunks = [m.span() for m in re.finditer(r"\S+", s)][:_MAX_CHUNKS]
        for i in range(len(chunks)):
            for j in range(i, len(chunks)):
                sub = s[chunks[i][0] : chunks[j][1]]
                if not (sub[0].isalnum() and sub[-1].isdigit()) or len(normalize(sub)) < MIN_IDENTIFIER:
                    continue
                if sub not in seen:
                    seen.add(sub)
                    out.append(sub)
    return out


def extract_amounts(text: str) -> list[int]:
    """Rupee amounts in prose → integer paise ("Rs. 4,850.00" → 485000). Never floats."""
    out: list[int] = []
    for m in _MONEY.finditer(fold(text)):
        rupees = int(m.group(1).replace(",", ""))
        paise = int((m.group(2) or "0").ljust(2, "0"))
        out.append(rupees * 100 + paise)
    return out


@dataclass(frozen=True)
class Fragment:
    """A piece of a tool result with the provenance the broker assigns to it."""

    value: Any
    path: str  # JSON path of `value` inside the tool result ("" = the whole result)
    source_type: SourceType
    source_ref: str
    trust: Trust


@dataclass(frozen=True)
class Observation:
    """One value the agent saw, before it is persisted as a ValueRecord."""

    raw: str
    normalized: str
    field_hint: str
    source_type: SourceType
    source_ref: str
    trust: Trust


def observe(fragments: Iterable[Fragment]) -> list[Observation]:
    """Every leaf of every fragment, plus identifiers and amounts found inside free text."""
    out: list[Observation] = []
    for f in fragments:
        for path, leaf in walk_leaves(f.value, f.path):
            raw = str(leaf)
            n = normalize(raw)
            if not n:
                continue
            hint = path or "$"
            out.append(Observation(raw, n, hint, f.source_type, f.source_ref, f.trust))
            if isinstance(leaf, str) and any(ch.isspace() for ch in leaf):
                for ident in extract_identifiers(leaf):
                    out.append(Observation(ident, normalize(ident), hint + "#identifier", f.source_type, f.source_ref, f.trust))
                for paise in extract_amounts(leaf):
                    out.append(Observation(str(paise), str(paise), hint + "#amount", f.source_type, f.source_ref, f.trust))
    return out


def is_critical(o: Observation) -> bool:
    """Values worth a `value_recorded` event: anything that could be a payee or an amount.
    Free-text identifiers must mix letters and digits (account-like), which keeps phone numbers,
    PIN codes and dates out of the live feed. Every observation is still stored for matching."""
    if o.field_hint in CRITICAL_FIELDS or o.field_hint.endswith("#amount"):
        return True
    if o.field_hint.endswith("#identifier"):
        return any(ch.isalpha() for ch in o.normalized) and any(ch.isdigit() for ch in o.normalized)
    return False


def matches(records: Iterable[ValueRecord], raw: str, *, contained: bool = True) -> list[ValueRecord]:
    """Records whose normalized value equals normalize(raw), or (for long enough values)
    contains it, so a value buried in an email body is still attributed to that email."""
    n = normalize(raw)
    if not n:
        return []
    return [r for r in records if r.normalized == n or (contained and len(n) >= MIN_CONTAINED and n in r.normalized)]


def describe(records: Iterable[ValueRecord]) -> list[str]:
    """["email:1842 (untrusted)", ...], sorted and de-duplicated, for Decision.found."""
    return sorted({f"{r.source_ref} ({r.trust})" for r in records})
