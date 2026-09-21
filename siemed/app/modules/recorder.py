from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
from pathlib import Path

from app.config import settings
from app.modules.cameras import CameraStatus, camera_rtsp
from app.models import Camera


class Recorder:
    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}
        self._files: dict[str, Path] = {}
        self._session_id: int | None = None

    @property
    def running(self) -> bool:
        return bool(self._procs)

    def start(self, session_id: int, dest_dir: Path, cameras: list[Camera]) -> list[Path]:
        self.stop()
        dest_dir.mkdir(parents=True, exist_ok=True)
        self._session_id = session_id
        ffmpeg = shutil.which(settings.ffmpeg_bin) or settings.ffmpeg_bin
        paths: list[Path] = []
        for cam in cameras:
            out = dest_dir / f"cam_{cam.key}.mp4"
            url = camera_rtsp(cam)
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-rtsp_transport",
                "tcp",
                "-i",
                url,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-y",
                str(out),
            ]
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                continue
            self._procs[cam.key] = proc
            self._files[cam.key] = out
            paths.append(out)
        return paths

    def stop(self) -> dict[str, Path]:
        files = dict(self._files)
        for key, proc in list(self._procs.items()):
            if proc.poll() is None:
                if os.name == "nt":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGINT)
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._procs.clear()
        self._files.clear()
        self._session_id = None
        return files


def file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    if not path.is_file():
        return ""
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


recorder = Recorder()
