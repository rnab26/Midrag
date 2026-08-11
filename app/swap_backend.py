"""Pluggable backend that actually performs the face swap.

Two implementations behind the same interface:
- MockSwapBackend: no GPU, no external account needed. Runs instantly so you can test
  the whole app (upload, save faces, history, downloads) before paying for anything.
- RunPodSwapBackend: calls a RunPod serverless endpoint running the real FaceFusion
  worker (see runpod_worker/). This is what does the actual, good-quality swap.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.storage import output_abs_path, upload_abs_path


class SwapBackendError(Exception):
    pass


class SwapBackend(ABC):
    @abstractmethod
    def submit(
        self,
        *,
        source_face_paths_by_target_index: dict[int, str],
        target_relative_path: str,
        target_media_type: str,
        output_relative_path: str,
        face_enhancer: bool,
        lip_sync: bool,
    ) -> str:
        """Kick off the swap. Returns a backend_job_id to poll later."""

    @abstractmethod
    def poll(self, backend_job_id: str, output_relative_path: str) -> tuple[str, str]:
        """Returns (status, error) where status is one of: running, completed, failed."""


class MockSwapBackend(SwapBackend):
    """Copies the target file to the output path so the rest of the app (history,
    download, multi-face mapping storage) can be exercised without a real GPU.
    For images, stamps a small watermark so it's visually obvious it's a mock result."""

    def submit(
        self,
        *,
        source_face_paths_by_target_index: dict[int, str],
        target_relative_path: str,
        target_media_type: str,
        output_relative_path: str,
        face_enhancer: bool,
        lip_sync: bool,
    ) -> str:
        src = upload_abs_path(target_relative_path)
        dst = output_abs_path(output_relative_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

        if target_media_type == "image":
            self._watermark(dst)

        return "mock-instant"

    def poll(self, backend_job_id: str, output_relative_path: str) -> tuple[str, str]:
        return "completed", ""

    @staticmethod
    def _watermark(image_path: Path) -> None:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return
        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        text = "MOCK SWAP"
        margin = 10
        draw.rectangle([0, img.height - 30, 150, img.height], fill=(0, 0, 0))
        draw.text((margin, img.height - 25), text, fill=(255, 255, 255))
        img.save(image_path)


class RunPodSwapBackend(SwapBackend):
    def __init__(self, api_key: str, endpoint_id: str, public_base_url: str):
        if not api_key or not endpoint_id:
            raise SwapBackendError(
                "RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID must be set to use the runpod backend."
            )
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.public_base_url = public_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _public_url_for_upload(self, relative_path: str) -> str:
        return f"{self.public_base_url}/media/uploads/{relative_path}"

    def submit(
        self,
        *,
        source_face_paths_by_target_index: dict[int, str],
        target_relative_path: str,
        target_media_type: str,
        output_relative_path: str,
        face_enhancer: bool,
        lip_sync: bool,
    ) -> str:
        payload: dict[str, Any] = {
            "input": {
                "target_url": self._public_url_for_upload(target_relative_path),
                "target_media_type": target_media_type,
                "source_faces": [
                    {"target_face_index": idx, "source_url": self._public_url_for_upload(path)}
                    for idx, path in source_face_paths_by_target_index.items()
                ],
                "face_enhancer": face_enhancer,
                "lip_sync": lip_sync,
            }
        }
        resp = httpx.post(
            f"https://api.runpod.ai/v2/{self.endpoint_id}/run",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        job_id = data.get("id")
        if not job_id:
            raise SwapBackendError(f"RunPod did not return a job id: {data}")
        return job_id

    def poll(self, backend_job_id: str, output_relative_path: str) -> tuple[str, str]:
        resp = httpx.get(
            f"https://api.runpod.ai/v2/{self.endpoint_id}/status/{backend_job_id}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")

        if status in ("IN_QUEUE", "IN_PROGRESS"):
            return "running", ""
        if status == "COMPLETED":
            result_url = (data.get("output") or {}).get("result_url")
            if not result_url:
                return "failed", f"RunPod completed but returned no result_url: {data}"
            dst = output_abs_path(output_relative_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            with httpx.stream("GET", result_url, timeout=120) as r:
                r.raise_for_status()
                with dst.open("wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
            return "completed", ""

        return "failed", str(data.get("error") or data)


def get_backend() -> SwapBackend:
    if settings.swap_backend == "runpod":
        return RunPodSwapBackend(settings.runpod_api_key, settings.runpod_endpoint_id, settings.public_base_url)
    return MockSwapBackend()
