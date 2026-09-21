from __future__ import annotations

from urllib.parse import unquote, urlsplit, urlunsplit

from sqlalchemy import inspect, text

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base, Camera, Setting, StaffUser
from app.security import hash_password
from app.settings_store import DEFAULTS


def _migrate_schema() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        if "cameras" in tables:
            cols = {c["name"] for c in insp.get_columns("cameras")}
            if "user" not in cols:
                conn.execute(text("ALTER TABLE cameras ADD COLUMN user VARCHAR(64) DEFAULT ''"))
            if "password" not in cols:
                conn.execute(text("ALTER TABLE cameras ADD COLUMN password VARCHAR(128) DEFAULT ''"))
            if "record_mode" not in cols:
                conn.execute(text("ALTER TABLE cameras ADD COLUMN record_mode VARCHAR(32) DEFAULT 'practice'"))
        if "sessions" in tables:
            cols = {c["name"] for c in insp.get_columns("sessions")}
            if "grade" not in cols:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN grade VARCHAR(8) DEFAULT ''"))


def _credentials_from_rtsp(url: str) -> tuple[str, str, str]:
    parts = urlsplit(url or "")
    netloc = parts.netloc
    user, password = "", ""
    if "@" in netloc:
        cred, netloc = netloc.rsplit("@", 1)
        if ":" in cred:
            user, password = cred.split(":", 1)
        else:
            user = cred
        user, password = unquote(user), unquote(password)
    cleaned = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return user, password, cleaned


def init_db(admin_password: str | None = None) -> str | None:
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    created = None
    db = SessionLocal()
    try:
        if db.query(StaffUser).count() == 0:
            pwd = admin_password or "admin"
            db.add(
                StaffUser(
                    login="admin",
                    name="Администратор",
                    password_hash=hash_password(pwd),
                    role="admin",
                    active=True,
                )
            )
            created = pwd
        if db.query(Camera).count() == 0:
            for i, title in enumerate(
                ("Общий план", "Зона рук", "Прибор / показания"), start=1
            ):
                db.add(
                    Camera(
                        key=f"cam{i}",
                        title=title,
                        user=settings.nvr_user,
                        password=settings.nvr_password,
                        rtsp=f"rtsp://{settings.nvr_host}:554/cam/realmonitor?channel={i}&subtype=0",
                        record_mode="practice",
                        sort=i,
                        enabled=True,
                    )
                )
        for cam in db.query(Camera).all():
            if not (cam.record_mode or "").strip():
                cam.record_mode = "practice"
            if not (cam.user or "").strip() and not (cam.password or "").strip() and cam.rtsp:
                user, password, cleaned = _credentials_from_rtsp(cam.rtsp)
                if user or password:
                    cam.user = user or settings.nvr_user
                    cam.password = password or settings.nvr_password
                    cam.rtsp = cleaned
                else:
                    cam.user = settings.nvr_user
                    cam.password = settings.nvr_password
        for key, value in DEFAULTS.items():
            if db.get(Setting, key) is None:
                db.add(Setting(key=key, value=value))
        db.commit()
    finally:
        db.close()
    return created
