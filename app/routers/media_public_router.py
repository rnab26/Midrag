"""Unauthenticated file serving used ONLY so the RunPod worker can fetch uploaded
files by URL. Paths are random UUIDs (unguessable), which is an acceptable tradeoff
for a personal tool but is NOT real access control — don't put private data you
wouldn't want exposed via a leaked link here. See README for hardening options
(e.g. swapping this for signed R2/S3 URLs)."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.storage import upload_abs_path

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/uploads/{path:path}")
def get_uploaded_file(path: str):
    abs_path = upload_abs_path(path)
    if not abs_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(abs_path)
