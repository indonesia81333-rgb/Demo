from __future__ import annotations

import asyncio
import hmac
import html
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Callable

from aiohttp import web

from database import UploadDatabase
from state import BotState, human_size

TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html"
SERVICE_NAME = "filepress-telegram-bot"


def _iso(ts: float | None) -> str:
    if ts is None:
        return "never"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


async def build_snapshot(
    state: BotState,
    db: UploadDatabase,
    route_label: Callable[[], str],
    max_file_size: int,
) -> dict[str, Any]:
    stats = await asyncio.to_thread(db.stats)
    online = state.connected
    display = {
        "status": "Online" if online else "Connecting…",
        "uptime": state.uptime,
        "started": _iso(state.started_at),
        "username": f"@{state.username}" if state.username else "-",
        "route": route_label(),
        "limit": human_size(max_file_size),
        "active": str(state.active_uploads),
        "total": str(stats["total"]),
        "last_24h": str(stats["last_24h"]),
        "bytes": human_size(stats["total_bytes"]),
        "users": str(stats["users"]),
        "ok": str(state.uploads_ok),
        "failed": str(state.uploads_failed),
        "last_upload": _iso(state.last_upload_at),
    }
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "online": online,
        "uptime_seconds": int(state.uptime_seconds),
        "stats": stats,
        "display": display,
    }


def build_web_app(
    state: BotState,
    db: UploadDatabase,
    route_label: Callable[[], str],
    max_file_size: int,
    token: str = "",
) -> web.Application:
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))

    def authorized(request: web.Request) -> bool:
        if not token:
            return True
        supplied = request.query.get("token") or request.headers.get(
            "X-Dashboard-Token", ""
        )
        return hmac.compare_digest(supplied, token)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": SERVICE_NAME})

    async def api_status(request: web.Request) -> web.Response:
        if not authorized(request):
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
        snap = await build_snapshot(state, db, route_label, max_file_size)
        return web.json_response(snap, headers={"Cache-Control": "no-store"})

    async def index(request: web.Request) -> web.Response:
        if not authorized(request):
            return web.Response(status=401, text="Unauthorized")
        snap = await build_snapshot(state, db, route_label, max_file_size)
        values = {k: html.escape(v) for k, v in snap["display"].items()}
        page = template.safe_substitute(
            status_class="online" if snap["online"] else "",
            **values,
        )
        return web.Response(
            text=page,
            content_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/", index)
    return app
