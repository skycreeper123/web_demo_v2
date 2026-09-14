from __future__ import annotations

import csv
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from web_demo.backend.app.core.config import is_absolute_path_text, resolve_output_path
from web_demo.backend.app.utils.file_writer import ensure_dir, write_json

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    cv2 = None

try:
    import imageio_ffmpeg  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    imageio_ffmpeg = None


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


@dataclass(frozen=True)
class ClipPreset:
    key: str
    label: str
    group: str
    description: str
    mode: str
    output_dir_name: str
    trimmed_dir_name: str = "trimmed"
    preview_dir_name: str = "last_frames"


CLIP_PRESETS: dict[str, ClipPreset] = {
    "first_half_ffmpeg": ClipPreset(
        key="first_half_ffmpeg",
        label="保留前 50%（ffmpeg）",
        group="前半段",
        description="速度最快，使用 ffmpeg -c copy 裁切，并抽取中点附近预览帧。",
        mode="ffmpeg_half",
        output_dir_name="output",
        trimmed_dir_name="trimmed",
        preview_dir_name="last_frames",
    ),
    "first_half_opencv": ClipPreset(
        key="first_half_opencv",
        label="保留前 50%（OpenCV）",
        group="前半段",
        description="按帧写入并重新编码，预览图为保留段最后一帧。",
        mode="opencv_half",
        output_dir_name="output_opencv",
        trimmed_dir_name="trimmed",
        preview_dir_name="last_frames",
    ),
    "first_30pct": ClipPreset(
        key="first_30pct",
        label="保留前 30%",
        group="比例裁切",
        description="按总帧数截取前 30%，预览图为保留段最后一帧。",
        mode="opencv_ratio_first",
        output_dir_name="output_30pct",
        trimmed_dir_name="trimmed",
        preview_dir_name="last_frames",
    ),
    "first_70pct": ClipPreset(
        key="first_70pct",
        label="保留前 70%",
        group="比例裁切",
        description="按总帧数截取前 70%，预览图为保留段最后一帧。",
        mode="opencv_ratio_first",
        output_dir_name="output_70pct",
        trimmed_dir_name="trimmed",
        preview_dir_name="last_frames",
    ),
    "first_3s": ClipPreset(
        key="first_3s",
        label="保留前 3 秒",
        group="按秒裁切",
        description="保留前 3 秒，预览图为保留段最后一帧。",
        mode="opencv_seconds_first",
        output_dir_name="output_first_3s",
        trimmed_dir_name="trimmed",
        preview_dir_name="last_frames",
    ),
    "first_5s": ClipPreset(
        key="first_5s",
        label="保留前 5 秒",
        group="按秒裁切",
        description="保留前 5 秒，预览图为保留段最后一帧。",
        mode="opencv_seconds_first",
        output_dir_name="output_first_5s",
        trimmed_dir_name="trimmed",
        preview_dir_name="last_frames",
    ),
    "first_7s": ClipPreset(
        key="first_7s",
        label="保留前 7 秒",
        group="按秒裁切",
        description="保留前 7 秒，预览图为保留段最后一帧。",
        mode="opencv_seconds_first",
        output_dir_name="output_first_7s",
        trimmed_dir_name="trimmed",
        preview_dir_name="last_frames",
    ),
    "last_3s": ClipPreset(
        key="last_3s",
        label="保留后 3 秒",
        group="按秒裁切",
        description="保留后 3 秒，预览图为保留段第一帧。",
        mode="opencv_seconds_last",
        output_dir_name="output_last_3s",
        trimmed_dir_name="trimmed",
        preview_dir_name="first_frames",
    ),
    "last_5s": ClipPreset(
        key="last_5s",
        label="保留后 5 秒",
        group="按秒裁切",
        description="保留后 5 秒，预览图为保留段第一帧。",
        mode="opencv_seconds_last",
        output_dir_name="output_last_5s",
        trimmed_dir_name="trimmed",
        preview_dir_name="first_frames",
    ),
    "last_7s": ClipPreset(
        key="last_7s",
        label="保留后 7 秒",
        group="按秒裁切",
        description="保留后 7 秒，预览图为保留段第一帧。",
        mode="opencv_seconds_last",
        output_dir_name="output_last_7s",
        trimmed_dir_name="trimmed",
        preview_dir_name="first_frames",
    ),
    "tail_30pct": ClipPreset(
        key="tail_30pct",
        label="保留后 30%",
        group="比例裁切",
        description="按总帧数保留后 30%，预览图为保留段第一帧。",
        mode="opencv_ratio_last",
        output_dir_name="output_tail_30pct",
        trimmed_dir_name="trimmed",
        preview_dir_name="first_frames",
    ),
    "tail_50pct": ClipPreset(
        key="tail_50pct",
        label="保留后 50%",
        group="比例裁切",
        description="按总帧数保留后 50%，预览图为保留段第一帧。",
        mode="opencv_ratio_last",
        output_dir_name="output_tail_50pct",
        trimmed_dir_name="trimmed",
        preview_dir_name="first_frames",
    ),
    "tail_70pct": ClipPreset(
        key="tail_70pct",
        label="保留后 70%",
        group="比例裁切",
        description="按总帧数保留后 70%，预览图为保留段第一帧。",
        mode="opencv_ratio_last",
        output_dir_name="output_tail_70pct",
        trimmed_dir_name="trimmed",
        preview_dir_name="first_frames",
    ),
    "merge_pairwise": ClipPreset(
        key="merge_pairwise",
        label="双文件夹顺序合并",
        group="合并",
        description="按排序后一一配对，第二组视频缩放到第一组尺寸后拼接输出。",
        mode="merge_pairwise",
        output_dir_name="output_merged_pairs",
        trimmed_dir_name="",
        preview_dir_name="",
    ),
}


def list_clip_presets() -> list[dict[str, Any]]:
    return [
        {
            "key": preset.key,
            "label": preset.label,
            "group": preset.group,
            "description": preset.description,
            "mode": preset.mode,
        }
        for preset in CLIP_PRESETS.values()
    ]


def _resolve_input_dir(value: str, *, path_style: str = "") -> Path:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError("请输入输入目录路径。")
    path = Path(text).expanduser()
    if not is_absolute_path_text(text, path_style):
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise RuntimeError(f"找不到输入目录：{path}")
    if not path.is_dir():
        raise RuntimeError(f"输入路径不是文件夹：{path}")
    return path


def _list_videos(folder: Path) -> list[Path]:
    return sorted([path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in VIDEO_EXTS])


def _create_timestamp_output_dir(output_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    candidate = output_root / timestamp
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{timestamp}_{suffix}"
        suffix += 1
    return ensure_dir(candidate)


def _require_cv2() -> Any:
    if cv2 is None:
        raise RuntimeError("OpenCV is required for this clip preset.")
    return cv2


def _require_ffmpeg() -> None:
    binary = _get_ffmpeg_executable()
    try:
        subprocess.run([binary, "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("Missing ffmpeg binary.") from exc
    except subprocess.CalledProcessError as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("Unable to run ffmpeg.") from exc


def _get_ffmpeg_executable() -> str:
    if imageio_ffmpeg is not None:
        try:
            return str(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception:
            pass
    return "ffmpeg"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _probe_duration(video_path: Path) -> float:
    _require_cv2()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video_path.name}")
    try:
        fps, total_frames, _, _ = _capture_video_meta(cap, video_path)
        return total_frames / fps
    finally:
        cap.release()


def _ffmpeg_half_keep(video: Path, trimmed_dir: Path, preview_dir: Path) -> dict[str, Any]:
    _require_ffmpeg()
    duration = _probe_duration(video)
    half = duration / 2
    out_video = trimmed_dir / f"{video.stem}_first_half{video.suffix}"
    out_frame = preview_dir / f"{video.stem}_half_last_frame.jpg"

    _run([
        _get_ffmpeg_executable(),
        "-y",
        "-i",
        str(video),
        "-t",
        f"{half}",
        "-c",
        "copy",
        str(out_video),
    ])

    seek_time = max(0.0, half - 0.05)
    _run([
        _get_ffmpeg_executable(),
        "-y",
        "-ss",
        f"{seek_time}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        str(out_frame),
    ])

    return {
        "output_video": str(out_video),
        "preview_image": str(out_frame),
        "detail": "保留前 50% 时长（ffmpeg）",
    }


def _capture_video_meta(cap: Any, video: Path) -> tuple[float, int, int, int]:
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0 or total_frames <= 0 or width <= 0 or height <= 0:
        raise RuntimeError(f"无法读取视频信息：{video.name}")
    return fps, total_frames, width, height


def _write_first_frames(
    *,
    video: Path,
    trimmed_dir: Path,
    preview_dir: Path,
    keep_frames: int,
    output_name: str,
    preview_name: str,
    preview_mode: str,
) -> dict[str, Any]:
    _require_cv2()
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video.name}")

    try:
        fps, total_frames, width, height = _capture_video_meta(cap, video)
        keep_frames = min(total_frames, max(1, keep_frames))
        out_video = trimmed_dir / output_name
        out_frame = preview_dir / preview_name
        writer = cv2.VideoWriter(str(out_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        last_frame = None

        for _ in range(keep_frames):
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
            last_frame = frame

        writer.release()
        if last_frame is None:
            raise RuntimeError(f"没有成功读取画面：{video.name}")
        cv2.imwrite(str(out_frame), last_frame)
        return {
            "output_video": str(out_video),
            "preview_image": str(out_frame),
            "detail": preview_mode,
        }
    finally:
        cap.release()


def _write_last_frames(
    *,
    video: Path,
    trimmed_dir: Path,
    preview_dir: Path,
    keep_frames: int,
    output_name: str,
    preview_name: str,
    preview_mode: str,
) -> dict[str, Any]:
    _require_cv2()
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{video.name}")

    try:
        fps, total_frames, width, height = _capture_video_meta(cap, video)
        keep_frames = min(total_frames, max(1, keep_frames))
        start_frame = max(0, total_frames - keep_frames)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        ok, first_frame = cap.read()
        if not ok:
            raise RuntimeError(f"无法读取起始帧：{video.name}")

        out_video = trimmed_dir / output_name
        out_frame = preview_dir / preview_name
        writer = cv2.VideoWriter(str(out_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        writer.write(first_frame)

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)

        writer.release()
        cv2.imwrite(str(out_frame), first_frame)
        return {
            "output_video": str(out_video),
            "preview_image": str(out_frame),
            "detail": preview_mode,
        }
    finally:
        cap.release()


def _process_single_preset(
    *,
    preset: ClipPreset,
    source_dir: Path,
    preset_dir: Path,
    log: Callable[[str], None],
    progress: Callable[[int, int], None],
) -> dict[str, Any]:
    videos = _list_videos(source_dir)
    if not videos:
        raise RuntimeError(f"在 {source_dir} 中没有找到视频文件。")

    trimmed_dir = ensure_dir(preset_dir / preset.trimmed_dir_name)
    preview_dir = ensure_dir(preset_dir / preset.preview_dir_name)
    items: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    total = len(videos)

    for index, video in enumerate(videos, start=1):
        log(f"处理视频：{video.name}")
        try:
            if preset.mode == "ffmpeg_half":
                result = _ffmpeg_half_keep(video, trimmed_dir, preview_dir)
            elif preset.mode == "opencv_half":
                cap = _require_cv2().VideoCapture(str(video))
                if not cap.isOpened():
                    raise RuntimeError(f"无法打开视频：{video.name}")
                try:
                    _, total_frames, _, _ = _capture_video_meta(cap, video)
                finally:
                    cap.release()
                keep_frames = max(1, total_frames // 2)
                result = _write_first_frames(
                    video=video,
                    trimmed_dir=trimmed_dir,
                    preview_dir=preview_dir,
                    keep_frames=keep_frames,
                    output_name=f"{video.stem}_first_half.mp4",
                    preview_name=f"{video.stem}_half_last_frame.jpg",
                    preview_mode="保留前 50% 帧（OpenCV）",
                )
            elif preset.mode == "opencv_ratio_first":
                ratio = 0.3 if preset.key == "first_30pct" else 0.7
                cap = _require_cv2().VideoCapture(str(video))
                if not cap.isOpened():
                    raise RuntimeError(f"无法打开视频：{video.name}")
                try:
                    _, total_frames, _, _ = _capture_video_meta(cap, video)
                finally:
                    cap.release()
                keep_frames = max(1, int(total_frames * ratio))
                suffix = "30pct" if ratio == 0.3 else "70pct"
                result = _write_first_frames(
                    video=video,
                    trimmed_dir=trimmed_dir,
                    preview_dir=preview_dir,
                    keep_frames=keep_frames,
                    output_name=f"{video.stem}_first_{suffix}.mp4",
                    preview_name=f"{video.stem}_{suffix}_last_frame.jpg",
                    preview_mode=f"保留前 {int(ratio * 100)}%",
                )
            elif preset.mode == "opencv_seconds_first":
                seconds = 3 if preset.key.endswith("3s") else 5 if preset.key.endswith("5s") else 7
                cap = _require_cv2().VideoCapture(str(video))
                if not cap.isOpened():
                    raise RuntimeError(f"无法打开视频：{video.name}")
                try:
                    fps, total_frames, _, _ = _capture_video_meta(cap, video)
                finally:
                    cap.release()
                keep_frames = min(total_frames, max(1, int(fps * seconds)))
                result = _write_first_frames(
                    video=video,
                    trimmed_dir=trimmed_dir,
                    preview_dir=preview_dir,
                    keep_frames=keep_frames,
                    output_name=f"{video.stem}_first_{seconds}s.mp4",
                    preview_name=f"{video.stem}_first_{seconds}s_last_frame.jpg",
                    preview_mode=f"保留前 {seconds} 秒",
                )
            elif preset.mode == "opencv_seconds_last":
                seconds = 3 if preset.key.endswith("3s") else 5 if preset.key.endswith("5s") else 7
                cap = _require_cv2().VideoCapture(str(video))
                if not cap.isOpened():
                    raise RuntimeError(f"无法打开视频：{video.name}")
                try:
                    fps, total_frames, _, _ = _capture_video_meta(cap, video)
                finally:
                    cap.release()
                keep_frames = min(total_frames, max(1, int(fps * seconds)))
                result = _write_last_frames(
                    video=video,
                    trimmed_dir=trimmed_dir,
                    preview_dir=preview_dir,
                    keep_frames=keep_frames,
                    output_name=f"{video.stem}_last_{seconds}s.mp4",
                    preview_name=f"{video.stem}_last_{seconds}s_first_frame.jpg",
                    preview_mode=f"保留后 {seconds} 秒",
                )
            elif preset.mode == "opencv_ratio_last":
                ratio = {"tail_30pct": 0.3, "tail_50pct": 0.5, "tail_70pct": 0.7}[preset.key]
                cap = _require_cv2().VideoCapture(str(video))
                if not cap.isOpened():
                    raise RuntimeError(f"无法打开视频：{video.name}")
                try:
                    _, total_frames, _, _ = _capture_video_meta(cap, video)
                finally:
                    cap.release()
                keep_frames = max(1, int(total_frames * ratio))
                suffix = f"last_{int(ratio * 100)}pct"
                result = _write_last_frames(
                    video=video,
                    trimmed_dir=trimmed_dir,
                    preview_dir=preview_dir,
                    keep_frames=keep_frames,
                    output_name=f"{video.stem}_{suffix}.mp4",
                    preview_name=f"{video.stem}_{suffix}_first_frame.jpg",
                    preview_mode=f"保留后 {int(ratio * 100)}%",
                )
            else:
                raise RuntimeError(f"不支持的预设模式：{preset.mode}")

            items.append(
                {
                    "source": str(video),
                    "output_video": result["output_video"],
                    "preview_image": result["preview_image"],
                    "status": "done",
                    "detail": result["detail"],
                }
            )
            log(f"完成：{Path(result['output_video']).name}")
        except Exception as exc:
            failures.append({"source": str(video), "error": str(exc)})
            items.append(
                {
                    "source": str(video),
                    "output_video": "",
                    "preview_image": "",
                    "status": "failed",
                    "detail": str(exc),
                }
            )
            log(f"失败：{video.name} -> {exc}")
        finally:
            progress(index, total)

    return {
        "items": items,
        "failures": failures,
        "total": total,
    }


def _write_manifest(job_dir: Path, payload: dict[str, Any]) -> None:
    write_json(job_dir / "manifest.json", payload)
    rows = []
    for item in payload.get("items", []):
        rows.append({key: str(value) for key, value in item.items()})
    if rows:
        csv_path = job_dir / "summary.csv"
        ensure_dir(csv_path.parent)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = sorted({key for row in rows for key in row.keys()})
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def run_video_clip_job(
    *,
    job_id: str,
    payload: dict[str, Any],
    log: Callable[[str], None],
    progress: Callable[[int, int], None],
) -> dict[str, Any]:
    preset_key = str(payload.get("preset") or "").strip()
    preset = CLIP_PRESETS.get(preset_key)
    if not preset:
        raise RuntimeError("请选择有效的剪辑预设。")

    path_style = str(payload.get("pathStyle") or "").strip().lower()
    output_root = resolve_output_path(str(payload.get("outputDir") or "").strip() or None, path_style=path_style)
    ensure_dir(output_root)
    job_dir = _create_timestamp_output_dir(output_root)
    preset_dir = ensure_dir(job_dir / preset.output_dir_name)

    log(f"预设：{preset.label}")
    log(f"输出目录：{job_dir}")

    if preset.mode == "merge_pairwise":
        source_dir_a = _resolve_input_dir(str(payload.get("inputDirA") or ""), path_style=path_style)
        source_dir_b = _resolve_input_dir(str(payload.get("inputDirB") or ""), path_style=path_style)
        videos_a = _list_videos(source_dir_a)
        videos_b = _list_videos(source_dir_b)
        if not videos_a:
            raise RuntimeError(f"在 {source_dir_a} 中没有找到视频文件。")
        if not videos_b:
            raise RuntimeError(f"在 {source_dir_b} 中没有找到视频文件。")

        _require_cv2()
        pair_count = min(len(videos_a), len(videos_b))
        if len(videos_a) != len(videos_b):
            log(f"提醒：两个文件夹数量不同，仅处理前 {pair_count} 对。")

        items: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for index in range(pair_count):
            video_a = videos_a[index]
            video_b = videos_b[index]
            log(f"合并第 {index + 1} 对：{video_a.name} + {video_b.name}")
            out_path = preset_dir / f"{video_a.stem}__{video_b.stem}.mp4"
            try:
                cap_a = cv2.VideoCapture(str(video_a))
                if not cap_a.isOpened():
                    raise RuntimeError(f"无法打开视频：{video_a.name}")
                fps = float(cap_a.get(cv2.CAP_PROP_FPS))
                width = int(cap_a.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap_a.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap_a.release()
                if fps <= 0 or width <= 0 or height <= 0:
                    raise RuntimeError(f"无法读取视频信息：{video_a.name}")

                writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
                try:
                    def write_part(video_path: Path) -> None:
                        cap = cv2.VideoCapture(str(video_path))
                        if not cap.isOpened():
                            raise RuntimeError(f"无法打开视频：{video_path.name}")
                        try:
                            while True:
                                ok, frame = cap.read()
                                if not ok:
                                    break
                                if (frame.shape[1], frame.shape[0]) != (width, height):
                                    frame = cv2.resize(frame, (width, height))
                                writer.write(frame)
                        finally:
                            cap.release()

                    write_part(video_a)
                    write_part(video_b)
                finally:
                    writer.release()

                items.append(
                    {
                        "source_a": str(video_a),
                        "source_b": str(video_b),
                        "output_video": str(out_path),
                        "preview_image": "",
                        "status": "done",
                        "detail": "双文件夹顺序合并",
                    }
                )
                log(f"完成：{out_path.name}")
            except Exception as exc:
                failures.append({"source_a": str(video_a), "source_b": str(video_b), "error": str(exc)})
                items.append(
                    {
                        "source_a": str(video_a),
                        "source_b": str(video_b),
                        "output_video": "",
                        "preview_image": "",
                        "status": "failed",
                        "detail": str(exc),
                    }
                )
                log(f"失败：{video_a.name} + {video_b.name} -> {exc}")
            finally:
                progress(index + 1, pair_count)

        manifest = {
            "job_id": job_id,
            "preset": preset.key,
            "output_dir": str(job_dir),
            "items": items,
            "failures": failures,
            "source_dir_a": str(source_dir_a),
            "source_dir_b": str(source_dir_b),
        }
        _write_manifest(job_dir, manifest)
        return {
            "job_id": job_id,
            "output_dir": str(job_dir),
            "items": items,
            "failures": failures,
            "total": pair_count,
            "summary_file": str(job_dir / "summary.csv"),
        }

    source_dir = _resolve_input_dir(str(payload.get("inputDir") or ""), path_style=path_style)
    result = _process_single_preset(
        preset=preset,
        source_dir=source_dir,
        preset_dir=preset_dir,
        log=log,
        progress=progress,
    )

    manifest = {
        "job_id": job_id,
        "preset": preset.key,
        "output_dir": str(job_dir),
        "source_dir": str(source_dir),
        "items": result["items"],
        "failures": result["failures"],
    }
    _write_manifest(job_dir, manifest)
    return {
        "job_id": job_id,
        "output_dir": str(job_dir),
        "items": result["items"],
        "failures": result["failures"],
        "total": result["total"],
        "summary_file": str(job_dir / "summary.csv"),
    }
