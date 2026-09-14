from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from web_demo.backend.app.utils.file_writer import ensure_dir

from .path_resolver import resolve_comfy_input_dir, workflow_ref


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def _validate_source_path(label: str, value: str | None) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.exists():
        raise RuntimeError(f"{label}不存在：{path}")
    if not path.is_file():
        raise RuntimeError(f"{label}不是文件：{path}")
    return path


def stage_input_files(job_id: str, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    input_dir = ensure_dir(resolve_comfy_input_dir(config))
    job_input_dir = ensure_dir(input_dir / "jobs" / job_id)

    image_path = _validate_source_path("输入图片", payload.get("imagePath"))
    video_path = _validate_source_path("输入视频", payload.get("videoPath"))
    staged: dict[str, Any] = {
        "job_input_dir": str(job_input_dir),
        "image_ref": "",
        "video_ref": "",
        "staged_files": [],
    }

    if image_path:
        if image_path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            raise RuntimeError(f"不支持的图片格式：{image_path.name}")
        image_name = f"input{image_path.suffix.lower()}"
        image_target = job_input_dir / image_name
        shutil.copy2(image_path, image_target)
        staged["image_ref"] = workflow_ref("jobs", job_id, image_name)
        staged["staged_files"].append(str(image_target))

    if video_path:
        if video_path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            raise RuntimeError(f"不支持的视频格式：{video_path.name}")
        video_name = f"source{video_path.suffix.lower()}"
        video_target = job_input_dir / video_name
        shutil.copy2(video_path, video_target)
        staged["video_ref"] = workflow_ref("jobs", job_id, video_name)
        staged["staged_files"].append(str(video_target))

    return staged

