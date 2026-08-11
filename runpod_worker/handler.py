"""RunPod serverless handler that runs FaceFusion to perform the actual face swap.

Input JSON (matches app.swap_backend.RunPodSwapBackend.submit):
{
  "target_url": "...",
  "target_media_type": "image" | "video",
  "source_faces": [{"target_face_index": 0, "source_url": "..."}, ...],
  "face_enhancer": true,
  "lip_sync": false
}

Output JSON: {"result_url": "..."}

NOTE: this file was written against FaceFusion's documented CLI conventions but has
NOT been run against a live GPU here (this dev environment has none, and deploying
to RunPod requires your own account/billing). Before relying on it, deploy the
image and run one real job — if `python facefusion.py headless-run --help` inside
the container shows different flag names than below (CLI flags do change between
FaceFusion versions), adjust FACEFUSION_BASE_ARGS/build_pass_args accordingly.
"""

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import requests
import runpod
from runpod.serverless.utils import rp_upload

FACEFUSION_DIR = "/opt/facefusion"


def _download(url: str, dest: Path) -> Path:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest


def _run_facefusion(*, processors: list[str], target_path: Path, output_path: Path,
                     source_path: Path | None = None, reference_face_position: int | None = None) -> None:
    cmd = [
        "python", "facefusion.py", "headless-run",
        "--target-path", str(target_path),
        "--output-path", str(output_path),
        "--processors", *processors,
        "--execution-providers", "cuda",
    ]
    if source_path is not None:
        cmd += ["--source-paths", str(source_path)]
    if reference_face_position is not None:
        cmd += ["--face-selector-mode", "one", "--reference-face-position", str(reference_face_position)]

    result = subprocess.run(cmd, cwd=FACEFUSION_DIR, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"facefusion failed ({' '.join(cmd)}):\nstdout={result.stdout}\nstderr={result.stderr}")


def handler(job):
    job_input = job["input"]
    target_media_type = job_input["target_media_type"]
    ext = ".mp4" if target_media_type == "video" else ".png"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        current_target = _download(job_input["target_url"], tmp_path / f"target{ext}")

        # Multi-face support: apply one source face per detected target face, in sequence,
        # each pass feeding its output as the next pass's target.
        for i, mapping in enumerate(job_input["source_faces"]):
            source_path = _download(mapping["source_url"], tmp_path / f"source_{i}.png")
            step_output = tmp_path / f"step_{i}{ext}"
            _run_facefusion(
                processors=["face_swapper"],
                source_path=source_path,
                target_path=current_target,
                output_path=step_output,
                reference_face_position=mapping["target_face_index"],
            )
            current_target = step_output

        post_processors = []
        if job_input.get("face_enhancer"):
            post_processors.append("face_enhancer")
        if job_input.get("lip_sync") and target_media_type == "video":
            post_processors.append("lip_syncer")

        final_output = tmp_path / f"final{ext}"
        if post_processors:
            _run_facefusion(processors=post_processors, target_path=current_target, output_path=final_output)
        else:
            final_output.write_bytes(current_target.read_bytes())

        result_url = rp_upload.upload_file_to_bucket(
            file_name=f"{uuid.uuid4().hex}{ext}",
            file_location=str(final_output),
        )
        return {"result_url": result_url}


runpod.serverless.start({"handler": handler})
