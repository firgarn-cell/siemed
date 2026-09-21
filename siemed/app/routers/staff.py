from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.db import SessionLocal, get_db
from app.deps import current_staff
from app.events import bus
from app.models import AuditLog, Booking, PracticeSession, SessionFile, Slot, StaffUser
from app.security import read_token
from app.modules.storage import free_gb
from app.timeutil import now
from app.settings_store import get_setting
from app.web import templates

router = APIRouter()


@router.get("/session/{sid}", response_class=HTMLResponse)
def session_view(
    sid: int,
    request: Request,
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_staff),
):
    sess = (
        db.query(PracticeSession)
        .options(
            joinedload(PracticeSession.booking).joinedload(Booking.group),
            joinedload(PracticeSession.booking).joinedload(Booking.slot).joinedload(Slot.lesson),
            joinedload(PracticeSession.files),
        )
        .filter(PracticeSession.id == sid)
        .first()
    )
    if not sess:
        return RedirectResponse("/", status_code=303)
    db.add(AuditLog(created_at=now(), actor=user.login, action="view_session", detail=str(sid)))
    db.commit()
    return templates.TemplateResponse(
        request,
        "admin/session.html",
        {
            "user": user,
            "sess": sess,
            "station_name": get_setting(db, "station_name"),
            "free_gb": round(free_gb(), 1),
            "admin_section": False,
        },
    )


@router.get("/media/{file_id}")
def media(file_id: int, db: Session = Depends(get_db), user: StaffUser = Depends(current_staff)):
    f = db.get(SessionFile, file_id)
    if not f or f.missing or not f.path or not Path(f.path).is_file():
        return HTMLResponse("Нет записи", status_code=404)
    return FileResponse(f.path, media_type="video/mp4")


@router.post("/session/{sid}/grade")
def save_grade(
    sid: int,
    db: Session = Depends(get_db),
    user: StaffUser = Depends(current_staff),
    grade: str = Form(""),
    notes: str = Form(""),
):
    sess = db.get(PracticeSession, sid)
    if sess:
        grade = grade.strip()
        if grade not in {"", "2", "3", "4", "5"}:
            grade = ""
        sess.grade = grade
        sess.notes = notes.strip()
        sess.reviewed = bool(grade)
        sess.reviewed_at = now() if grade else None
        sess.reviewed_by = user.login if grade else ""
        db.add(AuditLog(created_at=now(), actor=user.login, action="grade_session", detail=f"{sid}:{grade or '-'}"))
        db.commit()
    return RedirectResponse(f"/session/{sid}", status_code=303)


@router.post("/session/{sid}/reviewed")
def mark_reviewed(sid: int, db: Session = Depends(get_db), user: StaffUser = Depends(current_staff)):
    return RedirectResponse(f"/session/{sid}", status_code=303)


@router.websocket("/ws")
async def staff_ws(ws: WebSocket):
    token = ws.cookies.get("siemed_auth")
    data = read_token(token) if token else None
    if not data:
        await ws.close(code=1008)
        return
    db = SessionLocal()
    try:
        user = db.get(StaffUser, int(data["uid"]))
        if not user or not user.active:
            await ws.close(code=1008)
            return
    finally:
        db.close()
    await ws.accept()
    q = bus.subscribe_ws()
    try:
        while True:
            event = await q.get()
            await ws.send_text(json.dumps(event, ensure_ascii=False, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe_ws(q)
