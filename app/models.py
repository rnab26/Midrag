import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AssetKind(str, enum.Enum):
    source_face = "source_face"
    target_media = "target_media"


class MediaType(str, enum.Enum):
    image = "image"
    video = "video"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    assets: Mapped[list["MediaAsset"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[list["SwapJob"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class MediaAsset(Base):
    """A saved, reusable file: either a source face or a target photo/video."""

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[AssetKind] = mapped_column(Enum(AssetKind))
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType))
    label: Mapped[str] = mapped_column(String, default="")
    original_filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)  # relative to settings.uploads_dir
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="assets")


class SwapJob(Base):
    __tablename__ = "swap_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    target_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))

    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.pending)
    error: Mapped[str] = mapped_column(Text, default="")

    face_enhancer: Mapped[bool] = mapped_column(Boolean, default=True)
    lip_sync: Mapped[bool] = mapped_column(Boolean, default=False)

    backend_job_id: Mapped[str] = mapped_column(String, default="")
    result_path: Mapped[str] = mapped_column(String, default="")  # relative to settings.outputs_dir

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="jobs")
    target_asset: Mapped["MediaAsset"] = relationship(foreign_keys=[target_asset_id])
    face_mappings: Mapped[list["SwapJobFaceMapping"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="SwapJobFaceMapping.target_face_index"
    )


class SwapJobFaceMapping(Base):
    """One entry per face being replaced in the target — this is what makes multi-face swaps possible:
    each detected face in the target (by index) gets its own source face asset."""

    __tablename__ = "swap_job_face_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("swap_jobs.id"), index=True)
    source_face_asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))
    target_face_index: Mapped[int] = mapped_column(Integer)  # which detected face in the target to replace

    job: Mapped["SwapJob"] = relationship(back_populates="face_mappings")
    source_face_asset: Mapped["MediaAsset"] = relationship(foreign_keys=[source_face_asset_id])
