from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import AssetKind, MediaAsset, SwapJob
from app.templating import templates

router = APIRouter(tags=["pages"])


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    source_faces = (
        db.query(MediaAsset)
        .filter(MediaAsset.user_id == user.id, MediaAsset.kind == AssetKind.source_face)
        .order_by(MediaAsset.created_at.desc())
        .all()
    )
    target_media = (
        db.query(MediaAsset)
        .filter(MediaAsset.user_id == user.id, MediaAsset.kind == AssetKind.target_media)
        .order_by(MediaAsset.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "user": user, "source_faces": source_faces, "target_media": target_media},
    )


@router.get("/history")
def history_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    jobs = db.query(SwapJob).filter(SwapJob.user_id == user.id).order_by(SwapJob.created_at.desc()).all()
    return templates.TemplateResponse("history.html", {"request": request, "user": user, "jobs": jobs})
