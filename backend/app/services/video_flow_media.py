"""Media operations for the replacement flow, independent of model generation.

``cut_seconds`` always denotes a position on the original video's timeline.
All intermediates are created beside the requested output, and source media are
never modified. Durations are necessarily accurate to the nearest video frame.
"""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from .video_clip_service import _get_ffmpeg_executable, _require_cv2


def _source_file(value: Path) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"视频文件不存在或为空：{path}")
    return path


def probe_video(path: Path) -> dict[str, Any]:
    """Read validated video metadata without writing or changing the input."""
    path = _source_file(path)
    cv2 = _require_cv2()
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"无法打开视频：{path}")
        values = {
            "fps": float(capture.get(cv2.CAP_PROP_FPS)),
            "frames": float(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            "width": float(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        }
        if any(not math.isfinite(value) or value <= 0 for value in values.values()):
            raise RuntimeError(f"无法读取有效的视频帧率、帧数或尺寸：{path}")
        fps = values["fps"]
        frames, width, height = (int(values[key]) for key in ("frames", "width", "height"))
        if min(frames, width, height) < 1:
            raise RuntimeError(f"视频帧数或尺寸无效：{path}")
        duration = frames / fps
        if not math.isfinite(duration) or duration <= 0:
            raise RuntimeError(f"视频时长无效：{path}")
        return {"duration": duration, "fps": fps, "width": width, "height": height, "frames": frames}
    finally:
        capture.release()


def _number(value: float) -> str:
    return format(float(value), ".12g")


def _frame_rate(meta: dict[str, Any]) -> Fraction:
    fps = float(meta["fps"])
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("视频帧率必须是大于 0 的有效数值。")
    # Preserve rates such as 30000/1001 and 1197/40 (29.925), rather than
    # rounding all near-30 inputs to 30. The same rate drives every stage.
    return Fraction(str(fps)).limit_denominator(1_000_000)


def _fps_argument(meta: dict[str, Any]) -> str:
    rate = _frame_rate(meta)
    return str(rate.numerator) if rate.denominator == 1 else f"{rate.numerator}/{rate.denominator}"


def _timeline(meta: dict[str, Any], direction: str, cut_seconds: float) -> tuple[float, float, float]:
    if direction not in {"prefix", "suffix"}:
        raise ValueError("替换方向必须为 prefix（前段）或 suffix（后段）。")
    try:
        cut = float(cut_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("切点必须是有效的秒数。") from exc
    duration = float(meta["duration"])
    if not math.isfinite(cut) or not 0 < cut < duration:
        raise ValueError(f"切点必须大于 0 且小于原视频时长 {_number(duration)} 秒。")
    retained_duration = duration - cut if direction == "prefix" else cut
    replacement_duration = cut if direction == "prefix" else duration - cut
    if min(retained_duration, replacement_duration) < 1 / float(meta["fps"]):
        raise ValueError("保留段和替换段都必须至少包含一帧，请调整切点。")
    return cut, retained_duration, replacement_duration


def _task_output(root: Path, name: str) -> Path:
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / name
    # Also reject a pre-existing symlink pointing outside the task directory.
    if candidate.resolve().parent != root:
        raise ValueError("媒体输出必须位于当前任务的输出目录内。")
    if candidate.exists() or candidate.is_symlink():
        raise RuntimeError(f"输出文件已存在，请使用新的任务输出路径：{candidate}")
    return candidate


def _temporary_path(output: Path) -> Path:
    return _task_output(output.parent, f".{output.stem}_{uuid4().hex}.tmp{output.suffix}")


def _run_ffmpeg(arguments: list[str], *, duration: float, action: str) -> None:
    timeout = min(7200, max(120, math.ceil(duration * 30) + 60))
    command = [_get_ffmpeg_executable(), "-nostdin", "-hide_banner", "-loglevel", "error", "-n", *arguments]
    try:
        options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout, check=False)
        result = subprocess.run(command, **options)
        # Older system FFmpeg may be used when imageio's binary is unavailable.
        # Retry only a rejected option (before encoding started), using its
        # equivalent legacy spelling for this single-video-output command.
        error = (result.stderr or "").lower()
        if result.returncode and "-fps_mode:v" in command and "unrecognized option 'fps_mode" in error:
            compatible = list(command)
            compatible[compatible.index("-fps_mode:v")] = "-vsync"
            result = subprocess.run(compatible, **options)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{action}超时（{timeout} 秒），请检查视频长度或服务器负载。") from exc
    except OSError as exc:
        raise RuntimeError(f"{action}无法启动 FFmpeg：{exc}") from exc
    if result.returncode:
        detail = (result.stderr or "FFmpeg 没有返回错误说明。").strip()[-2500:]
        raise RuntimeError(f"{action}失败：{detail}")


def _video_encoding(meta: dict[str, Any]) -> list[str]:
    # yuv444p keeps unusual odd source dimensions without silently changing them.
    pixel_format = "yuv420p" if int(meta["width"]) % 2 == 0 and int(meta["height"]) % 2 == 0 else "yuv444p"
    rate = _frame_rate(meta)
    # FPS in a filter alone does not explicitly constrain the encoder/muxer.
    # Use CFR and matching encoder/MP4 clocks, with whole ticks per frame.
    timescale = rate.numerator * max(1, (10000 + rate.numerator - 1) // rate.numerator)
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", pixel_format,
            "-r:v", _fps_argument(meta), "-fps_mode:v", "cfr",
            "-enc_time_base:v", f"{rate.denominator}/{rate.numerator}",
            "-video_track_timescale", str(timescale),
            "-map_metadata", "-1", "-movflags", "+faststart"]


def _checked_output(output: Path, sources: list[Path]) -> Path:
    requested = Path(output).expanduser().absolute()
    if requested.suffix.lower() != ".mp4":
        raise ValueError("成片输出文件必须使用 .mp4 扩展名。")
    if requested.resolve() in sources:
        raise ValueError("成片输出不能覆盖输入视频。")
    return _task_output(requested.parent, requested.name)


def _extract_frame(video: Path, output: Path, *, last: bool, duration: float) -> None:
    temporary = _temporary_path(output)
    try:
        arguments: list[str] = []
        if last:
            # Decode the ending, updating one PNG through EOF: metadata-based
            # frame seeking alone can miss the actual final decodable frame.
            arguments.extend(["-sseof", _number(-min(2.0, duration))])
        arguments.extend(["-i", str(video), "-map", "0:v:0", "-an"])
        if last:
            arguments.extend(["-vsync", "0", "-update", "1"])
        else:
            arguments.extend(["-frames:v", "1", "-update", "1"])
        arguments.append(str(temporary))
        _run_ffmpeg(arguments, duration=duration, action="提取视频边界帧")
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"没有成功提取视频边界帧：{video}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_temporal(
    source: Path,
    output_dir: Path,
    direction: str,
    cut_seconds: float,
    *,
    extract_target_end: bool = False,
) -> dict[str, Any]:
    """Export the retained segment, its boundary, and an optional source end."""
    source = _source_file(source)
    meta = probe_video(source)
    cut, retained_duration, replacement_duration = _timeline(meta, direction, cut_seconds)
    retained = _task_output(output_dir, "retained.mp4")
    boundary = _task_output(output_dir, "boundary.png")
    original_first = _task_output(output_dir, "original_first.png")
    target_end = _task_output(output_dir, "target_end.png") if extract_target_end else None
    if source in {retained, boundary, original_first}:
        raise ValueError("任务输出不能覆盖原视频。")
    temporary = _temporary_path(retained)
    start = cut if direction == "prefix" else 0.0
    end = float(meta["duration"]) if direction == "prefix" else cut
    try:
        _run_ffmpeg(
            ["-i", str(source), "-map", "0:v:0", "-an", "-vf",
             f"trim=start={_number(start)}:end={_number(end)},setpts=PTS-STARTPTS,fps={_fps_argument(meta)}",
             "-t", _number(retained_duration), *_video_encoding(meta), str(temporary)],
            duration=float(meta["duration"]), action="裁切保留视频片段",
        )
        retained_meta = probe_video(temporary)
        temporary.replace(retained)
        _extract_frame(source, original_first, last=False, duration=float(meta["duration"]))
        _extract_frame(retained, boundary, last=direction == "suffix", duration=float(retained_meta["duration"]))
        if target_end is not None:
            # Use the full source ending, not the retained segment's boundary.
            _extract_frame(source, target_end, last=True, duration=float(meta["duration"]))
    finally:
        temporary.unlink(missing_ok=True)
    return {
        **meta,
        "retained_video": str(retained),
        "boundary_frame": str(boundary),
        "original_first_frame": str(original_first),
        **({"target_end": str(target_end)} if target_end is not None else {}),
        "replacement_duration": replacement_duration,
        "retained_duration": retained_duration,
        "cut_seconds": cut,
        "direction": direction,
    }


def _normalized_filter(
    input_meta: dict[str, Any], source_meta: dict[str, Any], duration: float, *, stretch: bool,
    stretch_geometry: bool = False,
) -> str:
    factor = duration / float(input_meta["duration"]) if stretch else 1.0
    width, height = int(source_meta["width"]), int(source_meta["height"])
    geometry = (
        f"scale={width}:{height},setsar=1,"
        if stretch_geometry else
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
    )
    return (
        f"setpts=(PTS-STARTPTS)*{_number(factor)},"
        f"{geometry}"
        f"fps={_fps_argument(source_meta)},"
        f"tpad=stop_mode=clone:stop_duration={_number(duration)},"
        f"trim=duration={_number(duration)},setpts=PTS-STARTPTS"
    )


def _render_final(
    inputs: list[Path],
    source: Path,
    output: Path,
    source_meta: dict[str, Any],
    filter_graph: str,
    keep_audio: bool,
) -> dict[str, Any]:
    output = _checked_output(output, [*inputs, source])
    temporary = _temporary_path(output)
    duration = float(source_meta["duration"])
    arguments: list[str] = []
    for input_path in [*inputs, source]:
        arguments.extend(["-i", str(input_path)])
    arguments.extend(["-filter_complex", filter_graph, "-map", "[video]"])
    if keep_audio:
        # Optional mapping allows silent source videos. Generation audio is
        # deliberately excluded; the full original timeline supplies the sound.
        arguments.extend(["-map", f"{len(inputs)}:a?", "-c:a", "aac", "-b:a", "192k"])
    else:
        arguments.append("-an")
    arguments.extend(["-t", _number(duration), *_video_encoding(source_meta), str(temporary)])
    try:
        _run_ffmpeg(arguments, duration=duration, action="合成替换视频")
        result_meta = probe_video(temporary)
        target_fps = float(_frame_rate(source_meta))
        actual_fps = float(result_meta["fps"])
        fps_difference = abs(actual_fps - target_fps)
        details = (f"目标帧率 {target_fps:.9g} fps，实际 {actual_fps:.9g} fps；"
                   f"原片 {source_meta['frames']} 帧，成片 {result_meta['frames']} 帧；"
                   f"目标时长 {duration:.9g} 秒，实际 {result_meta['duration']:.9g} 秒")
        tolerance = max(2 / target_fps, 0.075)
        if abs(float(result_meta["duration"]) - duration) > tolerance:
            raise RuntimeError(f"合成视频时长与原视频不一致：{details}。")
        if (result_meta["width"], result_meta["height"]) != (source_meta["width"], source_meta["height"]):
            raise RuntimeError(f"合成视频尺寸与原视频不一致：目标 {source_meta['width']}×{source_meta['height']}，"
                               f"实际 {result_meta['width']}×{result_meta['height']}；{details}。")
        # OpenCV/container average FPS may differ because of a final sample's
        # duration. Accept only a small (<1%) discrepancy accumulating to at
        # most one frame, with the independently reported frame count matching.
        frame_rounding_only = (
            fps_difference <= target_fps * 0.01
            and fps_difference * duration <= 1 + 1e-6
            and abs(int(result_meta["frames"]) - round(duration * target_fps)) <= 1
        )
        if not math.isclose(actual_fps, target_fps, rel_tol=0.001, abs_tol=0.001) and not frame_rounding_only:
            raise RuntimeError(f"合成视频帧率与原视频不一致：{details}。")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(output), "output_video": str(output), **result_meta,
            "source_duration": duration, "source_fps": target_fps,
            "fps_rational": _fps_argument(source_meta), "keep_audio": bool(keep_audio)}


def assemble_video(
    retained: Path,
    generated: Path,
    source: Path,
    output: Path,
    direction: str,
    cut_seconds: float,
    keep_audio: bool = True,
) -> dict[str, Any]:
    """Join a generated replacement with retained footage on the source timeline."""
    retained, generated, source = (_source_file(path) for path in (retained, generated, source))
    source_meta = probe_video(source)
    retained_meta, generated_meta = probe_video(retained), probe_video(generated)
    cut, retained_duration, replacement_duration = _timeline(source_meta, direction, cut_seconds)
    tolerance = max(2 / float(source_meta["fps"]), 2 / float(retained_meta["fps"]), 0.10)
    if abs(float(retained_meta["duration"]) - retained_duration) > tolerance:
        raise ValueError("保留片段时长与原视频切点不一致，请重新裁切保留片段。")
    retained_filter = _normalized_filter(retained_meta, source_meta, retained_duration, stretch=False)
    generated_filter = _normalized_filter(generated_meta, source_meta, replacement_duration, stretch=True)
    order = "[generated][retained]" if direction == "prefix" else "[retained][generated]"
    graph = (
        f"[0:v:0]{retained_filter}[retained];"
        f"[1:v:0]{generated_filter}[generated];"
        f"{order}concat=n=2:v=1:a=0,"
        f"fps={_fps_argument(source_meta)},"
        f"tpad=stop_mode=clone:stop_duration={_number(2 / float(source_meta['fps']))},"
        f"trim=duration={_number(source_meta['duration'])},setpts=PTS-STARTPTS[video]"
    )
    result = _render_final([retained, generated], source, output, source_meta, graph, keep_audio)
    return {**result, "direction": direction, "cut_seconds": cut, "replacement_duration": replacement_duration}


def finalize_spatial(
    generated: Path,
    source: Path,
    output: Path,
    keep_audio: bool = True,
) -> dict[str, Any]:
    """Restore source geometry, frame rate, duration and optional original audio."""
    generated, source = (_source_file(path) for path in (generated, source))
    source_meta, generated_meta = probe_video(source), probe_video(generated)
    # The fixed V5 graph resizes source frames directly to a square. Undo that
    # nonuniform resize here; fitting the square would preserve distortion and
    # add black bars. Temporal replacement still uses aspect-preserving fitting.
    graph = (
        "[0:v:0]"
        + _normalized_filter(generated_meta, source_meta, float(source_meta["duration"]),
                             stretch=True, stretch_geometry=True)
        + "[video]"
    )
    return _render_final([generated], source, output, source_meta, graph, keep_audio)
