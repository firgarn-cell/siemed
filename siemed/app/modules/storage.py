from __future__ import annotations

import shutil
from pathlib import Path

from app.config import settings


def free_gb(path: Path | None = None) -> float:
    target = path or settings.data_dir
    target.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(target)
    return usage.free / (1024**3)


def disk_ok() -> bool:
    return free_gb() >= settings.disk_min_free_gb
