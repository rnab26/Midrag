from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import AssetKind, MediaAsset, MediaType, User
from app.storage import save_upload, upload_abs_path

router = APIRouter(prefix="/faces", tags=["faces"])


@router.post("/upload")
def upload_asset(
    request: Request,
    kind: str = Form(...),
    label: str = Form(""),
    file: UploadFile = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    user: User = require_user(request, db)
    if kind not in (AssetKind.source_face.value, AssetKind.target_media.value):
        raise HTTPException(status_code=400, detail="Invalid kind")
    if file is None:
        raise HTTPException(status_code=400, detail="No file provided")

    stored_path, media_type = save_upload(file, user.id)
    asset = MediaAsset(
        user_id=user.id,
        kind=AssetKind(kind),
        media_type=MediaType(media_type),
        label=label or (file.filename or ""),
        original_filename=file.filename or "",
        stored_path=stored_path,
    )
    db.add(asset)
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/{asset_id}/file")
def get_asset_file(asset_id: str, request: Request, db: Session = Depends(get_db)):
    user: User = require_user(request, db)
    asset = db.get(MediaAsset, asset_id)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status_code=404)
    return FileResponse(upload_abs_path(asset.stored_path))


@router.post("/{asset_id}/delete")
def delete_asset(asset_id: str, request: Request, db: Session = Depends(get_db)):
    user: User = require_user(request, db)
    asset = db.get(MediaAsset, asset_id)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status_code=404)

    path = upload_abs_path(asset.stored_path)
    db.delete(asset)
    db.commit()
    if path.exists():
        path.unlink()
    return RedirectResponse("/", status_code=303)
