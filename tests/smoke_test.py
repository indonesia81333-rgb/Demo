from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import UploadDatabase  # noqa: E402
from services.filepress import _find_filepress_id, _find_url  # noqa: E402


def main() -> None:
    assert _find_filepress_id({"data": {"_id": "file123456789"}}) == "file123456789"
    assert _find_filepress_id({"id": "file123456789"}) == "file123456789"
    assert (
        _find_url({"data": {"url": "https://filepress.live/file/demo"}})
        == "https://filepress.live/file/demo"
    )

    with TemporaryDirectory() as tmp:
        db = UploadDatabase(Path(tmp) / "uploads.sqlite3")
        db.add_upload(
            user_id=1,
            file_name="demo.mp4",
            file_size=1234,
            drive_file_id="drive123",
            filepress_id="file123456789",
            share_url="https://filepress.live/file/file123456789",
        )
        rows = db.list_uploads(1)
        assert len(rows) == 1
        assert rows[0]["file_name"] == "demo.mp4"
        assert rows[0]["share_url"] == "https://filepress.live/file/file123456789"

    print("Smoke tests passed")


if __name__ == "__main__":
    main()
