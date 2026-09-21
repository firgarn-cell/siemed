from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import StaffUser
from app.security import read_token


def current_staff(
    siemed_auth: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> StaffUser:
    if not siemed_auth:
        raise HTTPException(status_code=401, detail="need_auth")
    data = read_token(siemed_auth)
    if not data or "uid" not in data:
        raise HTTPException(status_code=401, detail="need_auth")
    user = db.get(StaffUser, int(data["uid"]))
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="need_auth")
    return user


def current_admin(user: StaffUser = Depends(current_staff)) -> StaffUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_only")
    return user


def optional_staff(
    siemed_auth: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> StaffUser | None:
    if not siemed_auth:
        return None
    data = read_token(siemed_auth)
    if not data:
        return None
    user = db.get(StaffUser, int(data["uid"]))
    if not user or not user.active:
        return None
    return user


def request_is_public(request: Request) -> bool:
    return bool(getattr(request.state, "public_listener", False))
