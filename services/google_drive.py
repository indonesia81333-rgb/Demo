from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
CHUNK_SIZE = 8 * 1024 * 1024


class GoogleDriveError(Exception):
    """Raised for Google Drive configuration or API failures."""


def _build_service(credentials_file: str):
    path = Path(credentials_file)
    if not path.is_file():
        raise GoogleDriveError(
            f"Google service-account file not found: {credentials_file}"
        )
    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(path), scopes=SCOPES
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except Exception as exc:  # invalid JSON, bad key, etc.
        raise GoogleDriveError(
            f"Could not load Google service-account credentials: {exc}"
        ) from exc


def _http_detail(exc: HttpError) -> str:
    try:
        return exc.error_details[0]["message"]  # type: ignore[index]
    except Exception:
        return str(exc)


def upload_file(
    file_path: str | Path,
    file_name: str,
    credentials_file: str,
    folder_id: str = "",
    progress_callback: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    drive = _build_service(credentials_file)
    metadata: dict[str, Any] = {"name": file_name}
    if folder_id:
        metadata["parents"] = [folder_id]

    try:
        media = MediaFileUpload(
            str(file_path), resumable=True, chunksize=CHUNK_SIZE
        )
        request = drive.files().create(
            body=metadata,
            media_body=media,
            supportsAllDrives=True,
            fields="id,name,size,webViewLink",
        )
        response = None
        while response is None:
            status, response = request.next_chunk(num_retries=5)
            if status and progress_callback:
                progress_callback(status.progress())
        if progress_callback:
            progress_callback(1.0)

        file_id = response["id"]
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute(num_retries=5)

        return (
            drive.files()
            .get(
                fileId=file_id,
                fields="id,name,size,webViewLink",
                supportsAllDrives=True,
            )
            .execute(num_retries=5)
        )
    except HttpError as exc:
        raise GoogleDriveError(f"Google Drive API error: {_http_detail(exc)}") from exc
    except OSError as exc:
        raise GoogleDriveError(f"Could not read the local file: {exc}") from exc


def get_file_metadata(file_id: str, credentials_file: str) -> dict[str, Any]:
    drive = _build_service(credentials_file)
    try:
        return (
            drive.files()
            .get(
                fileId=file_id,
                fields="id,name,size,webViewLink,mimeType",
                supportsAllDrives=True,
            )
            .execute(num_retries=5)
        )
    except HttpError as exc:
        raise GoogleDriveError(f"Google Drive API error: {_http_detail(exc)}") from exc
