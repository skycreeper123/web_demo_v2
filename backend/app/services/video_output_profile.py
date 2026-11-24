"""Shared generation and export settings for the video replacement recipes."""

from __future__ import annotations

import math
from typing import Any


VIDEO_FPS = 30
VIDEO_SHORT_SIDE = 1080
MODEL_ALIGNMENT = 16
PERSON_REPLACE_FPS = 16
PERSON_REPLACE_LONG_SIDE = 512


PROFILE_FIELDS = {"outputShortSide", "outputFps", "generationLongSide", "generationFps", "expectedSourceSeconds", "generationPolicy"}


def validate_profile(payload: dict[str, Any]) -> dict[str, Any]:
    policy = payload.get("generationPolicy", "legacy")
    if policy not in {"native", "legacy"}:
        raise ValueError("生成规格策略无效。")
    result = {"generationPolicy": policy}
    for key, default, minimum, maximum in (
        ("outputShortSide", 1080, 64, 2160), ("outputFps", 30, 1, 120),
        ("generationLongSide", None, 256, 2048), ("generationFps", None, 1, 60),
        ("expectedSourceSeconds", None, 0.1, 3600),
    ):
        value = payload.get(key)
        value = default if value is None or value == "" else value
        if value is None:
            result[key] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} 必须是有效数值。") from exc
        if isinstance(value, bool) or not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f"{key} 必须在 {minimum} 到 {maximum} 之间。")
        if key != "expectedSourceSeconds" and not number.is_integer():
            raise ValueError(f"{key} 必须是整数。")
        result[key] = number if key == "expectedSourceSeconds" else int(number)
    if policy == "native":
        if result["generationLongSide"] is not None:
            raise ValueError("原生生成请直接设置目标分辨率，清空旧的生成长边覆盖值。")
        if result["generationFps"] not in (None, result["outputFps"]):
            raise ValueError("原生生成帧率必须与目标帧率一致，不能生成后转换。")
        if result["outputFps"] > 60:
            raise ValueError("当前原生生成帧率上限为 60 fps。")
    return result


def person_replacement_dimensions(source_meta: dict[str, Any], profile: dict[str, Any] | None = None) -> tuple[int, int]:
    """Use the tested WanAnimate size; the final export restores the exact ratio."""
    if (profile or {}).get("generationPolicy") == "native":
        return generation_dimensions(source_meta, profile)
    width, height = int(source_meta["width"]), int(source_meta["height"])
    if min(width, height) <= 0:
        raise ValueError("视频尺寸必须大于 0。")
    scale = ((profile or {}).get("generationLongSide") or PERSON_REPLACE_LONG_SIDE) / max(width, height)
    return tuple(max(64, round(value * scale / MODEL_ALIGNMENT) * MODEL_ALIGNMENT)
                 for value in (width, height))


def output_video_meta(source_meta: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep the source aspect ratio and timeline, with a 1080px short side."""
    width, height = int(source_meta["width"]), int(source_meta["height"])
    if min(width, height) <= 0:
        raise ValueError("视频尺寸必须大于 0。")
    profile = validate_profile(profile or {})
    scale = profile["outputShortSide"] / min(width, height)
    # Even dimensions are required by the yuv420p export format.
    target_width = max(2, round(width * scale / 2) * 2)
    target_height = max(2, round(height * scale / 2) * 2)
    return {**source_meta, "width": target_width, "height": target_height,
            "fps": profile["outputFps"], "frames": round(float(source_meta["duration"]) * profile["outputFps"])}


def generation_dimensions(source_meta: dict[str, Any], profile: dict[str, Any] | None = None) -> tuple[int, int]:
    """Round UP for the model; export removes the small alignment difference."""
    if (profile or {}).get("generationLongSide"):
        return person_replacement_dimensions(source_meta, profile)
    target = output_video_meta({"duration": 0, **source_meta}, profile)
    return tuple((target[key] + MODEL_ALIGNMENT - 1) // MODEL_ALIGNMENT * MODEL_ALIGNMENT
                 for key in ("width", "height"))


def generation_frames(duration: float, fps: float = VIDEO_FPS) -> int:
    """Cover the requested duration at 30fps with the model's 4n+1 frames."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("生成视频时长必须是大于 0 的有效数值。")
    return max(5, math.ceil((duration * fps - 1) / 4) * 4 + 1)
