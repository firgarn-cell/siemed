from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import StaffUser
from app.security import make_token, verify_password
from app.settings_store import get_setting
from app.web import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, db: Session = Depends(get_db), next: str = "/"):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "", "next": next, "station_name": get_setting(db, "station_name")},
    )


@router.post("/login")
def login_post(
    request: Request,
    db: Session = Depends(get_db),
    login: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    user = db.query(StaffUser).filter(StaffUser.login == login.strip()).first()
    if not user or not user.active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Неверный логин или пароль",
                "next": next,
                "station_name": get_setting(db, "station_name"),
            },
        )
    token = make_token({"uid": user.id, "role": user.role})
    dest = next if next.startswith("/") else "/"
    if dest.startswith("/login"):
        dest = "/"
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(
        "siemed_auth",
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 14,
    )
    return resp


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("siemed_auth")
    return resp
