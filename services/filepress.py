from __future__ import annotations

import json
from typing import Any

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


class FilePressClient:
    def __init__(self, api_url: str, api_key: str, base_url: str) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

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
