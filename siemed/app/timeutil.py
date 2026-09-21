from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings


def tz():
    try:
        return ZoneInfo(settings.timezone)
    except ZoneInfoNotFoundError:
        return timezone(timedelta(hours=5))


def now() -> datetime:
    return datetime.now(tz()).replace(tzinfo=None)


def as_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(tz()).replace(tzinfo=None)


def fmt(dt: datetime | None, pattern: str = "%d.%m.%Y %H:%M") -> str:
    local = as_local(dt)
    if local is None:
        return "—"
    return local.strftime(pattern)
