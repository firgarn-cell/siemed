from __future__ import annotations

import asyncio

import uvicorn

from app.config import settings
from app.main import booking_app, office_app, tablet_app


async def run() -> None:
    specs = [
        (office_app, settings.lan_host, settings.lan_port),
        (tablet_app, settings.tablet_host, settings.tablet_port),
        (booking_app, settings.public_host, settings.public_port),
    ]
    seen: set[tuple[str, int]] = set()
    servers: list[uvicorn.Server] = []
    for app, host, port in specs:
        if not port:
            continue
        key = (host, int(port))
        if key in seen:
            continue
        seen.add(key)
        cfg = uvicorn.Config(app, host=host, port=int(port), log_level="info")
        srv = uvicorn.Server(cfg)
        if servers:
            srv.install_signal_handlers = False
        servers.append(srv)
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
