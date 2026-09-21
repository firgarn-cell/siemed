from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Group, Lesson
from app.services import booking as bsvc
from app.settings_store import get_int, get_setting
from app.timeutil import as_local, fmt, now, tz
from app.web import templates

router = APIRouter()


def _page(request: Request, name: str, **ctx):
    db = ctx.get("db")
    return templates.TemplateResponse(
        request,
        name,
        {
            "public_url": get_setting(db, "public_url") if db else "",
            "station_name": get_setting(db, "station_name", "SIEMED") if db else "SIEMED",
            **ctx,
        },
    )


@router.get("/", response_class=HTMLResponse)
def booking_home(request: Request, db: Session = Depends(get_db)):
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    return _page(request, "booking/index.html", db=db, groups=groups, error="")


@router.post("/", response_class=HTMLResponse)
def booking_pick_date(
    request: Request,
    db: Session = Depends(get_db),
    group_id: int = Form(...),
    fio: str = Form(...),
):
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    try:
        fio = " ".join(fio.split())
        if len(fio) < 5:
            raise ValueError("Укажите ФИО полностью")
        group = db.get(Group, group_id)
        if not group:
            raise ValueError("Выберите группу")
        slots = bsvc.free_slots(db)
        by_day: dict[str, list] = defaultdict(list)
        for s in slots:
            key = as_local(s.starts_at).strftime("%Y-%m-%d")
            by_day[key].append(s)
        days = sorted(by_day.keys())
        return _page(
            request,
            "booking/slots.html",
            db=db,
            groups=groups,
            group=group,
            fio=fio,
            days=days,
            by_day=by_day,
            error="",
        )
    except ValueError as exc:
        return _page(request, "booking/index.html", db=db, groups=groups, error=str(exc), fio=fio)


@router.post("/confirm", response_class=HTMLResponse)
def booking_confirm(
    request: Request,
    db: Session = Depends(get_db),
    group_id: int = Form(...),
    fio: str = Form(...),
    slot_id: int = Form(...),
):
    try:
        row = bsvc.create_booking(db, slot_id, group_id, fio)
        return _page(
            request,
            "booking/done.html",
            db=db,
            booking=row,
            slot=row.slot,
            lesson=row.slot.lesson,
            group=row.group,
            cancel_hours=get_int(db, "cancel_lead_hours", 24),
        )
    except ValueError as exc:
        groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
        return _page(request, "booking/index.html", db=db, groups=groups, error=str(exc), fio=fio)


@router.get("/cancel", response_class=HTMLResponse)
def cancel_form(request: Request, db: Session = Depends(get_db)):
    return _page(request, "booking/cancel.html", db=db, error="", ok="")


@router.post("/cancel", response_class=HTMLResponse)
def cancel_post(
    request: Request,
    db: Session = Depends(get_db),
    code: str = Form(...),
    fio: str = Form(...),
):
    row = bsvc.find_booking(db, code=code)
    if not row or row.fio.lower() != " ".join(fio.split()).lower():
        return _page(request, "booking/cancel.html", db=db, error="Запись не найдена. Проверьте код и ФИО.", ok="")
    try:
        bsvc.cancel_booking(db, row, reason="student")
        return _page(request, "booking/cancel.html", db=db, error="", ok="Запись отменена. Слот снова свободен.")
    except ValueError as exc:
        return _page(request, "booking/cancel.html", db=db, error=str(exc), ok="")
