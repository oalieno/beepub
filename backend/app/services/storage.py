import os
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings


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
    with open(dest_path, "wb") as f:
        while chunk := await upload_file.read(1024 * 1024):
            f.write(chunk)
            size += len(chunk)
    return size


def delete_file(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
