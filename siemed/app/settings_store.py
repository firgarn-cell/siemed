from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Setting


DEFAULTS = {
    "cancel_lead_hours": str(settings.cancel_lead_hours),
    "slot_grace_minutes": str(settings.slot_grace_minutes),
    "public_url": settings.public_url,
    "station_name": settings.station_name,
}


def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(Setting, key)
    if row:
        return row.value
    if key in DEFAULTS:
        return DEFAULTS[key]
    return default


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def get_int(db: Session, key: str, default: int) -> int:
    try:
        return int(get_setting(db, key, str(default)))
    except ValueError:
        return default
