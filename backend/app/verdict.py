"""The result of a verification step: ok or not, plus a human-readable reason."""

from typing import NamedTuple


class Verdict(NamedTuple):
    ok: bool
    detail: str
