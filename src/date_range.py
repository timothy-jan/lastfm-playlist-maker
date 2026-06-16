"""Parse and format custom listening date ranges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


def parse_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def validate_date_range(start: date | None, end: date | None) -> str | None:
    if start is None or end is None:
        return "Pick both a start date and an end date for your custom range."
    if start > end:
        return "The start date needs to come before the end date."
    if end > date.today():
        return "Your end date can't be in the future."
    return None


def parse_date_range(date_from: str | None, date_to: str | None) -> tuple[DateRange | None, str | None]:
    start = parse_date(date_from)
    end = parse_date(date_to)
    error = validate_date_range(start, end)
    if error:
        return None, error
    assert start is not None and end is not None
    return DateRange(start=start, end=end), None


def date_range_to_unix(date_range: DateRange) -> tuple[int, int]:
    """Return (from, to) Unix timestamps for Last.fm (UTC, end inclusive)."""
    start_dt = datetime(
        date_range.start.year,
        date_range.start.month,
        date_range.start.day,
        tzinfo=timezone.utc,
    )
    end_exclusive = datetime(
        date_range.end.year,
        date_range.end.month,
        date_range.end.day,
        tzinfo=timezone.utc,
    ) + timedelta(days=1)
    return int(start_dt.timestamp()), int(end_exclusive.timestamp())


def format_date_human(value: date) -> str:
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def format_date_range_human(date_range: DateRange) -> str:
    if date_range.start.year == date_range.end.year:
        if date_range.start.month == date_range.end.month:
            return (
                f"{date_range.start.strftime('%b')} {date_range.start.day}"
                f"–{date_range.end.day}, {date_range.end.year}"
            )
        return (
            f"{format_date_human(date_range.start).rsplit(', ', 1)[0]}"
            f" – {format_date_human(date_range.end)}"
        )
    return f"{format_date_human(date_range.start)} – {format_date_human(date_range.end)}"


def default_custom_range() -> DateRange:
    today = date.today()
    return DateRange(start=today - timedelta(days=30), end=today)
