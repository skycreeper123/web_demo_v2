from __future__ import annotations

from pathlib import Path
from typing import Any

from .path_resolver import resolve_comfy_output_dir


MEDIA_KEYS = ("videos", "gifs", "images", "files")
MEDIA_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif")
# 主输出优先级只用于“结果文件选择”，不代表编码本身是否无损。
VIDEO_SUFFIX_PRIORITY = {
    ".mkv": 0,
    ".mov": 1,
    ".mp4": 2,
    ".m4v": 3,
    ".webm": 4,
    ".avi": 5,
    ".gif": 50,
}
IMAGE_SUFFIX_PRIORITY = {
    ".png": 100,
    ".webp": 101,
    ".jpg": 102,
    ".jpeg": 103,
}


def extract_execution_error(record: dict[str, Any]) -> dict[str, Any]:
    """Extract ComfyUI's node-level execution_error event from /history.

    ComfyUI has returned slightly different shapes over time (and custom
    servers sometimes put the event under ``status.messages`` or a top-level
    ``messages`` list), so this deliberately accepts both tuple/list and dict
    representations and keeps the useful diagnostic fields verbatim.
    """
    status = record.get("status") if isinstance(record.get("status"), dict) else {}
    containers = [status.get("messages"), record.get("messages"), record.get("events")]
    for container in containers:
        if not isinstance(container, list):
            continue
        for item in container:
            event_type = ""
            payload: Any = None
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                event_type, payload = str(item[0] or ""), item[1]
            elif isinstance(item, dict):
                event_type = str(item.get("type") or item.get("event") or "")
                payload = item.get("data") if "data" in item else item
            if event_type != "execution_error" or not isinstance(payload, dict):
                continue
            detail: dict[str, Any] = {}
            for key in (
                "prompt_id", "node_id", "node_type", "exception_type",
                "exception_message", "traceback", "current_inputs", "current_outputs",
                "timestamp",
            ):
                if key in payload and payload[key] not in (None, "", [], {}):
                    detail[key] = payload[key]
            return detail
    return {}


def _history_record(history_payload: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    if prompt_id in history_payload and isinstance(history_payload[prompt_id], dict):
        return history_payload[prompt_id]
    if isinstance(history_payload.get("data"), dict):
        return history_payload["data"]
    return history_payload


def summarize_history_state(history_payload: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    record = _history_record(history_payload, prompt_id)
    status = record.get("status") if isinstance(record.get("status"), dict) else {}
    status_str = str(status.get("status_str") or "").strip().lower()
    completed = bool(status.get("completed", False))
    outputs = record.get("outputs") if isinstance(record.get("outputs"), dict) else {}

    if outputs:
        return {"state": "SUCCEEDED", "record": record}
    if status_str in {"error", "failed"}:
        message = str(status.get("error") or status.get("messages") or "ComfyUI execution failed")
        detail = extract_execution_error(record)
        if detail.get("exception_message"):
            message = str(detail["exception_message"])
        return {"state": "FAILED", "record": record, "message": message, "detail": detail}
    if completed and not outputs:
        return {"state": "FAILED", "record": record, "message": "ComfyUI completed without outputs.", "detail": {}}
    return {"state": "PENDING", "record": record}


def _candidate_files_from_history(record: dict[str, Any], output_root: Path) -> list[Path]:
    outputs = record.get("outputs") if isinstance(record.get("outputs"), dict) else {}
    candidates: list[Path] = []
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key in MEDIA_KEYS:
            value = node_output.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "").strip()
                subfolder = str(item.get("subfolder") or "").strip()
                if not filename:
                    continue
                path = output_root / subfolder / filename if subfolder else output_root / filename
                candidates.append(path)
    return candidates


def _candidate_files_from_prefix(output_root: Path, output_prefix: str) -> list[Path]:
    text = str(output_prefix or "").strip().replace("\\", "/")
    if not text:
        return []
    prefix_path = Path(text)
    search_root = output_root / prefix_path.parent if prefix_path.parent.as_posix() not in {"", "."} else output_root
    stem = prefix_path.name
    if not search_root.exists():
        return []
    results: list[Path] = []
    for path in search_root.glob(f"{stem}*"):
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES:
            results.append(path)
    return sorted(results)


def _candidate_sort_key(path: Path) -> tuple[int, int, str]:
    suffix = path.suffix.lower()
    if suffix in VIDEO_SUFFIX_PRIORITY:
        group = 0
        rank = VIDEO_SUFFIX_PRIORITY[suffix]
    else:
        group = 1
        rank = IMAGE_SUFFIX_PRIORITY.get(suffix, 999)
    try:
        size_rank = -path.stat().st_size
    except OSError:
        size_rank = 0
    return (group + rank, size_rank, path.name.lower())


def collect_result(
    *,
    history_payload: dict[str, Any],
    prompt_id: str,
    output_prefix: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    summary = summarize_history_state(history_payload, prompt_id)
    if summary["state"] != "SUCCEEDED":
        raise RuntimeError(summary.get("message") or "ComfyUI result is not ready.")

    output_root = resolve_comfy_output_dir(config)
    record = summary["record"]
    candidates = _candidate_files_from_history(record, output_root)
    if not candidates:
        candidates = _candidate_files_from_prefix(output_root, output_prefix)
    if not candidates:
        raise RuntimeError("未能在 ComfyUI 输出目录中定位结果文件。")

    existing = [path for path in candidates if path.exists() and path.is_file()]
    if not existing:
        raise RuntimeError("结果文件不存在或不可读。")

    # 先按“视频优先、较大的成片优先”排序，尽量避免把预览图或中间图当主输出。
    existing.sort(key=_candidate_sort_key)
    primary = existing[0]
    items = [{"name": path.name, "path": str(path)} for path in existing]
    return {
        "output_path": str(primary),
        "output_dir": str(primary.parent),
        "items": items,
    }
