from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Callable

import aiohttp


class FilePressError(Exception):
    """Raised when the FilePress API request fails or returns an unusable response."""


ID_KEYS = ("_id", "file_id", "id")
URL_KEYS = ("url", "link", "file_url", "download_url")


def _find_filepress_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    candidates = [data] if isinstance(data, dict) else []
    candidates.append(payload)
    for source in candidates:
        for key in ID_KEYS:
            value = source.get(key)
            if value:
                return str(value)
    return None


def _find_url(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    candidates = [data] if isinstance(data, dict) else []
    candidates.append(payload)
    for source in candidates:
        for key in URL_KEYS:
            value = source.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
    return None


class _ProgressFile(io.BufferedReader):
    """File reader that reports bytes read; aiohttp reads it from a worker thread."""

    def __init__(
        self, path: Path, callback: Callable[[float], None] | None
    ) -> None:
        super().__init__(io.FileIO(path, "rb"), buffer_size=1024 * 1024)
        self._total = os.fstat(self.fileno()).st_size
        self._sent = 0
        self._callback = callback

    def read(self, size: int | None = -1) -> bytes:
        chunk = super().read(size)
        if chunk and self._callback and self._total:
            self._sent += len(chunk)
            self._callback(min(self._sent / self._total, 1.0))
        return chunk


class FilePressClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        base_url: str,
        upload_url: str = "",
        upload_file_field: str = "file",
        upload_auth: str = "body",
        upload_key_field: str = "key",
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.upload_url = upload_url
        self.upload_file_field = upload_file_field
        self.upload_auth = upload_auth
        self.upload_key_field = upload_key_field

    @property
    def direct_upload_enabled(self) -> bool:
        return bool(self.upload_url)

    def _parse(self, status: int, text: str) -> tuple[str, str | None, dict[str, Any]]:
        if status not in (200, 201, 202):
            raise FilePressError(f"FilePress API returned HTTP {status}: {text[:500]}")

        try:
            payload: Any = json.loads(text)
        except json.JSONDecodeError:
            payload = {}

        if isinstance(payload, dict):
            message = str(payload.get("message", ""))
            if payload.get("success") is False or "file not found" in message.lower():
                detail = message or text[:500]
                raise FilePressError(f"FilePress rejected the file: {detail}")

        filepress_id = _find_filepress_id(payload)
        share_url = _find_url(payload)

        if not share_url and filepress_id:
            share_url = f"{self.base_url}/file/{filepress_id}"
        if not share_url:
            raise FilePressError(
                f"FilePress response did not contain a link or file ID: {text[:500]}"
            )

        raw = payload if isinstance(payload, dict) else {"raw": text}
        return share_url, filepress_id, raw

    async def publish_drive_file(
        self, drive_file_id: str
    ) -> tuple[str, str | None, dict[str, Any]]:
        body = {"key": self.api_key, "id": drive_file_id}
        timeout = aiohttp.ClientTimeout(total=90)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.api_url, json=body) as response:
                    text = await response.text()
                    status = response.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise FilePressError(
                f"Could not reach the FilePress API ({exc.__class__.__name__}: {exc}). "
                "The FILEPRESS_API_URL may have changed; check your configuration."
            ) from exc
        return self._parse(status, text)

    async def upload_file(
        self,
        file_path: str | Path,
        file_name: str,
        progress_callback: Callable[[float], None] | None = None,
    ) -> tuple[str, str | None, dict[str, Any]]:
        """Upload a local file straight to FilePress (multipart/form-data).

        progress_callback is invoked from a worker thread.
        """
        if not self.upload_url:
            raise FilePressError(
                "Direct upload is not configured. Set FILEPRESS_UPLOAD_URL."
            )

        headers: dict[str, str] = {}
        form = aiohttp.FormData()
        if self.upload_auth == "body":
            form.add_field(self.upload_key_field, self.api_key)
        elif self.upload_auth == "bearer":
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            headers[self.upload_key_field] = self.api_key

        reader = _ProgressFile(Path(file_path), progress_callback)
        form.add_field(
            self.upload_file_field,
            reader,
            filename=file_name,
            content_type="application/octet-stream",
        )

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=900)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.upload_url, data=form, headers=headers
                ) as response:
                    text = await response.text()
                    status = response.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise FilePressError(
                f"Direct upload to FilePress failed ({exc.__class__.__name__}: {exc}). "
                "The FILEPRESS_UPLOAD_URL may have changed; check your configuration."
            ) from exc
        finally:
            reader.close()
        return self._parse(status, text)
