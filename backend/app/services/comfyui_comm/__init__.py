from __future__ import annotations

import csv
import json
from pathlib import Path
import time
from typing import Any, Callable

from web_demo.backend.app.core.config import is_absolute_path_text, load_comfy_config, normalize_path_style

from .input_stager import stage_input_files
from .job_monitor import ComfyJobRegistry, ComfyWebSocketManager
from .result_collector import collect_result, summarize_history_state
from .server_client import ComfyServerClient
from .workflow_binder import bind_workflow, list_workflow_templates, resolve_template_payload


COMFY_JOB_KIND = "comfy_video"
JOB_REGISTRY = ComfyJobRegistry()
WS_MANAGER = ComfyWebSocketManager(JOB_REGISTRY)


def _resolve_csv_source_path(root_dir: str | None, name: str | None, *, path_style: str = "") -> str:
    root_text = str(root_dir or "").strip()
    name_text = str(name or "").strip()
    if not root_text or not name_text:
        return ""
    root_path = Path(root_text)
    if is_absolute_path_text(root_text, path_style):
        return str(root_path / name_text)
    return str((root_path / name_text).resolve())


def _parse_params_json(text: str | None) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("params_json must be a JSON object.")
    return value


def _format_bytes(size: Any) -> str:
    value = float(size or 0)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def _load_csv_rows(csv_path: str, *, path_style: str = "") -> list[dict[str, str]]:
    path = Path(csv_path)
    if not is_absolute_path_text(csv_path, path_style):
        path = path.resolve()
    if not path.exists():
        raise RuntimeError(f"CSV 文件不存在：{path}")
    if not path.is_file():
        raise RuntimeError(f"CSV 路径不是文件：{path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [{str(key or "").strip(): str(value or "").strip() for key, value in row.items()} for row in reader]
    if not rows:
        raise RuntimeError("CSV 中没有可执行的任务行。")
    return rows


def _select_csv_rows(rows: list[dict[str, str]], payload: dict[str, Any]) -> list[tuple[int, dict[str, str]]]:
    requested = payload.get("rowIndices")
    if not requested:
        return list(enumerate(rows, start=1))
    if not isinstance(requested, list):
        raise RuntimeError("rowIndices must be an array of row numbers.")

    selected: set[int] = set()
    for item in requested:
        try:
            index = int(item)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid row index: {item}") from exc
        if index <= 0:
            raise RuntimeError(f"Row index must be positive: {index}")
        selected.add(index)

    filtered = [(row_index, row) for row_index, row in enumerate(rows, start=1) if row_index in selected]
    if not filtered:
        raise RuntimeError("No CSV rows matched the requested rowIndices.")
    return filtered


def _build_failure(
    *,
    row_index: int,
    name: str,
    stage: str,
    error_code: str,
    message: str,
    retryable: bool,
    prompt_id: str = "",
    detail: Any | None = None,
) -> dict[str, Any]:
    failure = {
        "row_index": row_index,
        "name": name,
        "stage": stage,
        "error_code": error_code,
        "message": str(message or "").strip() or error_code,
        "retryable": bool(retryable),
    }
    if prompt_id:
        failure["prompt_id"] = prompt_id
    if detail not in (None, "", [], {}):
        failure["detail"] = detail
    return failure


def _build_row_payload(
    *,
    parent_job_id: str,
    row_index: int,
    row: dict[str, str],
    payload: dict[str, Any],
    template_payload: dict[str, Any],
) -> dict[str, Any]:
    path_style = normalize_path_style(payload.get("pathStyle"))
    image_path = row.get("image_path") or _resolve_csv_source_path(
        payload.get("imageRootDir"),
        row.get("image_name"),
        path_style=path_style,
    )
    video_path = row.get("video_path") or _resolve_csv_source_path(
        payload.get("videoRootDir"),
        row.get("video_name"),
        path_style=path_style,
    )
    positive_prompt = row.get("positive_prompt") or ""
    negative_prompt = row.get("negative_prompt") or ""
    row_params = _parse_params_json(row.get("params_json"))
    default_params = payload.get("defaultParams") if isinstance(payload.get("defaultParams"), dict) else {}
    merged_params = {**default_params, **row_params}
    requested_prompt_id = f"{parent_job_id}_{row_index:04d}"
    output_prefix = row.get("output_prefix") or ""
    if not output_prefix:
        explicit_prefix_base = str(payload.get("defaultOutputPrefixBase") or "").strip()
        if explicit_prefix_base:
            output_prefix = f"{explicit_prefix_base.rstrip('/')}/row_{row_index:04d}"
        else:
            output_prefix = f"video/jobs/{parent_job_id}/row_{row_index:04d}"

    seed_text = row.get("seed") or ""
    seed = int(seed_text) if seed_text else payload.get("defaultSeed")
    workflow_type = str(
        payload.get("workflowType") or row.get("workflow_type") or template_payload.get("workflow_type") or ""
    ).strip()
    return {
        "requestedPromptId": requested_prompt_id,
        "workflowType": workflow_type,
        "positivePrompt": positive_prompt,
        "negativePrompt": negative_prompt,
        "imagePath": image_path,
        "videoPath": video_path,
        "seed": seed,
        "outputPrefix": output_prefix,
        "params": merged_params,
        "rowIndex": row_index,
        "rowData": row,
    }


def list_comfy_templates(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return list_workflow_templates(config or load_comfy_config())


def comfy_health(config: dict[str, Any] | None = None) -> dict[str, Any]:
    active_config = config or load_comfy_config()
    client = ComfyServerClient(active_config)
    status = client.health()
    if bool(active_config.get("ws_enabled", True)):
        client_id = WS_MANAGER.ensure_started(active_config)
        status["ws"] = {
            "enabled": True,
            "client_id": client_id,
            "connected": WS_MANAGER.is_connected(),
        }
    else:
        status["ws"] = {
            "enabled": False,
            "client_id": "",
            "connected": False,
        }
    return status


def cancel_comfy_job(job_id: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    active_config = config or load_comfy_config()
    client = ComfyServerClient(active_config)
    tracker = JOB_REGISTRY.get(job_id)
    if tracker is None:
        raise RuntimeError("ComfyUI job tracker not found.")

    JOB_REGISTRY.mark_cancel_requested(job_id)
    if not tracker.prompt_id:
        return {"ok": True, "job_id": job_id, "message": "Cancel requested before prompt submission."}

    if tracker.state in {"CREATED", "SUBMITTED", "QUEUED"}:
        client.post_queue_delete([tracker.prompt_id])
        return {"ok": True, "job_id": job_id, "prompt_id": tracker.prompt_id, "message": "Queued job deletion requested."}

    client.post_interrupt()
    return {"ok": True, "job_id": job_id, "prompt_id": tracker.prompt_id, "message": "Interrupt requested."}


def run_comfy_job(
    *,
    job_id: str,
    payload: dict[str, Any],
    log: Callable[[str], None],
    progress: Callable[[int, int], None],
    update_job: Callable[..., Any],
) -> dict[str, Any]:
    config = load_comfy_config()
    timeout_seconds = int(config.get("job_timeout_sec") or 1800)
    poll_interval = max(1, int(config.get("poll_interval_sec") or 2))
    path_style = normalize_path_style(payload.get("pathStyle") or config.get("path_style"))
    tracker = JOB_REGISTRY.register(job_id)
    client = ComfyServerClient(config)
    csv_path = str(payload.get("csvPath") or "").strip()
    if not csv_path:
        raise RuntimeError("请提供 CSV 文件路径。")

    log("Checking ComfyUI health...")
    health = comfy_health(config)
    update_job(meta={"comfy_health": health})
    log("Loading CSV rows...")
    rows = _load_csv_rows(csv_path, path_style=path_style)
    selected_rows = _select_csv_rows(rows, payload)
    update_job(
        meta={
            "csv_path": csv_path,
            "row_count": len(rows),
            "selected_row_count": len(selected_rows),
            "selected_row_indices": [row_index for row_index, _ in selected_rows],
        }
    )

    log("Resolving workflow template...")
    template_payload = resolve_template_payload(payload, config)

    client_id = ""
    if bool(config.get("ws_enabled", True)):
        client_id = WS_MANAGER.ensure_started(config, log=log)
        if WS_MANAGER.is_connected():
            log("ComfyUI WebSocket listener is connected.")
        else:
            log("ComfyUI WebSocket is starting; HTTP polling will still monitor the job.")
    else:
        log("ComfyUI WebSocket is disabled; using HTTP polling only.")

    outputs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    final_output_dir = ""
    total_rows = len(selected_rows)

    for current_index, (row_index, row) in enumerate(selected_rows, start=1):
        tracker = JOB_REGISTRY.get(job_id) or tracker
        if tracker.cancel_requested:
            log("Batch cancelled before submitting the next row.")
            return {
                "status": "cancelled",
                "job_id": job_id,
                "output_dir": final_output_dir,
                "items": outputs,
                "failures": failures,
                "total": total_rows,
            }

        row_payload = _build_row_payload(
            parent_job_id=job_id,
            row_index=row_index,
            row=row,
            payload=payload,
            template_payload=template_payload,
        )
        display_name = row.get("video_name") or row.get("image_name") or row.get("video_path") or row.get("image_path") or f"row_{row_index:04d}"
        log(f"[{current_index}/{total_rows}] Preparing inputs for {display_name} (CSV row {row_index})")

        try:
            staged_inputs = stage_input_files(row_payload["requestedPromptId"], row_payload, config)
        except Exception as exc:
            failures.append(
                _build_failure(
                    row_index=row_index,
                    name=display_name,
                    stage="INPUT_PREPARE",
                    error_code="INPUT_STAGE_FAILED",
                    message=str(exc),
                    retryable=False,
                )
            )
            log(f"[{current_index}/{total_rows}] Input prepare failed: {exc}")
            progress(current_index, total_rows)
            continue

        if staged_inputs.get("image_ref"):
            log(
                f"[{current_index}/{total_rows}] Staged image: {staged_inputs.get('image_source')} -> "
                f"{staged_inputs['image_ref']} ({_format_bytes(staged_inputs.get('image_bytes'))})"
            )
        if staged_inputs.get("video_ref"):
            log(
                f"[{current_index}/{total_rows}] Staged video: {staged_inputs.get('video_source')} -> "
                f"{staged_inputs['video_ref']} ({_format_bytes(staged_inputs.get('video_bytes'))})"
            )

        try:
            workflow = bind_workflow(
                payload=row_payload,
                staged_inputs=staged_inputs,
                template_payload=template_payload,
            )
        except Exception as exc:
            failures.append(
                _build_failure(
                    row_index=row_index,
                    name=display_name,
                    stage="WORKFLOW_BIND",
                    error_code="WORKFLOW_BIND_FAILED",
                    message=str(exc),
                    retryable=False,
                )
            )
            log(f"[{current_index}/{total_rows}] Workflow bind failed: {exc}")
            progress(current_index, total_rows)
            continue

        requested_prompt_id = str(row_payload.get("requestedPromptId") or "").strip() or None
        try:
            submit_response = client.post_prompt(workflow, client_id=client_id or "local-app", prompt_id=requested_prompt_id)
        except Exception as exc:
            failures.append(
                _build_failure(
                    row_index=row_index,
                    name=display_name,
                    stage="SUBMIT",
                    error_code="SUBMIT_FAILED",
                    message=str(exc),
                    retryable=True,
                )
            )
            log(f"[{current_index}/{total_rows}] Submit failed: {exc}")
            progress(current_index, total_rows)
            continue

        prompt_id = str(submit_response.get("prompt_id") or "").strip()
        if not prompt_id:
            failures.append(
                _build_failure(
                    row_index=row_index,
                    name=display_name,
                    stage="SUBMIT",
                    error_code="PROMPT_ID_MISSING",
                    message="ComfyUI returned an empty prompt_id.",
                    retryable=True,
                )
            )
            progress(current_index, total_rows)
            continue
        if requested_prompt_id and prompt_id != requested_prompt_id:
            failures.append(
                _build_failure(
                    row_index=row_index,
                    name=display_name,
                    stage="SUBMIT",
                    error_code="PROMPT_ID_UNEXPECTED",
                    message=f"unexpected prompt_id: {prompt_id}",
                    retryable=True,
                    prompt_id=prompt_id,
                )
            )
            progress(current_index, total_rows)
            continue

        JOB_REGISTRY.attach_prompt(job_id, prompt_id)
        JOB_REGISTRY.reset_progress(job_id)
        update_job(meta={"prompt_id": prompt_id, "current_row": row_index, "current_name": display_name})
        log(f"[{current_index}/{total_rows}] Submitted to ComfyUI. prompt_id={prompt_id}")

        deadline = time.time() + timeout_seconds
        last_node = ""
        last_progress_percent = -1
        next_history_check = 0.0
        next_queue_check = 0.0
        row_completed = False

        while time.time() < deadline:
            tracker = JOB_REGISTRY.get(job_id) or tracker
            if tracker.current_node and tracker.current_node != last_node:
                last_node = tracker.current_node
                log(f"[{current_index}/{total_rows}] Running node: {tracker.current_node}")
                update_job(meta={"current_node": tracker.current_node})

            progress_max = int(tracker.progress_max or 0)
            if progress_max > 0:
                percent = min(100, int(tracker.progress_value * 100 / progress_max))
                if percent != last_progress_percent and (
                    last_progress_percent < 0
                    or percent - last_progress_percent >= 10
                    or percent >= 100
                ):
                    log(
                        f"[{current_index}/{total_rows}] Node progress: "
                        f"{tracker.current_node or last_node or '?'} "
                        f"{int(tracker.progress_value)}/{progress_max} ({percent}%)"
                    )
                    update_job(
                        meta={
                            "node_progress_value": int(tracker.progress_value),
                            "node_progress_max": progress_max,
                            "node_progress_percent": percent,
                        }
                    )
                    last_progress_percent = percent

            if tracker.cancel_requested and tracker.interrupted:
                log("ComfyUI batch was interrupted.")
                return {
                    "status": "cancelled",
                    "job_id": job_id,
                    "output_dir": final_output_dir,
                    "items": outputs,
                    "failures": failures,
                    "total": total_rows,
                }

            now = time.time()
            if now >= next_queue_check:
                try:
                    queue_payload = client.get_queue()
                    pending = len(queue_payload.get("queue_pending") or []) if isinstance(queue_payload.get("queue_pending"), list) else 0
                    running = len(queue_payload.get("queue_running") or []) if isinstance(queue_payload.get("queue_running"), list) else 0
                    update_job(meta={"queue_pending": pending, "queue_running": running})
                except Exception as exc:
                    log(f"[{current_index}/{total_rows}] Queue sync warning: {exc}")
                next_queue_check = now + poll_interval

            if now >= next_history_check:
                try:
                    history_payload = client.get_history(prompt_id)
                    summary = summarize_history_state(history_payload, prompt_id)
                except Exception as exc:
                    log(f"[{current_index}/{total_rows}] History polling warning: {exc}")
                    next_history_check = now + poll_interval
                    time.sleep(0.5)
                    continue
                if summary["state"] == "SUCCEEDED":
                    try:
                        result = collect_result(
                            history_payload=history_payload,
                            prompt_id=prompt_id,
                            output_prefix=str(row_payload.get("outputPrefix") or ""),
                            config=config,
                        )
                        final_output_dir = result["output_dir"]
                        primary_path = result["output_path"]
                        outputs.append(
                            {
                                "name": Path(primary_path).name,
                                "path": primary_path,
                                "row_index": row_index,
                                "source_name": display_name,
                                "prompt_id": prompt_id,
                            }
                        )
                        update_job(meta={"result_path": primary_path})
                        log(f"[{current_index}/{total_rows}] Collected result: {primary_path}")
                    except Exception as exc:
                        failures.append(
                            _build_failure(
                                row_index=row_index,
                                name=display_name,
                                stage="RESULT_FETCH",
                                error_code="RESULT_FETCH_FAILED",
                                message=str(exc),
                                retryable=True,
                                prompt_id=prompt_id,
                            )
                        )
                        log(f"[{current_index}/{total_rows}] Result fetch failed: {exc}")
                    row_completed = True
                    break
                if summary["state"] == "FAILED":
                    message = summary.get("message") or "ComfyUI execution failed."
                    detail = summary.get("detail") if isinstance(summary.get("detail"), dict) else {}
                    if detail:
                        node_id = detail.get("node_id", "?")
                        node_type = detail.get("node_type", "?")
                        exception_type = detail.get("exception_type", "")
                        log(
                            f"[{current_index}/{total_rows}] ComfyUI node error: "
                            f"node_id={node_id} node_type={node_type} exception_type={exception_type}"
                        )
                        if detail.get("traceback"):
                            log(f"[{current_index}/{total_rows}] ComfyUI traceback: {detail['traceback']}")
                    failures.append(
                        _build_failure(
                            row_index=row_index,
                            name=display_name,
                            stage="RUNNING",
                            error_code="EXECUTION_FAILED",
                            message=message,
                            retryable=True,
                            prompt_id=prompt_id,
                            detail=detail,
                        )
                    )
                    log(f"[{current_index}/{total_rows}] Failed: {message}")
                    row_completed = True
                    break
                next_history_check = now + poll_interval

            time.sleep(0.5)

        if not row_completed:
            failures.append(
                _build_failure(
                    row_index=row_index,
                    name=display_name,
                    stage="TIMEOUT",
                    error_code="JOB_TIMEOUT",
                    message=f"timeout after {timeout_seconds}s",
                    retryable=True,
                    prompt_id=prompt_id,
                )
            )
            log(f"[{current_index}/{total_rows}] Timed out.")
        progress(current_index, total_rows)

    if outputs and failures:
        status = "partial"
    elif outputs:
        status = "completed"
    else:
        status = "failed"
    if tracker.cancel_requested:
        status = "cancelled"
    return {
        "status": status,
        "job_id": job_id,
        "output_dir": final_output_dir,
        "items": outputs,
        "failures": failures,
        "total": total_rows,
        "error": failures[0]["message"] if failures else "",
    }
