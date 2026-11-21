from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class UploadDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    drive_file_id TEXT NOT NULL,
                    filepress_id TEXT,
                    share_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_uploads_user_id "
                "ON uploads (user_id, id DESC)"
            )
            conn.commit()

    def add_upload(
        self,
        user_id: int,
        file_name: str,
        file_size: int,
        drive_file_id: str,
        filepress_id: str | None,
        share_url: str,
    ) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                """
                INSERT INTO uploads
                    (user_id, file_name, file_size, drive_file_id, filepress_id, share_url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, file_name, file_size, drive_file_id, filepress_id, share_url),
            )
            conn.commit()

    def stats(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(file_size), 0) AS bytes, "
                "COUNT(DISTINCT user_id) AS users FROM uploads"
            ).fetchone()
            today = conn.execute(
                "SELECT COUNT(*) AS n FROM uploads "
                "WHERE created_at >= datetime('now', '-1 day')"
            ).fetchone()
        return {
            "total": int(total["n"]),
            "total_bytes": int(total["bytes"]),
            "users": int(total["users"]),
            "last_24h": int(today["n"]),
        }

    def list_uploads(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM uploads WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
