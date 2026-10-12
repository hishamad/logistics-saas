from datetime import datetime, timedelta
from math import ceil, floor


def minute_up(value: datetime, origin: datetime) -> int:
    return ceil((value - origin).total_seconds() / 60)


def minute_down(value: datetime, origin: datetime) -> int:
    return floor((value - origin).total_seconds() / 60)


def instant(minute: int, origin: datetime) -> datetime:
    return origin + timedelta(minutes=minute)


def overlaps(start: datetime, end: datetime, other_start: datetime, other_end: datetime) -> bool:
    # Empty half-open intervals do not occupy a resource.
    return start < end and other_start < other_end and start < other_end and other_start < end
