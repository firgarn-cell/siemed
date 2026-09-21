from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Camera


RECORD_PRACTICE = "practice"
RECORD_OFF = "off"


@dataclass
class CameraStatus:
    key: str
    title: str
    rtsp: str
    alive: bool
    detail: str


def camera_rtsp(cam: Camera) -> str:
    user = (cam.user or settings.nvr_user or "").strip()
    password = (cam.password or settings.nvr_password or "").strip()
    raw = (cam.rtsp or "").strip()
    if not raw:
        ch = cam.key.replace("cam", "") or "1"
        raw = settings.nvr_rtsp_template.format(
            user=user, password=password, host=settings.nvr_host, ch=ch
        )
        return raw
    if "{" in raw:
        ch = cam.key.replace("cam", "") or "1"
        return raw.format(user=user, password=password, host=settings.nvr_host, ch=ch)
    parts = urlsplit(raw)
    scheme = parts.scheme or "rtsp"
    netloc = parts.netloc
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[-1]
    if user:
        netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{netloc}"
    return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))


def recording_cameras(db: Session) -> list[Camera]:
    rows = (
        db.query(Camera)
        .filter(Camera.enabled.is_(True))
        .order_by(Camera.sort, Camera.id)
        .all()
    )
    return [c for c in rows if (c.record_mode or RECORD_PRACTICE) == RECORD_PRACTICE]


def probe(rtsp: str, timeout: int = 8) -> tuple[bool, str]:
    ffprobe = shutil.which(settings.ffprobe_bin) or settings.ffprobe_bin
    if not shutil.which(settings.ffprobe_bin) and not shutil.which("ffprobe"):
        return False, "ffprobe не найден"
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "5000000",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        rtsp,
    ]
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, str(exc)
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "нет потока").strip().splitlines()
        return False, (err[-1] if err else "камера недоступна")
    text = (res.stdout or "").lower()
    if "video" not in text:
        return False, "нет видеопотока"
    return True, "ok" + ("+audio" if "audio" in text else "")


def check_all(db: Session) -> list[CameraStatus]:
    out: list[CameraStatus] = []
    cams = (
        db.query(Camera)
        .filter(Camera.enabled.is_(True))
        .order_by(Camera.sort, Camera.id)
        .all()
    )
    for cam in cams:
        url = camera_rtsp(cam)
        ok, detail = probe(url)
        out.append(
            CameraStatus(key=cam.key, title=cam.title, rtsp=url, alive=ok, detail=detail)
        )
    return out


def all_alive(statuses: list[CameraStatus]) -> bool:
    return bool(statuses) and all(s.alive for s in statuses) and len(statuses) >= 3
