import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import settings

# Hard cap for any uploaded file. Image-heavy manga epubs are legitimately
# large, so this is set generously. Must match nginx `client_max_body_size`.
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB


def get_book_path(book_id: uuid.UUID, filename: str) -> str:
    ext = Path(filename).suffix
    return str(Path(settings.books_dir) / f"{book_id}{ext}")


def get_cover_path(book_id: uuid.UUID) -> str:
    return str(Path(settings.covers_dir) / f"{book_id}.jpg")


def get_illustration_path(illustration_id: uuid.UUID) -> str:
    return str(Path(settings.illustrations_dir) / f"{illustration_id}.png")


async def save_upload_file(upload_file: UploadFile, dest_path: str) -> int:
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    size = 0
    try:
        with open(dest_path, "wb") as f:
            while chunk := await upload_file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            f"File exceeds maximum upload size of "
                            f"{MAX_UPLOAD_SIZE // (1024 * 1024)} MB"
                        ),
                    )
                f.write(chunk)
    except HTTPException:
        # Don't leave a half-written file on disk if the upload was rejected.
        try:
            os.remove(dest_path)
        except FileNotFoundError:
            pass
        raise
    return size


def delete_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
