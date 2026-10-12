"""Shared generation and export settings for the video replacement recipes."""

from __future__ import annotations

import math
from typing import Any


VIDEO_FPS = 30
VIDEO_SHORT_SIDE = 1080
MODEL_ALIGNMENT = 16


def output_video_meta(source_meta: dict[str, Any]) -> dict[str, Any]:
    """Keep the source aspect ratio and timeline, with a 1080px short side."""
    width, height = int(source_meta["width"]), int(source_meta["height"])
    if min(width, height) <= 0:
        raise ValueError("视频尺寸必须大于 0。")
    scale = VIDEO_SHORT_SIDE / min(width, height)
    # Even dimensions are required by the yuv420p export format.
    target_width = max(2, round(width * scale / 2) * 2)
    target_height = max(2, round(height * scale / 2) * 2)
    return {**source_meta, "width": target_width, "height": target_height,
            "fps": VIDEO_FPS, "frames": round(float(source_meta["duration"]) * VIDEO_FPS)}


def generation_dimensions(source_meta: dict[str, Any]) -> tuple[int, int]:
    """Round UP for the model; export removes the small alignment difference."""
    target = output_video_meta(source_meta)
    return tuple((target[key] + MODEL_ALIGNMENT - 1) // MODEL_ALIGNMENT * MODEL_ALIGNMENT
                 for key in ("width", "height"))


def generation_frames(duration: float) -> int:
    """Cover the requested duration at 30fps with the model's 4n+1 frames."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("生成视频时长必须是大于 0 的有效数值。")
    return max(5, math.ceil((duration * VIDEO_FPS - 1) / 4) * 4 + 1)
