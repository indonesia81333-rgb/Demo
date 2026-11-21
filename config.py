from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Environment variable {name} must be an integer, got: {raw!r}"
        ) from exc


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    bot_token: str
    filepress_api_key: str
    filepress_api_url: str
    filepress_base_url: str
    gdrive_service_account_file: str
    gdrive_folder_id: str
    download_dir: Path
    database_path: Path
    port: int
    log_level: str
    max_telegram_file_size: int


def load_settings() -> Settings:
    api_id_raw = _required("API_ID")
    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Environment variable API_ID must be an integer, got: {api_id_raw!r}"
        ) from exc

    download_dir = Path(os.getenv("DOWNLOAD_DIR", "downloads").strip() or "downloads")
    database_path = Path(
        os.getenv("DATABASE_PATH", "data/uploads.sqlite3").strip()
        or "data/uploads.sqlite3"
    )

    download_dir.mkdir(parents=True, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        api_id=api_id,
        api_hash=_required("API_HASH"),
        bot_token=_required("BOT_TOKEN"),
        filepress_api_key=_required("FILEPRESS_API_KEY"),
        filepress_api_url=(
            os.getenv("FILEPRESS_API_URL", "").strip()
            or "https://api.filebee.top/api/v1/file/add"
        ),
        filepress_base_url=(
            os.getenv("FILEPRESS_BASE_URL", "").strip() or "https://filepress.live"
        ).rstrip("/"),
        gdrive_service_account_file=(
            os.getenv("GDRIVE_SERVICE_ACCOUNT_FILE", "").strip()
            or "service-account.json"
        ),
        gdrive_folder_id=os.getenv("GDRIVE_FOLDER_ID", "").strip(),
        download_dir=download_dir,
        database_path=database_path,
        port=_int("PORT", 8080),
        log_level=(os.getenv("LOG_LEVEL", "").strip() or "INFO").upper(),
        max_telegram_file_size=_int("TELEGRAM_MAX_FILE_SIZE_BYTES", 2_097_152_000),
    )
