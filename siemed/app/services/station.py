from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.events import bus
from app.models import AuditLog, PracticeSession, SessionFile
from app.modules.cameras import check_all, recording_cameras
from app.modules.player import player
from app.modules.recorder import file_checksum, recorder
from app.modules.storage import disk_ok, free_gb
from app.services import booking as booking_svc
from app.timeutil import as_local, now


def slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9а-яё]+", "_", text, flags=re.I)
    return text.strip("_")[:40] or "student"


@dataclass
class Runtime:
    booking_id: int | None = None
    session_id: int | None = None
    phase: str = "idle"  # idle|instruction|choice|practice
    instruction_ended: bool = False
    demo_no_player: bool = False


runtime = Runtime()


def current_session(db: Session) -> PracticeSession | None:
    if not runtime.session_id:
        return None
    return db.get(PracticeSession, runtime.session_id)


def identify(db: Session, code: str = "", group_id: int | None = None, fio: str = "") -> PracticeSession:
    if not disk_ok():
        raise ValueError("На диске станции мало места. Вызовите администратора.")
    b = booking_svc.find_booking(db, code=code or None, group_id=group_id, fio=fio or None)
    if not b:
        raise ValueError("Нет записи с такими данными")
    if not booking_svc.booking_in_grace(db, b):
        raise ValueError("Нет записи на это время. Запишитесь на сайте или обратитесь к администратору.")
    existing = (
        db.query(PracticeSession)
        .filter(PracticeSession.booking_id == b.id)
        .order_by(PracticeSession.id.desc())
        .first()
    )
    if existing and existing.status in {"completed", "timeout", "instruction_only"}:
        raise ValueError("Это занятие уже завершено")
    if existing and existing.status == "practice" and runtime.session_id == existing.id:
        return existing
    sess = existing or PracticeSession(
        booking_id=b.id,
        status="instruction",
        instruction_started_at=now(),
    )
    if existing is None:
        db.add(sess)
        db.commit()
        db.refresh(sess)
    runtime.booking_id = b.id
    runtime.session_id = sess.id
    runtime.phase = "instruction"
    runtime.instruction_ended = False
    video = b.slot.lesson.video_path
    if not video or not Path(video).is_file():
        raise ValueError("У занятия нет обучающего видео. Вызовите администратора.")
    played = player.play(video)
    runtime.demo_no_player = not player.ready
    if not played and player.ready:
        raise ValueError("Не удалось запустить видео на телевизоре")
    return sess


def mark_instruction_finished() -> None:
    if runtime.phase == "instruction":
        runtime.instruction_ended = True
        runtime.phase = "choice"


def replay() -> None:
    if runtime.phase not in {"choice", "instruction"}:
        raise ValueError("Сейчас нельзя повторить видео")
    if not player.replay():
        raise ValueError("Нет ролика для повтора")
    runtime.phase = "instruction"
    runtime.instruction_ended = False


def walk_away(db: Session) -> None:
    sess = current_session(db)
    if not sess:
        return
    player.stop()
    sess.status = "instruction_only"
    sess.ended_at = now()
    db.commit()
    runtime.phase = "idle"
    runtime.session_id = None
    runtime.booking_id = None
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            bus.emit(
                "session_saved",
                {"session_id": sess.id, "status": sess.status},
            )
        )
    except RuntimeError:
        pass


def start_practice(db: Session) -> None:
    if runtime.phase != "choice" and not runtime.instruction_ended:
        raise ValueError("Сначала досмотрите инструктаж")
    if not disk_ok():
        raise ValueError("На диске мало места. Вызовите администратора.")
    statuses = check_all(db)
    cams = recording_cameras(db)
    if len(cams) < 3:
        raise ValueError("Нужны три камеры в режиме записи практики. Вызовите администратора.")
    rec_keys = {c.key for c in cams}
    dead = [s for s in statuses if s.key in rec_keys and not s.alive]
    if dead:
        names = ", ".join(f"«{s.title}»" for s in dead)
        raise ValueError(f"Камера недоступна: {names}. Вызовите администратора.")
    sess = current_session(db)
    if not sess:
        raise ValueError("Сессия потеряна, войдите снова")
    booking = sess.booking
    day = now().strftime("%Y%m%d_%H%M%S")
    folder = settings.archive_dir / day / f"{slug(booking.group.name)}_{slug(booking.fio)}_{booking.code}"
    recorder.start(sess.id, folder, cams)
    sess.status = "practice"
    sess.started_at = now()
    db.commit()
    runtime.phase = "practice"
    player.stop()


def finish_practice(db: Session, timeout: bool = False) -> PracticeSession:
    sess = current_session(db)
    if not sess:
        raise ValueError("Нет активной практики")
    files = recorder.stop()
    sess.ended_at = now()
    sess.status = "timeout" if timeout else "completed"
    booking = sess.booking
    db.query(SessionFile).filter(SessionFile.session_id == sess.id).delete()
    cams = recording_cameras(db)
    for cam in cams:
        path = files.get(cam.key)
        missing = path is None or not path.is_file() or path.stat().st_size < 1024
        row = SessionFile(
            session_id=sess.id,
            camera_key=cam.key,
            camera_title=cam.title,
            path="" if missing else str(path),
            size=0 if missing else path.stat().st_size,
            checksum="" if missing else file_checksum(path),
            has_audio=not missing,
            missing=missing,
        )
        db.add(row)
    db.add(
        AuditLog(
            created_at=now(),
            actor=booking.fio,
            action="session_complete",
            detail=f"{sess.status} {booking.code}",
        )
    )
    db.commit()
    db.refresh(sess)
    runtime.phase = "idle"
    runtime.session_id = None
    runtime.booking_id = None
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            bus.emit(
                "session_saved",
                {
                    "session_id": sess.id,
                    "status": sess.status,
                    "fio": booking.fio,
                    "group": booking.group.name,
                    "lesson": booking.slot.lesson.title,
                },
            )
        )
    except RuntimeError:
        pass
    return sess


def maybe_timeout(db: Session) -> None:
    if runtime.phase != "practice" or not runtime.session_id:
        return
    sess = db.get(PracticeSession, runtime.session_id)
    if not sess or not sess.started_at:
        return
    limit = sess.booking.slot.lesson.practice_limit_min
    started = as_local(sess.started_at)
    if now() >= started + timedelta(minutes=limit):
        finish_practice(db, timeout=True)
