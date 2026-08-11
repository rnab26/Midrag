import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}


def guess_media_type(filename: str) -> str:
    ext = _ext(filename)
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    raise ValueError(f"Unsupported file type: {ext}")


def save_upload(upload: UploadFile, user_id: str) -> tuple[str, str]:
    """Saves an uploaded file under the user's upload dir. Returns (stored_relative_path, media_type)."""
    media_type = guess_media_type(upload.filename or "")
    rel_dir = Path(user_id)
    abs_dir = settings.uploads_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}{_ext(upload.filename or '')}"
    abs_path = abs_dir / stored_name
    with abs_path.open("wb") as f:
        shutil.copyfileobj(upload.file, f)

    return str(rel_dir / stored_name), media_type


def upload_abs_path(stored_relative_path: str) -> Path:
    return settings.uploads_dir / stored_relative_path


def output_abs_path(stored_relative_path: str) -> Path:
    return settings.outputs_dir / stored_relative_path


def new_output_path(user_id: str, ext: str) -> str:
    rel_dir = Path(user_id)
    abs_dir = settings.outputs_dir / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    return str(rel_dir / stored_name)
