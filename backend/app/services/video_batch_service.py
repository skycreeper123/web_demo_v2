"""Persistent batches of distinct input groups, executed one flow at a time.

Lock order is always batch then flow. No lock is held while models or media run.
Creating a batch only validates and saves recipes; execution requires claim_batch.
"""
from __future__ import annotations

import copy
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Callable
import uuid

from web_demo.backend.app.core.config import project_root
from web_demo.backend.app.services import video_flow_service as flows


BATCH_KIND = "video_batch"
BATCH_ROOT = project_root() / "output" / "video_batches"
_LOCK = threading.RLock()
_ACTIVE: set[str] = set()
_ID = re.compile(r"^[a-f0-9]{16}$")
_ROW_FIELDS = {"name", "videoPath", "referenceImagePath", "referenceAlt1Path", "referenceAlt2Path", "startImagePath", "endImagePath", "cutSeconds", "editInstruction"}
_DEFAULT_FIELDS = _ROW_FIELDS | {"mode", "temporalMode", "spatialTarget", "promptSource", "keepAudio"}


def _directory(batch_id: str) -> Path:
    if not _ID.fullmatch(str(batch_id)):
        raise ValueError("批次编号无效。")
    return BATCH_ROOT / batch_id


def _save(batch: dict[str, Any]) -> None:
    directory = _directory(batch["id"])
    directory.mkdir(parents=True, exist_ok=True)
    batch["updatedAt"] = time.time()
    temporary = directory / "batch.json.tmp"
    temporary.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "batch.json")


def _load(batch_id: str) -> dict[str, Any]:
    path = _directory(batch_id) / "batch.json"
    if not path.is_file():
        raise FileNotFoundError("找不到此批次。")
    batch = json.loads(path.read_text(encoding="utf-8"))
    if batch["status"] == "running" and batch_id not in _ACTIVE:
        # Read authoritative child records: a claim with no dispatched work is
        # safe to continue, and a committed child result must not be rerun.
        _refresh_rows(batch)
        review = any(row.get("requiresReview") for row in batch["rows"])
        complete = all(row["status"] == "completed" for row in batch["rows"])
        error = ("服务曾重启，当前服务器任务结果未确认；请检查 Comfy 队列后再选择重试失败组。" if review else
                 "" if complete else "服务曾重启；已保存完成结果，可继续待执行组或重试失败组。")
        batch.update(status="interrupted" if review else "completed" if complete else "stopped",
                     requiresReview=review, error=error, currentRow=0)
        flows.release_batch_flows(batch_id)
        _save(batch)
    return batch


def _refresh_rows(batch: dict[str, Any]) -> None:
    """Use child state, not the worker's completed status for a single step."""
    for row in batch["rows"]:
        try:
            flow = flows.get_flow(row["flowId"])
            final = flow.get("artifacts", {}).get("final_video")
            final = final if final and Path(final["path"]).is_file() else None
            status = flow["status"]
            # A manually repaired child resolves its earlier batch warning.
            # Keep a dispatcher warning only while the observed child record
            # has not changed since the uncertain outcome was recorded.
            review = bool(flow.get("requiresReview") or (row.get("requiresReview") and
                          row.get("reviewFlowUpdatedAt") == flow.get("updatedAt")))
            # A batch claimed this row but its child has not started yet.
            if row["status"] == "running" and status not in {"running", "completed", "failed"} and batch["id"] in _ACTIVE:
                status = "running"
            if status == "completed":
                row.update(status="completed" if final else "failed",
                           error="" if final else "成片文件缺失，请重试此组以重新导出。")
                review = False
                row.pop("dispatchError", None)
            elif status == "failed":
                row.update(status="failed", error=str(flow.get("error") or "流程执行失败。"))
            elif status == "running":
                row.update(status="running", error="")
            elif row.get("dispatchError"):
                row.update(status="failed", error=row["dispatchError"])
            elif not review:
                row.update(status="pending", error="")
            row["finalVideo"] = copy.deepcopy(final)
            row["requiresReview"] = review
            active = next((step for step in flow["steps"] if step["status"] == "running"), None)
            row["activeStepTitle"] = active["title"] if active else ""
        except (OSError, ValueError, KeyError) as exc:
            row.update(status="failed", error=f"无法读取此组流程：{exc}", finalVideo=None, activeStepTitle="")


def _counts(batch: dict[str, Any]) -> dict[str, int]:
    return {"total": len(batch["rows"]), **{
        status: sum(row["status"] == status for row in batch["rows"])
        for status in ("completed", "failed", "pending", "running")
    }}


def _public(batch: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(batch)
    _refresh_rows(result)
    result["counts"] = _counts(result)
    result.update(result["counts"])
    result["requiresReview"] = any(row.get("requiresReview") for row in result["rows"])
    result["manifestUrl"] = f"/api/video-batches/{result['id']}/manifest.csv"
    result["logUrl"] = f"/api/video-batches/{result['id']}/logs"
    result["logDownloadUrl"] = f"/api/video-batches/{result['id']}/logs.txt"
    if result["status"] == "completed" and result["completed"] != result["total"]:
        result["status"] = "ready"
    if result["status"] == "interrupted" and not result["requiresReview"]:
        result["status"] = ("ready" if result["pending"] else "completed" if result["completed"] == result["total"]
                            else "partial" if result["completed"] else "failed")
        result["error"] = f"{result['failed']} 组失败，可重试失败组。" if result["failed"] else ""
    result.pop("runRows", None)
    return result


def get_batch(batch_id: str) -> dict[str, Any]:
    with _LOCK:
        return _public(_load(batch_id))


def list_batches() -> list[dict[str, Any]]:
    with _LOCK:
        batches = []
        if BATCH_ROOT.exists():
            for path in BATCH_ROOT.glob("*/batch.json"):
                try:
                    batch = _public(_load(path.parent.name))
                except (OSError, ValueError, KeyError):
                    continue
                batches.append({key: batch[key] for key in (
                    "id", "name", "mode", "temporalMode", "spatialTarget", "status", "error", "createdAt", "updatedAt",
                    "counts", "total", "completed", "failed", "pending", "running", "currentRow", "requiresReview",
                )})
        return sorted(batches, key=lambda item: item["updatedAt"], reverse=True)


def _remove_created(directory: Path, root: Path) -> None:
    # Only directories created by the current transaction may be rolled back.
    if directory.resolve().parent != root.resolve() or not _ID.fullmatch(directory.name):
        raise RuntimeError("拒绝清理任务目录之外的路径。")
    if directory.exists():
        shutil.rmtree(directory)


def create_batch(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("批次配置必须是对象。")
    defaults = payload.get("defaults")
    rows = payload.get("rows")
    if not isinstance(defaults, dict) or not isinstance(rows, list) or not rows:
        raise ValueError("请提供流程默认配置和至少一组素材；组数由导入素材决定。")
    if defaults.get("promptSource", "ai") != "ai":
        raise ValueError("批量流程仅支持 AI 自动生成提示词。")
    defaults = {key: value for key, value in defaults.items() if key in _DEFAULT_FIELDS}
    defaults["promptSource"] = "ai"
    batch_id = uuid.uuid4().hex[:16]
    recipes = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) - _ROW_FIELDS:
            raise ValueError(f"第 {index} 组只能覆盖素材路径、切点、编辑要求和名称；流程类型由默认配置统一指定。")
        try:
            overrides = {key: value for key, value in row.items()
                         if value is not None and not (isinstance(value, str) and not value.strip())}
            flow = flows.build_flow({**defaults, **overrides})
        except (ValueError, TypeError, OSError) as exc:
            raise ValueError(f"第 {index} 组：{exc}") from exc
        flow["batchId"] = batch_id
        recipes.append(flow)
    first = recipes[0]
    batch = {
        "id": batch_id, "name": str(payload.get("name") or f"{flows.MODES[first['mode']]} · {len(rows)} 组")[:160],
        "mode": first["mode"], "temporalMode": first["inputs"]["temporalMode"],
        "spatialTarget": first["inputs"]["spatialTarget"], "defaults": defaults,
        "createdAt": time.time(), "updatedAt": time.time(), "status": "draft", "error": "", "jobId": "",
        "stopRequested": False, "requiresReview": False, "currentRow": 0, "attempts": 0,
        "rows": [{"index": index, "name": flow["name"], "flowId": flow["id"], "status": "pending", "error": "",
                  "requiresReview": False, "finalVideo": None, "activeStepTitle": ""}
                 for index, flow in enumerate(recipes, 1)],
    }
    # Every row has been validated before the first directory is created. Hold
    # both locks until commit so list/read requests cannot see a partial batch.
    with _LOCK, flows._LOCK:
        created = []
        batch_directory = _directory(batch_id)
        if batch_directory.exists():
            raise RuntimeError("批次编号冲突，请重新创建。")
        try:
            for flow in recipes:
                directory = flows._directory(flow["id"])
                if directory.exists():
                    raise RuntimeError("流程编号冲突，请重新创建批次。")
                created.append(directory)
                flows._save(flow)
            _save(batch)
        except Exception:
            for directory in created:
                _remove_created(directory, flows.FLOW_ROOT)
            _remove_created(batch_directory, BATCH_ROOT)
            raise
        return _public(batch)


def claim_batch(batch_id: str, job_id: str, retry_failed: bool = False) -> dict[str, Any]:
    with _LOCK:
        if _ACTIVE:
            raise ValueError("服务器已有批次运行，请等待完成或停止后再启动另一批次。")
        batch = _load(batch_id)
        _refresh_rows(batch)
        requires_review = any(row.get("requiresReview") for row in batch["rows"])
        if requires_review and not retry_failed:
            raise ValueError("当前任务结果未确认，请检查 Comfy 队列后选择重试失败组。")
        selected = [row["index"] for row in batch["rows"]
                    if row["status"] == ("failed" if retry_failed else "pending")]
        if not selected:
            raise ValueError("没有待执行组；失败组请使用重试失败组，成功组会自动跳过。")
        flows.reserve_batch_flows(batch_id, [row["flowId"] for row in batch["rows"]])
        batch.update(status="running", jobId=job_id, stopRequested=False, requiresReview=False,
                     error="", currentRow=0, runRows=selected, attempts=batch.get("attempts", 0) + 1)
        for row in batch["rows"]:
            if row["index"] in selected:
                row["requiresReview"] = False
        _ACTIVE.add(batch_id)
        try:
            _save(batch)
        except Exception:
            _ACTIVE.discard(batch_id)
            flows.release_batch_flows(batch_id)
            raise
        return _public(batch)


def request_stop(batch_id: str) -> dict[str, Any]:
    with _LOCK:
        batch = _load(batch_id)
        if batch_id in _ACTIVE:
            batch["stopRequested"] = True
            if batch["currentRow"]:
                row = batch["rows"][batch["currentRow"] - 1]
                flows.request_stop(row["flowId"], batch_id=batch_id)
            _save(batch)
        return _public(batch)


def resolve_manifest(batch_id: str) -> Path:
    with _LOCK:
        batch = _public(_load(batch_id))
        path = _directory(batch_id) / "summary.csv"
        temporary = path.with_suffix(".csv.tmp")
        with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["index", "name", "flow_id", "status", "error", "final_video"])
            writer.writeheader()
            for row in batch["rows"]:
                writer.writerow({"index": row["index"], "name": row["name"], "flow_id": row["flowId"],
                                 "status": row["status"], "error": row["error"],
                                 "final_video": (row.get("finalVideo") or {}).get("path", "")})
        temporary.replace(path)
        return path


def resolve_log(batch_id: str) -> Path:
    with _LOCK:
        _load(batch_id)
        path = _directory(batch_id) / "batch.log"
        path.touch(exist_ok=True)
        return path


def read_logs(batch_id: str) -> list[str]:
    with _LOCK:
        path = resolve_log(batch_id)
        # Read backwards in blocks rather than loading an ever-growing log.
        with path.open("rb") as handle:
            handle.seek(0, 2)
            remaining = handle.tell()
            chunks: list[bytes] = []
            line_count = 0
            while remaining and line_count <= 1000:
                length = min(65536, remaining)
                remaining -= length
                handle.seek(remaining)
                chunk = handle.read(length)
                chunks.append(chunk)
                line_count += chunk.count(b"\n")
        return b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()[-1000:]


def run_batch(*, batch_id: str, job_id: str, log: Callable[[str], None],
              progress: Callable[[int, int], None], update_job: Callable[..., Any]) -> dict[str, Any]:
    original_log = log
    log_warning_sent = False

    def log(message: str) -> None:
        nonlocal log_warning_sent
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        lines = "".join(f"[{timestamp}] {line}\n" for line in (str(message).splitlines() or [""]))
        try:
            with _LOCK:
                with (_directory(batch_id) / "batch.log").open("a", encoding="utf-8") as handle:
                    handle.write(lines)
        except OSError as exc:
            if not log_warning_sent:
                log_warning_sent = True
                original_log(f"批次日志文件暂时无法保存：{exc}；任务日志仍会继续更新。")
        original_log(message)

    with _LOCK:
        batch = _load(batch_id)
        if batch_id not in _ACTIVE or batch["jobId"] != job_id:
            raise ValueError("请先取得此批次的执行权。")
        selected = list(batch["runRows"])
    try:
        log(f"开始批次：{batch['name']}；本次任务 {job_id}；待执行 {len(selected)} 组，共 {len(batch['rows'])} 组。")
        for index in selected:
            with _LOCK:
                batch = _load(batch_id)
                if batch.get("stopRequested"):
                    break
                row = batch["rows"][index - 1]
                batch["currentRow"] = index
                row.update(status="running", error="", requiresReview=False, dispatchError="")
                _save(batch)
                # Each group owns different staged Comfy input paths and trackers.
                child_job_id = f"{job_id}_{row['flowId']}"
                child = flows.get_flow(row["flowId"])
                restart_step = child["steps"][-1]["id"] if child["status"] == "completed" else ""
                try:
                    flows.claim_run(row["flowId"], child_job_id, restart_step, batch_id=batch_id)
                except Exception as exc:
                    row.update(status="failed", error=str(exc), dispatchError=str(exc))
                    _save(batch)
                    log(f"第 {index} 组启动失败：{exc}")
                    continue
            log(f"第 {index}/{len(batch['rows'])} 组：{row['name']}")

            def child_update(**changes: Any) -> None:
                # Child adapters must never replace the parent batch counters.
                if isinstance(changes.get("meta"), dict):
                    update_job(meta={**changes["meta"], "batch_id": batch_id, "batch_row": index, "flow_id": row["flowId"]})

            try:
                result = flows.run_flow_steps(
                    flow_id=row["flowId"], job_id=child_job_id, run_all=True,
                    log=lambda message: log(f"[{index}/{len(batch['rows'])}] {message}"),
                    progress=lambda *_: None, update_job=child_update,
                )
            except Exception as exc:
                # Unexpected adapter failure is not safe to classify as an
                # ordinary per-row model failure; stop dispatching more work.
                result = {"status": "failed", "error": str(exc), "requiresReview": True}
            with _LOCK:
                batch = _load(batch_id)
                row = batch["rows"][index - 1]
                child = flows.get_flow(row["flowId"])
                row.update(status="pending", error="", requiresReview=False)
                _refresh_rows(batch)
                if result.get("requiresReview") or child.get("requiresReview"):
                    error = str(result.get("error") or child.get("error") or "服务器任务结果未确认，请检查 Comfy 队列后重试。")
                    row.update(status="failed", error=error, requiresReview=True, reviewFlowUpdatedAt=child.get("updatedAt"))
                    batch.update(status="interrupted", requiresReview=True, error=error)
                elif child["status"] not in {"completed", "failed"}:
                    batch["stopRequested"] = True
                batch["currentRow"] = 0
                _save(batch)
                counts = _counts(batch)
            if row["status"] == "completed":
                log(f"第 {index} 组完成：{(row.get('finalVideo') or {}).get('path', '')}")
            elif row["status"] == "failed":
                log(f"第 {index} 组失败：{row['error']}")
            else:
                log(f"第 {index} 组中间步骤已保存，可继续执行。")
            progress(counts["completed"] + counts["failed"], counts["total"])
            if batch.get("requiresReview") or batch.get("stopRequested"):
                break
        with _LOCK:
            batch = _load(batch_id)
            _refresh_rows(batch)
            counts = _counts(batch)
            if batch.get("requiresReview"):
                batch["status"] = "interrupted"
            elif batch.get("stopRequested"):
                batch.update(status="stopped", error="已在当前步骤结束后停止；已完成步骤已保存，可继续剩余组。")
            else:
                batch["status"] = ("ready" if counts["pending"] else "completed" if counts["completed"] == counts["total"]
                                   else "partial" if counts["completed"] else "failed")
                batch["error"] = "" if not counts["failed"] else f"{counts['failed']} 组失败，可单独重试失败组。"
            batch["currentRow"] = 0
            _save(batch)
    except Exception as exc:
        with _LOCK:
            batch = _load(batch_id)
            if batch.get("currentRow"):
                row = batch["rows"][batch["currentRow"] - 1]
                row.update(status="failed", error=str(exc), requiresReview=True)
                try:
                    row["reviewFlowUpdatedAt"] = flows.get_flow(row["flowId"])["updatedAt"]
                except (OSError, ValueError, KeyError):
                    pass
            batch.update(status="interrupted", requiresReview=bool(batch.get("currentRow")), error=str(exc), currentRow=0)
            _save(batch)
        log(f"批次已停止：{exc}")
    finally:
        with _LOCK:
            _ACTIVE.discard(batch_id)
            flows.release_batch_flows(batch_id)
    snapshot = get_batch(batch_id)
    counts = snapshot["counts"]
    items = [row["finalVideo"] for row in snapshot["rows"] if row.get("finalVideo")]
    failures = [{"row_index": row["index"], "flow_id": row["flowId"], "message": row["error"]}
                for row in snapshot["rows"] if row["status"] == "failed"]
    log(f"批次本次执行结束：{snapshot['status']}；已完成 {counts['completed']} 组，失败 {counts['failed']} 组，待执行 {counts['pending']} 组；任务 {job_id}。")
    status = "completed" if snapshot["status"] == "completed" else "partial" if counts["completed"] or snapshot["status"] == "stopped" else "failed"
    return {"status": status, "items": items, "failures": failures, "error": snapshot["error"],
            "total": counts["total"], "progress": counts["completed"] + counts["failed"],
            "output_dir": str(_directory(batch_id)), "requiresReview": snapshot["requiresReview"],
            "summary_file": str(resolve_manifest(batch_id))}
