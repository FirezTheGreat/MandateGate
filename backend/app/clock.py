"""UTC time helpers. All timestamps on the wire are ISO-8601 UTC strings ("...Z").

Pure functions take `now` as an argument; only `utc_now()` reads the clock.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    """Aware datetime → "YYYY-MM-DDTHH:MM:SSZ" (second precision, UTC)."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime; use an aware UTC datetime")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    """ISO-8601 with an explicit offset or Z → aware UTC datetime. Naive or garbage → ValueError."""
    if not isinstance(s, str) or "T" not in s:
        raise ValueError(f"not an ISO-8601 timestamp: {s!r}")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp has no UTC offset: {s!r}")
    return dt.astimezone(UTC)
