# FilePress Telegram Uploader

A Telegram bot that accepts media files, uploads them to Google Drive with resumable uploads, and registers each Drive file with the FilePress API to produce a public share link.

```
Telegram user ──► Bot (Pyrofork) ──► Google Drive (resumable, 8 MiB chunks)
                                          │
                                          ▼
                                   FilePress API ──► public share link
```

Upload history is stored in SQLite, and a `GET /health` endpoint is exposed for uptime checks.

## Prerequisites

- Python 3.10+ (Docker image uses 3.11)
- Telegram API credentials (`API_ID`, `API_HASH`) from <https://my.telegram.org>
- A bot token from [@BotFather](https://t.me/BotFather)
- A FilePress API key
- A Google Cloud project with the Google Drive API enabled
- A service-account JSON key
- A Shared Drive (or folder) where the service account has **Content manager** access

## Google Drive setup

1. In Google Cloud Console, create or select a project and enable the **Google Drive API**.
2. Create a **service account** and generate a **JSON key**. Save it as `service-account.json`.
3. Create a Shared Drive (service accounts have no personal storage quota, so a Shared Drive is recommended).
4. Add the service account's email to the Shared Drive as **Content manager**.
5. Optionally copy a folder ID from the Drive URL into `GDRIVE_FOLDER_ID`.
6. For `/publish_drive`, make sure the service account can read the file you want to publish.

## Local install and run

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your credentials
# place service-account.json in the project root
python bot.py
```

Run the smoke tests with:

```bash
python tests/smoke_test.py
```

## Docker

```bash
docker build -t filepress-bot .

docker run -d --name filepress-bot \
  --env-file .env \
  -p 8080:8080 \
  -v "$(pwd)/service-account.json:/app/service-account.json:ro" \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/downloads:/app/downloads" \
  filepress-bot
```

## Deploy on Render

1. Push this project to a Git repository (without `.env` or `service-account.json`).
2. In Render, create a **Background Worker** from the repository, using the Docker runtime (`render.yaml` is included).
3. Add the environment variables from `.env.example` in the Render dashboard.
4. Add a **Secret File** named `service-account.json` with your key contents. Render mounts it at `/etc/secrets/service-account.json`, so set `GDRIVE_SERVICE_ACCOUNT_FILE=/etc/secrets/service-account.json`.
5. Attach a **persistent disk** mounted at `/app/data` so upload history survives deploys.

## Bot commands

| Command | Description |
| --- | --- |
| `/start`, `/help` | Usage instructions |
| `/status` | Bot status and configured Telegram file limit |
| `/myuploads` | Your latest 10 published links |
| `/publish_drive DRIVE_FILE_ID_OR_URL` | Publish an existing Google Drive file (raw ID or a URL containing `/d/<id>`) |

Send any document, video, audio, photo, GIF, voice note, video note, or sticker in a private chat to upload it.

## File size limits

The bot-side Telegram limit defaults to 2,097,152,000 bytes (about 2 GB) and is configurable with `TELEGRAM_MAX_FILE_SIZE_BYTES`. For larger files, upload directly to Google Drive and use `/publish_drive`.

## Security notes

- Never commit `.env` or `service-account.json`.
- Every file uploaded through the bot becomes **publicly readable** on Google Drive.
- Rotate your bot token, FilePress key, and service-account key immediately if they are exposed.

## FilePress endpoints

FilePress domains can change. `FILEPRESS_API_URL` and `FILEPRESS_BASE_URL` are configurable, so update them in your environment if the service moves.
