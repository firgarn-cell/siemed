from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from app.config import settings
from app.events import bus


def _linux() -> bool:
    return os.name != "nt"


class Player:
    """Плеер инструктажа: mpv на назначенном HDMI."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._current: str | None = None
        self._ended = False
        self._emitted_for: str | None = None

    @property
    def ready(self) -> bool:
        return _linux() and shutil.which(settings.mpv_bin) is not None

    def ensure(self) -> None:
        if not self.ready:
            return
        ipc = Path(settings.mpv_ipc)
        ipc.parent.mkdir(parents=True, exist_ok=True)
        if self._alive():
            return
        cmd = [
            settings.mpv_bin,
            "--idle=yes",
            "--force-window=yes",
            "--fs=yes",
            f"--fs-screen={settings.mpv_screen}",
            "--keep-open=yes",
            "--no-osc",
            "--no-osd-bar",
            "--cursor-autohide=always",
            f"--input-ipc-server={settings.mpv_ipc}",
            "--really-quiet",
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for _ in range(20):
            if ipc.exists():
                break
            time.sleep(0.1)

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _cmd(self, payload: dict) -> dict | None:
        if not self.ready:
            return None
        self.ensure()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(2)
            sock.connect(settings.mpv_ipc)
            sock.sendall((json.dumps(payload) + "\n").encode())
            try:
                raw = sock.recv(8192).decode(errors="ignore")
                for line in raw.splitlines():
                    if line.strip():
                        return json.loads(line)
            except Exception:
                return None
        except OSError:
            return None
        finally:
            sock.close()
        return None

    def play(self, path: str) -> bool:
        self._ended = False
        self._emitted_for = None
        self._current = path
        if not self.ready:
            return Path(path).is_file()
        self.ensure()
        self._cmd({"command": ["loadfile", path, "replace"]})
        self._cmd({"command": ["set_property", "pause", False]})
        return True

    def replay(self) -> bool:
        if not self._current:
            return False
        return self.play(self._current)

    def stop(self) -> None:
        self._current = None
        self._ended = False
        if not self.ready:
            return
        self._cmd({"command": ["stop"]})
        splash = settings.splash_path
        if splash.is_file():
            self._cmd({"command": ["loadfile", str(splash), "replace"]})

    def is_ended(self) -> bool:
        if self._ended:
            return True
        if not self.ready:
            return False
        res = self._cmd({"command": ["get_property", "eof-reached"]})
        if res and res.get("data") is True:
            self._ended = True
            return True
        return False


player = Player()


async def poll_player_end() -> None:
    while True:
        try:
            if player._current and player.is_ended() and player._emitted_for != player._current:
                player._emitted_for = player._current
                await bus.emit("instruction_finished", {"path": player._current})
        except Exception:
            pass
        await asyncio.sleep(0.5)
