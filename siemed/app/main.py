from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.bootstrap import init_db
from app.config import ROOT, settings
from app.events import bus
from app.modules.player import player, poll_player_end
from app.routers import admin, auth, booking, staff, station
from app.services.station import mark_instruction_finished

KINDS = ("booking", "tablet", "office")

_boot_lock = threading.Lock()
_bus_bound = False


def create_app(*, kind: str = "office") -> FastAPI:
    if kind not in KINDS:
        raise ValueError(f"unknown app kind: {kind}")

    titles = {
        "booking": "SIEMED · запись",
        "tablet": "SIEMED · планшет",
        "office": "SIEMED · рабочее место",
    }
    app = FastAPI(title=titles[kind], version=__version__, docs_url=None, redoc_url=None)
    app.state.kind = kind

    static = ROOT / "app" / "static"
    static.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static)), name="static")

    if kind == "booking":
        app.include_router(booking.router)
    elif kind == "tablet":
        app.include_router(station.router)
    else:
        app.include_router(auth.router)
        app.include_router(admin.router)
        app.include_router(staff.router)

        @app.get("/admin", include_in_schema=False)
        def _legacy_admin():
            return RedirectResponse("/administration", status_code=303)

        @app.get("/staff", include_in_schema=False)
        def _legacy_staff():
            return RedirectResponse("/", status_code=303)

        @app.get("/staff/session/{sid}", include_in_schema=False)
        def _legacy_session(sid: int):
            return RedirectResponse(f"/session/{sid}", status_code=303)

    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "kind": kind}

    @app.get("/favicon.ico")
    def favicon():
        ico = static / "favicon.ico"
        if ico.is_file():
            from fastapi.responses import FileResponse

            return FileResponse(ico)
        return JSONResponse({}, status_code=404)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException):
        accept = request.headers.get("accept", "")
        if kind == "office" and exc.status_code in (401, 403) and "text/html" in accept:
            if exc.status_code == 403:
                return RedirectResponse("/", status_code=303)
            return RedirectResponse("/login?next=" + str(request.url.path), status_code=303)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.on_event("startup")
    async def _start():
        global _bus_bound
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with _boot_lock:
            init_db()
            if not _bus_bound:
                bus.on("instruction_finished", lambda p: mark_instruction_finished())
                _bus_bound = True
        if kind == "tablet":
            player.ensure()
            asyncio.create_task(poll_player_end())

    return app


office_app = create_app(kind="office")
tablet_app = create_app(kind="tablet")
booking_app = create_app(kind="booking")
app = office_app
public_app = booking_app
