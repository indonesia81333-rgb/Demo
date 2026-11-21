from __future__ import annotations

import time
from dataclasses import dataclass, field


def human_size(size: float) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def format_uptime(seconds: float) -> str:
    total = max(0, int(seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


@dataclass
class BotState:
    """In-memory runtime status shown by /status and the dashboard."""

    started_at: float = field(default_factory=time.time)
    _started_monotonic: float = field(default_factory=time.monotonic)
    connected: bool = False
    username: str = ""
    uploads_ok: int = 0
    uploads_failed: int = 0
    active_uploads: int = 0
    last_upload_at: float | None = None

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._started_monotonic

    @property
    def uptime(self) -> str:
        return format_uptime(self.uptime_seconds)
