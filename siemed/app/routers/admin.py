from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.db import get_db
from app.deps import current_admin, current_staff
from app.models import (
    AuditLog,
    Booking,
    Camera,
    Group,
    Lesson,
    PracticeSession,
    Slot,
    StaffUser,
)
from app.modules.cameras import check_all
from app.modules.player import player
from app.modules.storage import free_gb
from app.security import hash_password
from app.timeutil import now
from app.services import booking as bsvc
from app.settings_store import get_int, get_setting, set_setting
from app.timeutil import as_local, now, tz
from app.web import templates

router = APIRouter()

_ADMIN_PATHS = (
    "/administration",
    "/lessons",
    "/groups",
    "/slots",
    "/cameras",
    "/users",
    "/settings",
    "/log",
    "/archive",
    "/bookings",
    "/player-test",
)


def _admin_section(request: Request) -> bool:
    path = request.url.path
    return any(path == p or path.startswith(p + "/") for p in _ADMIN_PATHS)


def _ctx(request: Request, db: Session, user: StaffUser, **extra):
    return {
        "user": user,
        "station_name": get_setting(db, "station_name"),
        "free_gb": round(free_gb(), 1),
        "admin_section": extra.pop("admin_section", _admin_section(request)),
        **extra,
    }


def _session_query(db: Session):
    return db.query(PracticeSession).options(
        joinedload(PracticeSession.booking).joinedload(Booking.group),
        joinedload(PracticeSession.booking).joinedload(Booking.slot).joinedload(Slot.lesson),
        joinedload(PracticeSession.files),
    )


@router.get("/", response_class=HTMLResponse)
def results(
    request: Request,
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_staff),
    q: str = "",
):
    rows = _session_query(db).order_by(PracticeSession.id.desc()).limit(200).all()
    if q:
        ql = q.lower()
        rows = [
            r
            for r in rows
            if ql in r.booking.fio.lower() or ql in r.booking.group.name.lower()
        ]
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        _ctx(request, db, user, sessions=rows, q=q, admin_section=False),
    )


@router.get("/administration", response_class=HTMLResponse)
def administration(
    request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)
):
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    slots_today = (
        db.query(Slot)
        .options(joinedload(Slot.lesson), joinedload(Slot.bookings))
        .filter(Slot.starts_at >= today, Slot.starts_at < today + timedelta(days=1))
        .order_by(Slot.starts_at)
        .all()
    )
    cams = check_all(db)
    return templates.TemplateResponse(
        request,
        "admin/administration.html",
        _ctx(
            request,
            db,
            user,
            slots_today=slots_today,
            cams=cams,
            lessons_n=db.query(Lesson).count(),
            groups_n=db.query(Group).filter(Group.hidden.is_(False)).count(),
            sessions_n=db.query(PracticeSession).count(),
            admin_section=True,
        ),
    )


@router.get("/lessons", response_class=HTMLResponse)
def lessons(request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    rows = db.query(Lesson).order_by(Lesson.title).all()
    return templates.TemplateResponse(request, "admin/lessons.html", _ctx(request, db, user, lessons=rows, error=""))


@router.post("/lessons")
async def lesson_save(
    request: Request,
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_admin),
    lesson_id: int = Form(0),
    code: str = Form(""),
    title: str = Form(...),
    description: str = Form(""),
    practice_limit_min: int = Form(15),
    slot_minutes: int = Form(30),
    published: str = Form(""),
    video: UploadFile | None = File(None),
):
    row = db.get(Lesson, lesson_id) if lesson_id else Lesson(code=code or f"NSG-{uuid.uuid4().hex[:6].upper()}")
    if not lesson_id:
        db.add(row)
    row.title = title.strip()
    row.description = description.strip()
    row.practice_limit_min = practice_limit_min
    row.slot_minutes = slot_minutes
    row.published = published == "1"
    if video and video.filename:
        settings.lessons_dir.mkdir(parents=True, exist_ok=True)
        ext = Path(video.filename).suffix.lower() or ".mp4"
        dest = settings.lessons_dir / f"{row.code}{ext}"
        with dest.open("wb") as fh:
            shutil.copyfileobj(video.file, fh)
        row.video_path = str(dest)
    db.commit()
    return RedirectResponse("/lessons", status_code=303)


@router.get("/groups", response_class=HTMLResponse)
def groups(request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    rows = db.query(Group).order_by(Group.name).all()
    return templates.TemplateResponse(request, "admin/groups.html", _ctx(request, db, user, groups=rows))


@router.post("/groups")
def group_save(
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_admin),
    name: str = Form(...),
    group_id: int = Form(0),
    hidden: str = Form(""),
):
    if group_id:
        row = db.get(Group, group_id)
        if row:
            row.name = name.strip()
            row.hidden = hidden == "1"
    else:
        db.add(Group(name=name.strip(), hidden=False))
    db.commit()
    return RedirectResponse("/groups", status_code=303)


@router.get("/slots", response_class=HTMLResponse)
def slots_page(request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    lessons = db.query(Lesson).filter(Lesson.published.is_(True)).order_by(Lesson.title).all()
    rows = (
        db.query(Slot)
        .options(joinedload(Slot.lesson), joinedload(Slot.bookings).joinedload(Booking.group))
        .filter(Slot.starts_at >= now() - timedelta(days=1))
        .order_by(Slot.starts_at)
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        request, "admin/slots.html", _ctx(request, db, user, lessons=lessons, slots=rows, error="")
    )


@router.post("/slots")
def slots_create(
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_admin),
    lesson_id: int = Form(...),
    date: str = Form(...),
    start_time: str = Form(...),
    count: int = Form(1),
):
    lesson = db.get(Lesson, lesson_id)
    day = datetime.strptime(date, "%Y-%m-%d").date()
    hh, mm = start_time.split(":")
    start = datetime(day.year, day.month, day.day, int(hh), int(mm))
    for i in range(max(1, min(count, 24))):
        s = start + timedelta(minutes=lesson.slot_minutes * i)
        e = s + timedelta(minutes=lesson.slot_minutes)
        overlap = (
            db.query(Slot)
            .filter(Slot.closed.is_(False), Slot.starts_at < e, Slot.ends_at > s)
            .first()
        )
        if overlap:
            continue
        db.add(Slot(lesson_id=lesson.id, starts_at=s, ends_at=e))
    db.commit()
    return RedirectResponse("/slots", status_code=303)


@router.post("/slots/{slot_id}/close")
def slot_close(slot_id: int, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    slot = db.get(Slot, slot_id)
    if slot and not bsvc.active_booking_for_slot(db, slot):
        slot.closed = True
        db.commit()
    return RedirectResponse("/slots", status_code=303)


@router.post("/bookings/{booking_id}/cancel")
def admin_cancel(booking_id: int, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    row = db.get(Booking, booking_id)
    if row:
        bsvc.cancel_booking(db, row, reason="admin")
        db.add(AuditLog(created_at=now(), actor=user.login, action="cancel_booking", detail=row.code))
        db.commit()
    return RedirectResponse("/slots", status_code=303)


@router.get("/cameras", response_class=HTMLResponse)
def cameras_page(request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    cams = db.query(Camera).order_by(Camera.sort).all()
    statuses = {s.key: s for s in check_all(db)}
    return templates.TemplateResponse(
        request, "admin/cameras.html", _ctx(request, db, user, cameras=cams, statuses=statuses)
    )


@router.post("/cameras")
def camera_save(
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_admin),
    cam_id: int = Form(...),
    title: str = Form(...),
    cam_user: str = Form(""),
    cam_password: str = Form(""),
    rtsp: str = Form(...),
    record_mode: str = Form("practice"),
    enabled: str = Form(""),
):
    cam = db.get(Camera, cam_id)
    if cam:
        cam.title = title.strip()
        cam.user = cam_user.strip()
        if cam_password.strip():
            cam.password = cam_password.strip()
        cam.rtsp = rtsp.strip()
        cam.record_mode = record_mode if record_mode in {"practice", "off"} else "practice"
        cam.enabled = enabled == "1"
        db.commit()
    return RedirectResponse("/cameras", status_code=303)


@router.post("/player-test")
def player_test(db: Session = Depends(get_db), user: StaffUser = Depends(current_admin), lesson_id: int = Form(0)):
    lesson = db.get(Lesson, lesson_id) if lesson_id else db.query(Lesson).filter(Lesson.video_path != "").first()
    if lesson and lesson.video_path:
        player.play(lesson.video_path)
    return RedirectResponse("/administration", status_code=303)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    return templates.TemplateResponse(
        request,
        "admin/settings.html",
        _ctx(
            request,
            db,
            user,
            cancel_lead_hours=get_int(db, "cancel_lead_hours", 24),
            slot_grace_minutes=get_int(db, "slot_grace_minutes", 5),
            public_url=get_setting(db, "public_url"),
            station_name=get_setting(db, "station_name"),
        ),
    )


@router.post("/settings")
def settings_save(
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_admin),
    station_name: str = Form(...),
    public_url: str = Form(...),
    cancel_lead_hours: int = Form(...),
    slot_grace_minutes: int = Form(...),
):
    set_setting(db, "station_name", station_name.strip())
    set_setting(db, "public_url", public_url.strip())
    set_setting(db, "cancel_lead_hours", str(cancel_lead_hours))
    set_setting(db, "slot_grace_minutes", str(slot_grace_minutes))
    return RedirectResponse("/settings", status_code=303)


@router.get("/users", response_class=HTMLResponse)
def staff_list(request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    rows = db.query(StaffUser).order_by(StaffUser.login).all()
    return templates.TemplateResponse(request, "admin/staff.html", _ctx(request, db, user, staff=rows, error=""))


@router.post("/users")
def staff_add(
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_admin),
    login: str = Form(...),
    name: str = Form(""),
    password: str = Form(...),
    role: str = Form("staff"),
):
    if db.query(StaffUser).filter(StaffUser.login == login.strip()).first():
        return RedirectResponse("/users", status_code=303)
    db.add(
        StaffUser(
            login=login.strip(),
            name=name.strip(),
            password_hash=hash_password(password),
            role=role if role in {"admin", "staff"} else "staff",
            active=True,
        )
    )
    db.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/users/{uid}/toggle")
def staff_toggle(uid: int, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    row = db.get(StaffUser, uid)
    if row and row.id != user.id:
        row.active = not row.active
        db.commit()
    return RedirectResponse("/users", status_code=303)


@router.get("/archive", response_class=HTMLResponse)
def archive(
    request: Request,
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_admin),
    q: str = "",
):
    query = db.query(PracticeSession).options(
        joinedload(PracticeSession.booking).joinedload(Booking.group),
        joinedload(PracticeSession.booking).joinedload(Booking.slot).joinedload(Slot.lesson),
        joinedload(PracticeSession.files),
    ).order_by(PracticeSession.id.desc())
    rows = query.limit(200).all()
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r.booking.fio.lower() or ql in r.booking.group.name.lower()]
    return templates.TemplateResponse(request, "admin/archive.html", _ctx(request, db, user, sessions=rows, q=q))


@router.post("/archive/{sid}/delete")
def archive_delete(sid: int, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    sess = db.get(PracticeSession, sid)
    if sess:
        for f in sess.files:
            p = Path(f.path) if f.path else None
            if p and p.is_file():
                p.unlink(missing_ok=True)
        db.query(AuditLog).filter(AuditLog.action == "unused").delete()
        db.add(AuditLog(created_at=now(), actor=user.login, action="delete_session", detail=str(sid)))
        db.delete(sess)
        db.commit()
    return RedirectResponse("/archive", status_code=303)


@router.get("/log", response_class=HTMLResponse)
def log_page(request: Request, db: Session = Depends(get_db), user: StaffUser = Depends(current_admin)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(300).all()
    return templates.TemplateResponse(request, "admin/log.html", _ctx(request, db, user, logs=rows))
