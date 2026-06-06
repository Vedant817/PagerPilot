from datetime import datetime, timezone
from typing import Any


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        ts = float(value)
        # Datadog/GitHub APIs may return milliseconds or seconds.
        if ts > 10_000_000_000:
            ts = ts / 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit():
        return parse_timestamp(int(text))

    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def timestamp_sort_key(value: Any) -> datetime:
    return parse_timestamp(value) or datetime.max.replace(tzinfo=timezone.utc)


def to_utc_iso(value: Any) -> str:
    dt = parse_timestamp(value)
    if not dt:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
