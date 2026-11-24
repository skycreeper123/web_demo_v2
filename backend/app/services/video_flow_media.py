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
from .video_output_profile import output_video_meta, generation_dimensions, generation_frames


def native_generation_plan(source_meta, profile, duration):
    target = output_video_meta({**source_meta, "duration": duration}, profile)
    width, height = generation_dimensions(source_meta, profile)
    frames = target["frames"]
    if frames < 1:
        raise ValueError("替换时段不足一个目标生成帧。")
    return {"width": width, "height": height, "fps": target["fps"],
            "frames": frames, "requested_frames": generation_frames(frames / target["fps"], target["fps"]),
            "target_width": target["width"], "target_height": target["height"], "duration": duration}


def prepare_native_conditioning(source, output, plan):
    """Resample source conditions and pad to the model grid BEFORE inference."""
    source = _source_file(source)
    output = _checked_output(output, [source])
    width, height = plan['width'], plan['height']
    tw, th = plan['target_width'], plan['target_height']
    frames, fps = plan['requested_frames'], plan['fps']
    # Pad on right/bottom so the final crop is exact, including even pixel grids.
    vf = (f"scale={tw}:{th},pad={width}:{height}:0:0:color=black,setsar=1,"
          f"fps={fps},tpad=stop_mode=clone:stop_duration={_number(frames/fps)},"
          f"trim=end_frame={frames},setpts=PTS-STARTPTS")
    _run_ffmpeg(['-i', str(source), '-an', '-vf', vf, '-frames:v', str(frames),
                 *_video_encoding(plan), str(output)], duration=frames/fps, action="准备模型输入条件")
    meta = probe_video(output)
    if (meta['width'], meta['height'], meta['frames']) != (width, height, frames) or not math.isclose(meta['fps'], fps, abs_tol=.001):
        raise RuntimeError("模型输入条件尺寸或帧数不符。")
    return output


def validate_native_video(meta, plan):
    if (meta['width'], meta['height']) != (plan['width'], plan['height']):
        raise ValueError(f"模型生成尺寸不达标：需要 {plan['width']}×{plan['height']}，实际 {meta['width']}×{meta['height']}；禁止后期放大。")
    if not math.isclose(meta['fps'], plan['fps'], rel_tol=0, abs_tol=.001):
        raise ValueError(f"模型生成帧率不达标：需要 {plan['fps']}，实际 {meta['fps']}；禁止后期转换帧率。")
    if not plan['frames'] <= meta['frames'] <= plan['requested_frames']:
        raise ValueError(f"模型生成帧数不达标：需要 {plan['frames']} 至 {plan['requested_frames']}，实际 {meta['frames']}；禁止补帧或拉伸时长。")


def _native_filter(meta, plan):
    validate_native_video(meta, plan)
    return (f"crop={plan['target_width']}:{plan['target_height']}:0:0,setsar=1,"
            f"trim=end_frame={plan['frames']},setpts=PTS-STARTPTS,format=yuv420p")


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
    # Retained intermediates preserve source rates such as 30000/1001.
    # Final exports pass the explicit output profile instead.
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
    # Retained intermediates can keep unusual odd source dimensions with yuv444p.
    # Final output dimensions are even and therefore consistently use yuv420p.
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
    input_meta: dict[str, Any], target_meta: dict[str, Any], duration: float, *, stretch: bool,
    stretch_geometry: bool = False,
) -> str:
    factor = duration / float(input_meta["duration"]) if stretch else 1.0
    width, height = int(target_meta["width"]), int(target_meta["height"])
    geometry = (
        f"scale={width}:{height},setsar=1,"
        if stretch_geometry else
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
    )
    return (
        f"setpts=(PTS-STARTPTS)*{_number(factor)},"
        f"{geometry}"
        f"format=yuv420p,fps={_fps_argument(target_meta)},"
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
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output = _checked_output(output, [*inputs, source])
    temporary = _temporary_path(output)
    target_meta = output_video_meta(source_meta, profile)
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
    arguments.extend(["-t", _number(duration), *_video_encoding(target_meta), str(temporary)])
    try:
        _run_ffmpeg(arguments, duration=duration, action="合成替换视频")
        result_meta = probe_video(temporary)
        target_fps = float(_frame_rate(target_meta))
        target_frames = int(target_meta["frames"])
        actual_fps = float(result_meta["fps"])
        if (profile or {}).get('generationPolicy') == 'native' and (
                result_meta['frames'] != target_frames or not math.isclose(actual_fps, target_fps, rel_tol=0, abs_tol=.001)):
            raise RuntimeError(f"原生规格导出校验失败：需要 {target_frames} 帧 / {target_fps} fps，实际 {result_meta['frames']} 帧 / {actual_fps} fps。")
        fps_difference = abs(actual_fps - target_fps)
        details = (f"目标帧率 {target_fps:.9g} fps，实际 {actual_fps:.9g} fps；"
                   f"原片 {source_meta['frames']} 帧，目标 {target_frames} 帧，成片 {result_meta['frames']} 帧；"
                   f"目标时长 {duration:.9g} 秒，实际 {result_meta['duration']:.9g} 秒")
        tolerance = max(2 / target_fps, 0.075)
        if abs(float(result_meta["duration"]) - duration) > tolerance:
            raise RuntimeError(f"合成视频时长与原视频不一致：{details}。")
        if (result_meta["width"], result_meta["height"]) != (target_meta["width"], target_meta["height"]):
            raise RuntimeError(f"合成视频尺寸与输出设置不一致：目标 {target_meta['width']}×{target_meta['height']}，"
                               f"实际 {result_meta['width']}×{result_meta['height']}；{details}。")
        # OpenCV/container average FPS may differ because of a final sample's
        # duration. Accept only a small (<1%) discrepancy accumulating to at
        # most one frame, with the independently reported frame count matching.
        frame_rounding_only = (
            fps_difference <= target_fps * 0.01
            and fps_difference * duration <= 1 + 1e-6
            and abs(int(result_meta["frames"]) - target_frames) <= 1
        )
        if (abs(int(result_meta["frames"]) - target_frames) > 1
                or (not math.isclose(actual_fps, target_fps, rel_tol=0.001, abs_tol=0.001)
                    and not frame_rounding_only)):
            raise RuntimeError(f"合成视频帧数或帧率与输出设置不一致：{details}。")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(output), "output_video": str(output), **result_meta,
            "source_duration": duration, "source_fps": float(source_meta["fps"]),
            "fps_rational": _fps_argument(target_meta), "keep_audio": bool(keep_audio)}


def assemble_video(
    retained: Path,
    generated: Path,
    source: Path,
    output: Path,
    direction: str,
    cut_seconds: float,
    keep_audio: bool = True,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Join a generated replacement with retained footage on the source timeline."""
    retained, generated, source = (_source_file(path) for path in (retained, generated, source))
    source_meta = probe_video(source)
    target_meta = output_video_meta(source_meta, profile)
    retained_meta, generated_meta = probe_video(retained), probe_video(generated)
    cut, retained_duration, replacement_duration = _timeline(source_meta, direction, cut_seconds)
    tolerance = max(2 / float(source_meta["fps"]), 2 / float(retained_meta["fps"]), 0.10)
    if abs(float(retained_meta["duration"]) - retained_duration) > tolerance:
        raise ValueError("保留片段时长与原视频切点不一致，请重新裁切保留片段。")
    retained_filter = _normalized_filter(retained_meta, target_meta, retained_duration, stretch=False)
    generated_filter = _normalized_filter(generated_meta, target_meta, replacement_duration, stretch=True)
    if (profile or {}).get("generationPolicy") == "native":
        plan = native_generation_plan(source_meta, profile, replacement_duration)
        generated_filter = _native_filter(generated_meta, plan)
        retained_frames = target_meta['frames'] - plan['frames']
        # Only UGC is normalized; the generated portion is cropped, never retimed.
        retained_filter = _normalized_filter(retained_meta, target_meta, retained_frames/target_meta['fps'], stretch=False)
    order = "[generated][retained]" if direction == "prefix" else "[retained][generated]"
    graph = (
        f"[0:v:0]{retained_filter}[retained];"
        f"[1:v:0]{generated_filter}[generated];"
        f"{order}concat=n=2:v=1:a=0,"
        f"fps={_fps_argument(target_meta)},"
        f"tpad=stop_mode=clone:stop_duration={_number(2 / float(target_meta['fps']))},"
        f"trim=duration={_number(source_meta['duration'])},setpts=PTS-STARTPTS[video]"
    )
    if (profile or {}).get("generationPolicy") == "native":
        graph = (f"[0:v:0]{retained_filter}[retained];[1:v:0]{generated_filter}[generated];"
                 f"{order}concat=n=2:v=1:a=0,trim=end_frame={target_meta['frames']},setpts=PTS-STARTPTS[video]")
    result = _render_final([retained, generated], source, output, source_meta, graph, keep_audio, profile)
    return {**result, "direction": direction, "cut_seconds": cut, "replacement_duration": replacement_duration}


def assemble_native_region(generated: Path, source: Path, output: Path, *, direction: str,
                           cut_seconds: float, keep_audio: bool, profile: dict[str, Any]) -> dict[str, Any]:
    """Anchor the edited side of the cut to the original timeline without retiming."""
    generated, source = _source_file(generated), _source_file(source)
    source_meta = probe_video(source)
    target = output_video_meta(source_meta, profile)
    _, _, duration = _timeline(source_meta, direction, cut_seconds)
    plan = native_generation_plan(source_meta, profile, duration)
    fps, total, edited = target['fps'], target['frames'], plan['frames']
    if min(edited, total - edited) < 1:
        raise ValueError('区域替换的切点两侧必须各有至少一个输出帧。')
    prefix = direction == 'prefix'
    start, end = (0, edited) if prefix else (total - edited, total)
    keep_start, keep_end = (edited, total) if prefix else (0, start)
    # Fade only inside the edited interval. At the adjoining frame the weight
    # is exactly zero, so both sides of the cut come from the same original.
    ramp = max(1, min(round(fps * .3), edited - 1))
    distance = f'{edited - 1}-T*{fps}' if prefix else f'T*{fps}'
    weight = f"st(0,clip(({distance})/{ramp},0,1));ld(0)*ld(0)*(3-2*ld(0))"
    base = (f"scale={target['width']}:{target['height']},setsar=1,format=yuv420p,"
            f"fps={fps},tpad=stop_mode=clone:stop_duration={_number(1/fps)},"
            f"trim=end_frame={total},split=2[whole_edit][whole_keep]")
    order = '[edited][retained]' if prefix else '[retained][edited]'
    graph = (
        f"[1:v:0]{base};"
        f"[whole_edit]trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS[original];"
        f"[whole_keep]trim=start_frame={keep_start}:end_frame={keep_end},setpts=PTS-STARTPTS[retained];"
        f"[0:v:0]{_native_filter(probe_video(generated), plan)}[generated];"
        f"[original][generated]blend=all_expr='A+(B-A)*({weight})':shortest=1[edited];"
        f"{order}concat=n=2:v=1:a=0,setpts=PTS-STARTPTS[video]"
    )
    return _render_final([generated], source, output, source_meta, graph, keep_audio, profile)


def finalize_spatial(
    generated: Path,
    source: Path,
    output: Path,
    keep_audio: bool = True,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Export the 1080p/30fps profile with the source timeline and optional audio."""
    generated, source = (_source_file(path) for path in (generated, source))
    source_meta, generated_meta = probe_video(source), probe_video(generated)
    target_meta = output_video_meta(source_meta, profile)
    if (profile or {}).get("generationPolicy") == "native":
        plan = native_generation_plan(source_meta, profile, source_meta['duration'])
        graph = '[0:v:0]' + _native_filter(generated_meta, plan) + '[video]'
        return _render_final([generated], source, output, source_meta, graph, keep_audio, profile)
    # The model aligns dimensions to its spatial grid. Scale back to the source
    # aspect ratio at the output size so alignment does not introduce black bars.
    graph = (
        "[0:v:0]"
        + _normalized_filter(generated_meta, target_meta, float(source_meta["duration"]),
                             stretch=True, stretch_geometry=True)
        + "[video]"
    )
    return _render_final([generated], source, output, source_meta, graph, keep_audio, profile)


def prepare_spatial_interval(source: Path, directory: Path, direction: str, cut_seconds: float) -> dict[str, Any]:
    """Keep the untouched interval and supply only the edited interval to Comfy."""
    media = prepare_temporal(source, directory, direction, cut_seconds)
    meta = probe_video(source)
    start = 0 if direction == "prefix" else cut_seconds
    end = cut_seconds if direction == "prefix" else meta["duration"]
    target = _task_output(directory, "target_video.mp4")
    _run_ffmpeg(["-i", str(source), "-map", "0:v:0", "-an", "-vf",
                 f"trim=start={_number(start)}:end={_number(end)},setpts=PTS-STARTPTS,fps={_fps_argument(meta)}",
                 *_video_encoding(meta), str(target)], duration=end-start, action="裁切区域替换时段")
    actual = probe_video(target)
    if abs(actual["duration"] - (end-start)) > max(2/meta["fps"], 0.075):
        raise RuntimeError("区域替换时段裁切时长异常。")
    return {**media, "target_video": str(target)}
