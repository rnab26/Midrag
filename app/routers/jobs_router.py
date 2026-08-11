from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.database import get_db
from app.models import JobStatus, MediaAsset, SwapJob, SwapJobFaceMapping, User
from app.storage import new_output_path, output_abs_path
from app.swap_backend import SwapBackendError, get_backend

router = APIRouter(prefix="/jobs", tags=["jobs"])


class FaceMappingIn(BaseModel):
    source_face_asset_id: str
    target_face_index: int = 0


class CreateJobIn(BaseModel):
    target_asset_id: str
    mappings: list[FaceMappingIn]
    face_enhancer: bool = True
    lip_sync: bool = False


def _job_to_dict(job: SwapJob) -> dict:
    return {
        "id": job.id,
        "status": job.status.value,
        "error": job.error,
        "face_enhancer": job.face_enhancer,
        "lip_sync": job.lip_sync,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result_url": f"/jobs/{job.id}/result" if job.status == JobStatus.completed else None,
        "target_label": job.target_asset.label,
        "num_faces": len(job.face_mappings),
    }


@router.post("")
def create_job(request: Request, body: CreateJobIn, db: Session = Depends(get_db)):
    user: User = require_user(request, db)

    target = db.get(MediaAsset, body.target_asset_id)
    if not target or target.user_id != user.id:
        raise HTTPException(status_code=404, detail="Target media not found")
    if not body.mappings:
        raise HTTPException(status_code=400, detail="At least one source face mapping is required")

    source_assets: dict[str, MediaAsset] = {}
    for m in body.mappings:
        asset = db.get(MediaAsset, m.source_face_asset_id)
        if not asset or asset.user_id != user.id:
            raise HTTPException(status_code=404, detail=f"Source face {m.source_face_asset_id} not found")
        source_assets[m.source_face_asset_id] = asset

    output_ext = Path(target.stored_path).suffix
    output_relative_path = new_output_path(user.id, output_ext)

    job = SwapJob(
        user_id=user.id,
        target_asset_id=target.id,
        status=JobStatus.pending,
        face_enhancer=body.face_enhancer,
        lip_sync=body.lip_sync,
        result_path=output_relative_path,
    )
    db.add(job)
    db.flush()

    for m in body.mappings:
        db.add(
            SwapJobFaceMapping(
                job_id=job.id, source_face_asset_id=m.source_face_asset_id, target_face_index=m.target_face_index
            )
        )
    db.commit()
    db.refresh(job)

    backend = get_backend()
    try:
        backend_job_id = backend.submit(
            source_face_paths_by_target_index={
                m.target_face_index: source_assets[m.source_face_asset_id].stored_path for m in body.mappings
            },
            target_relative_path=target.stored_path,
            target_media_type=target.media_type.value,
            output_relative_path=output_relative_path,
            face_enhancer=job.face_enhancer,
            lip_sync=job.lip_sync,
        )
        job.backend_job_id = backend_job_id
        job.status = JobStatus.running
    except SwapBackendError as e:
        job.status = JobStatus.failed
        job.error = str(e)
    db.commit()
    db.refresh(job)

    _refresh_status(job, db)
    return _job_to_dict(job)


def _refresh_status(job: SwapJob, db: Session) -> None:
    if job.status not in (JobStatus.pending, JobStatus.running):
        return
    backend = get_backend()
    try:
        status, error = backend.poll(job.backend_job_id, job.result_path)
    except SwapBackendError as e:
        status, error = "failed", str(e)

    if status == "completed":
        job.status = JobStatus.completed
        job.completed_at = datetime.now(timezone.utc)
    elif status == "failed":
        job.status = JobStatus.failed
        job.error = error
    db.commit()
    db.refresh(job)


@router.get("")
def list_jobs(request: Request, db: Session = Depends(get_db)):
    user: User = require_user(request, db)
    jobs = (
        db.query(SwapJob)
        .filter(SwapJob.user_id == user.id)
        .order_by(SwapJob.created_at.desc())
        .all()
    )
    for job in jobs:
        _refresh_status(job, db)
    return [_job_to_dict(j) for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, request: Request, db: Session = Depends(get_db)):
    user: User = require_user(request, db)
    job = db.get(SwapJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404)
    _refresh_status(job, db)
    return _job_to_dict(job)


@router.get("/{job_id}/result")
def get_job_result(job_id: str, request: Request, db: Session = Depends(get_db)):
    user: User = require_user(request, db)
    job = db.get(SwapJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404)
    if job.status != JobStatus.completed:
        raise HTTPException(status_code=409, detail="Job not completed yet")
    path = output_abs_path(job.result_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Result file missing")
    return FileResponse(path)
