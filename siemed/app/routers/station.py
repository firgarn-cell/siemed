from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Group
from app.modules.player import player
from app.services import station as st
from app.settings_store import get_int, get_setting
from app.timeutil import as_local, now
from app.web import templates

router = APIRouter()


def _ctx(request: Request, db: Session, **extra):
    sess = st.current_session(db)
    booking = sess.booking if sess else None
    limit = 15
    remain = None
    if sess and sess.status == "practice" and sess.started_at:
        limit = sess.booking.slot.lesson.practice_limit_min
        elapsed = (now() - as_local(sess.started_at)).total_seconds()
        remain = max(0, int(limit * 60 - elapsed))
    return {
        "station_name": get_setting(db, "station_name"),
        "runtime": st.runtime,
        "session": sess,
        "booking": booking,
        "player_ready": player.ready,
        "remain": remain,
        "grace": get_int(db, "slot_grace_minutes", 5),
        **extra,
    }


@router.get("/", response_class=HTMLResponse)
def tablet(request: Request, db: Session = Depends(get_db)):
    st.maybe_timeout(db)
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    return templates.TemplateResponse(
        request, "station/index.html", _ctx(request, db, groups=groups, error="")
    )


@router.get("/enter")
@router.get("/replay")
@router.get("/leave")
@router.get("/start")
@router.get("/finish")
@router.get("/video-done")
def tablet_post_only_get():
    return RedirectResponse("/", status_code=303)


@router.post("/enter", response_class=HTMLResponse)
def enter(
    request: Request,
    db: Session = Depends(get_db),
    code: str = Form(""),
    group_id: str = Form(""),
    fio: str = Form(""),
):
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    try:
        gid = int(group_id) if group_id else None
        st.identify(db, code=code, group_id=gid, fio=fio)
        return templates.TemplateResponse(request, "station/index.html", _ctx(request, db, groups=groups, error=""))
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "station/index.html", _ctx(request, db, groups=groups, error=str(exc))
        )


@router.post("/replay")
def replay(request: Request, db: Session = Depends(get_db)):
    try:
        st.replay()
    except ValueError as exc:
        groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
        return templates.TemplateResponse(
            request, "station/index.html", _ctx(request, db, groups=groups, error=str(exc))
        )
    return templates.TemplateResponse(request, "station/index.html", _ctx(request, db, groups=[], error=""))


@router.post("/leave")
def leave(request: Request, db: Session = Depends(get_db)):
    st.walk_away(db)
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    return templates.TemplateResponse(request, "station/index.html", _ctx(request, db, groups=groups, error=""))


@router.post("/start")
def start(request: Request, db: Session = Depends(get_db)):
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    try:
        st.start_practice(db)
        return templates.TemplateResponse(request, "station/index.html", _ctx(request, db, groups=groups, error=""))
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "station/index.html", _ctx(request, db, groups=groups, error=str(exc), force_choice=True)
        )


@router.post("/finish")
def finish(request: Request, db: Session = Depends(get_db)):
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    try:
        st.finish_practice(db)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "station/index.html", _ctx(request, db, groups=groups, error=str(exc))
        )
    return templates.TemplateResponse(
        request, "station/index.html", _ctx(request, db, groups=groups, error="", done=True)
    )


@router.post("/video-done")
def video_done(request: Request, db: Session = Depends(get_db)):
    """Для поста без mpv (наладка) или после события eof."""
    st.mark_instruction_finished()
    groups = db.query(Group).filter(Group.hidden.is_(False)).order_by(Group.name).all()
    return templates.TemplateResponse(request, "station/index.html", _ctx(request, db, groups=groups, error=""))


@router.get("/poll")
def poll(db: Session = Depends(get_db)):
    st.maybe_timeout(db)
    if player.is_ended():
        st.mark_instruction_finished()
    return JSONResponse(
        {
            "phase": st.runtime.phase,
            "instruction_ended": st.runtime.instruction_ended,
            "remain": _ctx(None, db).get("remain"),
        }
    )
