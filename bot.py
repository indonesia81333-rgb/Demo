from __future__ import annotations

import asyncio
import html
import logging
import mimetypes
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.enums import ParseMode
from pyrogram.handlers import MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import load_settings
from database import UploadDatabase
from services.filepress import FilePressClient, FilePressError
from services.google_drive import GoogleDriveError, get_file_metadata, upload_file

settings = load_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("filepress_bot")

db = UploadDatabase(settings.database_path)
filepress = FilePressClient(
    api_url=settings.filepress_api_url,
    api_key=settings.filepress_api_key,
    base_url=settings.filepress_base_url,
)

PROGRESS_INTERVAL_SECONDS = 2.0
BAR_BLOCKS = 12
DRIVE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")

MEDIA_FILTER = (
    filters.document
    | filters.video
    | filters.audio
    | filters.photo
    | filters.animation
    | filters.voice
    | filters.video_note
    | filters.sticker
)


def human_size(size: float) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def progress_bar(fraction: float) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(fraction * BAR_BLOCKS)
    return "█" * filled + "░" * (BAR_BLOCKS - filled)


def get_media_details(message: Message) -> tuple[str, int]:
    media: Any = None
    for attr in (
        "document",
        "video",
        "audio",
        "animation",
        "voice",
        "video_note",
        "sticker",
        "photo",
    ):
        media = getattr(message, attr, None)
        if media:
            break
    if not media:
        raise ValueError("No supported media was found in that message.")

    name = getattr(media, "file_name", None)
    if not name:
        mime_type = getattr(media, "mime_type", None)
        ext = mimetypes.guess_extension(mime_type) if mime_type else None
        if not ext:
            ext = ".jpg" if message.photo else ".bin"
        name = f"telegram_file_{message.id}{ext}"

    name = Path(name).name.replace("\x00", "")[:240]
    if not name:
        name = f"telegram_file_{message.id}.bin"
    return name, int(getattr(media, "file_size", 0) or 0)


async def edit_status(
    status_message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    try:
        await status_message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
    except Exception as exc:
        logger.debug("Could not edit status message: %s", exc)


def share_markup(link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Open / Download", url=link)]])


def make_download_progress(status_message: Message, file_name: str):
    last_update = 0.0

    async def download_progress(current: int, total: int) -> None:
        nonlocal last_update
        now = time.monotonic()
        done = bool(total) and current >= total
        if not done and now - last_update < PROGRESS_INTERVAL_SECONDS:
            return
        last_update = now
        fraction = current / total if total else 0.0
        await edit_status(
            status_message,
            f"⬇️ <b>Downloading from Telegram</b>\n"
            f"<code>{html.escape(file_name)}</code>\n\n"
            f"{progress_bar(fraction)} {fraction * 100:.1f}%\n"
            f"{human_size(current)} / {human_size(total)}",
        )

    return download_progress


async def drive_progress_callback(
    status_message: Message, file_name: str, fraction: float
) -> None:
    await edit_status(
        status_message,
        f"☁️ <b>Uploading to Google Drive</b>\n"
        f"<code>{html.escape(file_name)}</code>\n\n"
        f"{progress_bar(fraction)} {fraction * 100:.1f}%",
    )


async def publish_drive_id(
    user_id: int, drive_file_id: str, file_name: str, file_size: int
) -> tuple[str, str | None]:
    link, filepress_id, _raw = await filepress.publish_drive_file(drive_file_id)
    db.add_upload(
        user_id=user_id,
        file_name=file_name,
        file_size=file_size,
        drive_file_id=drive_file_id,
        filepress_id=filepress_id,
        share_url=link,
    )
    return link, filepress_id


def service_account_exists() -> bool:
    return Path(settings.gdrive_service_account_file).is_file()


def extract_drive_id(argument: str) -> str | None:
    argument = argument.strip()
    match = re.search(r"/d/([A-Za-z0-9_-]+)", argument)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", argument)
    if match:
        return match.group(1)
    if DRIVE_ID_PATTERN.match(argument):
        return argument
    return None


HELP_TEXT = (
    "👋 <b>FilePress Uploader</b>\n\n"
    "Send me a file (document, video, audio, photo, GIF, voice note, video note "
    "or sticker) and I'll upload it to Google Drive and give you a public "
    "FilePress share link.\n\n"
    "<b>Commands</b>\n"
    "/start, /help - show this message\n"
    "/status - bot status and file size limit\n"
    "/myuploads - your latest 10 links\n"
    "/publish_drive &lt;file id or URL&gt; - publish a file that is already on "
    "Google Drive (useful for files above the Telegram limit)"
)


async def start_handler(client: Client, message: Message) -> None:
    await message.reply_text(
        HELP_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def status_handler(client: Client, message: Message) -> None:
    await message.reply_text(
        "✅ <b>Bot is running.</b>\n"
        f"Telegram file limit: <b>{human_size(settings.max_telegram_file_size)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def myuploads_handler(client: Client, message: Message) -> None:
    uploads = await asyncio.to_thread(db.list_uploads, message.from_user.id, 10)
    if not uploads:
        await message.reply_text("You have no published uploads yet.")
        return
    lines = ["📁 <b>Your latest uploads</b>\n"]
    for item in uploads:
        lines.append(
            f"• <a href=\"{html.escape(item['share_url'], quote=True)}\">"
            f"{html.escape(item['file_name'])}</a> ({human_size(item['file_size'])})"
        )
    await message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def publish_drive_handler(client: Client, message: Message) -> None:
    if len(message.command) < 2:
        await message.reply_text(
            "Usage: /publish_drive DRIVE_FILE_ID_OR_URL\n"
            "Example: /publish_drive https://drive.google.com/file/d/FILE_ID/view"
        )
        return

    drive_file_id = extract_drive_id(" ".join(message.command[1:]))
    if not drive_file_id:
        await message.reply_text(
            "That doesn't look like a Google Drive file ID or URL."
        )
        return

    if not service_account_exists():
        await message.reply_text(
            "Google Drive is not configured on this bot "
            "(service-account file is missing)."
        )
        return

    status_message = await message.reply_text("Looking up the Drive file…")
    try:
        metadata = await asyncio.to_thread(
            get_file_metadata, drive_file_id, settings.gdrive_service_account_file
        )
        file_name = metadata.get("name", drive_file_id)
        file_size = int(metadata.get("size") or 0)
        link, _ = await publish_drive_id(
            message.from_user.id, drive_file_id, file_name, file_size
        )
        await edit_status(
            status_message,
            "✅ <b>Published</b>\n\n"
            f"<b>File:</b> {html.escape(file_name)}\n"
            f"<b>Size:</b> {human_size(file_size)}\n\n"
            f"<b>Link:</b> <a href=\"{html.escape(link, quote=True)}\">"
            f"{html.escape(link)}</a>",
            share_markup(link),
        )
    except GoogleDriveError as exc:
        await edit_status(
            status_message, f"Google Drive error\n{html.escape(str(exc))}"
        )
    except FilePressError as exc:
        await edit_status(status_message, f"FilePress error\n{html.escape(str(exc))}")
    except Exception as exc:
        logger.exception("Unexpected error in /publish_drive")
        await edit_status(
            status_message, f"Unexpected error\n{html.escape(str(exc)[:500])}"
        )


async def media_handler(client: Client, message: Message) -> None:
    try:
        file_name, file_size = get_media_details(message)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return

    limit = settings.max_telegram_file_size
    if file_size > limit:
        await message.reply_text(
            f"❌ This file is {human_size(file_size)}, which is above the bot's "
            f"limit of {human_size(limit)}.\n\n"
            "Upload it directly to Google Drive (shared with the service account) "
            "and then use /publish_drive DRIVE_FILE_ID_OR_URL."
        )
        return

    if not service_account_exists():
        await message.reply_text(
            "Google Drive is not configured on this bot "
            "(service-account file is missing)."
        )
        return

    status_message = await message.reply_text("Preparing upload ...")
    loop = asyncio.get_running_loop()
    temp_path: Path | None = None

    try:
        suffix = Path(file_name).suffix
        with tempfile.NamedTemporaryFile(
            dir=settings.download_dir, delete=False, suffix=suffix
        ) as tmp:
            temp_path = Path(tmp.name)

        downloaded = await client.download_media(
            message,
            file_name=str(temp_path),
            progress=make_download_progress(status_message, file_name),
        )
        if not downloaded or not temp_path.exists():
            raise RuntimeError("Telegram download failed: no file was saved.")
        actual_size = temp_path.stat().st_size
        if actual_size <= 0:
            raise RuntimeError("Telegram download failed: the file is empty.")
        if actual_size > limit:
            raise RuntimeError(
                f"Downloaded file is {human_size(actual_size)}, above the "
                f"{human_size(limit)} limit."
            )

        await edit_status(
            status_message,
            "Telegram download complete. Starting resumable Google Drive upload…",
        )

        last_drive_update = 0.0

        def drive_progress(fraction: float) -> None:
            nonlocal last_drive_update
            now = time.monotonic()
            if fraction < 1.0 and now - last_drive_update < PROGRESS_INTERVAL_SECONDS:
                return
            last_drive_update = now
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    drive_progress_callback(status_message, file_name, fraction)
                )
            )

        metadata = await asyncio.to_thread(
            upload_file,
            temp_path,
            file_name,
            settings.gdrive_service_account_file,
            settings.gdrive_folder_id,
            drive_progress,
        )
        drive_file_id = metadata["id"]
        uploaded_size = int(metadata.get("size") or actual_size)

        await edit_status(
            status_message,
            "Google Drive upload complete. Publishing share link through FilePress…",
        )

        link, _ = await publish_drive_id(
            message.from_user.id, drive_file_id, file_name, uploaded_size
        )
        await edit_status(
            status_message,
            "✅ <b>Upload complete</b>\n\n"
            f"<b>File:</b> {html.escape(file_name)}\n"
            f"<b>Size:</b> {human_size(uploaded_size)}\n"
            "<b>Storage:</b> Google Drive → FilePress\n\n"
            f"<b>Link:</b> <a href=\"{html.escape(link, quote=True)}\">"
            f"{html.escape(link)}</a>",
            share_markup(link),
        )
    except (GoogleDriveError, FilePressError) as exc:
        logger.warning("Upload failed for user %s: %s", message.from_user.id, exc)
        await edit_status(status_message, f"Upload failed\n{html.escape(str(exc))}")
    except Exception as exc:
        logger.exception("Unexpected error while handling media")
        await edit_status(
            status_message, f"Upload failed\n{html.escape(str(exc)[:500])}"
        )
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as exc:
                logger.warning("Could not delete temp file %s: %s", temp_path, exc)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "filepress-telegram-bot"})


def build_client() -> Client:
    app = Client(
        "filepress_telegram_bot",
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        bot_token=settings.bot_token,
        workers=16,
        sleep_threshold=60,
        max_concurrent_transmissions=2,
    )
    private = filters.private
    app.add_handler(
        MessageHandler(start_handler, filters.command(["start", "help"]) & private)
    )
    app.add_handler(MessageHandler(status_handler, filters.command("status") & private))
    app.add_handler(
        MessageHandler(myuploads_handler, filters.command("myuploads") & private)
    )
    app.add_handler(
        MessageHandler(
            publish_drive_handler, filters.command("publish_drive") & private
        )
    )
    app.add_handler(MessageHandler(media_handler, private & MEDIA_FILTER))
    return app


async def main() -> None:
    web_app = web.Application()
    web_app.router.add_get("/health", health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.port)
    await site.start()
    logger.info("Health check listening on port %s", settings.port)

    app = build_client()
    try:
        await app.start()
        me = await app.get_me()
        logger.info("Bot started as @%s (id=%s)", me.username, me.id)
        await idle()
    finally:
        try:
            await app.stop()
        except Exception as exc:
            logger.debug("Error while stopping client: %s", exc)
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down")
