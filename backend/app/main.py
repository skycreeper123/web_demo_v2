from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[3]))

from web_demo.backend.app.core.config import (  # noqa: E402
    IMAGE_PROMPT_KIND,
    IMAGE_EDIT_PROMPT_KIND,
    VIDEO_PROMPT_KIND,
    api_config_path,
    comfy_config_path,
    default_output_root,
    load_api_config,
    load_comfy_config,
    load_defaults,
    load_prompt_config,
    project_relative_path_text,
    prompt_config_path,
    resolve_output_path,
    save_api_config,
    save_comfy_config,
    save_prompt_config,
)
from web_demo.backend.app.services.comfyui_comm.path_resolver import resolve_workflow_manifest_dir  # noqa: E402
from web_demo.backend.app.services.comfyui_comm import (  # noqa: E402
    COMFY_JOB_KIND,
    cancel_comfy_job,
    comfy_health,
    list_comfy_templates,
    run_comfy_job,
)
from web_demo.backend.app.services.prompt_generator import run_image_generation  # noqa: E402
from web_demo.backend.app.services.image_edit_prompt_generator import run_image_edit_generation  # noqa: E402
from web_demo.backend.app.services.video_matcher import build_video_matches  # noqa: E402
from web_demo.backend.app.services.video_clip_service import (  # noqa: E402
    list_clip_presets,
    run_video_clip_job,
)
from web_demo.backend.app.services.video_prompt_generator import run_video_generation  # noqa: E402
from web_demo.backend.app.utils.file_writer import ensure_dir  # noqa: E402
from web_demo.backend.app.utils.logging_utils import (  # noqa: E402
    get_job_log_path,
    get_job_logger,
    setup_logging,
)


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
DEFAULTS = load_defaults()
APP_LOGGER = logging.getLogger("web_demo.app")
HTTP_LOGGER = logging.getLogger("web_demo.http")
# SQLite 任务状态库，负责持久化任务快照、日志、输出和失败详情。
JOB_DATABASE_PATH = Path(__file__).resolve().parents[2] / "jobs.sqlite3"


@dataclass
class JobState:
    # JobState 是前后端共享的任务快照，前端轮询时直接读取这一份结构。
    id: str
    kind: str
    status: str = "queued"
    progress: int = 0
    total: int = 0
    logs: list[str] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    output_dir: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    log_file: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0


def _infer_log_level(message: str) -> int:
    # 根据文本前缀自动推断日志级别，避免每次写日志都手动指定 level。
    normalized = str(message or "").strip().lower()
    if not normalized:
        return logging.INFO
    if normalized.startswith(("failed", "error", "exception", "traceback", "timed out")):
        return logging.ERROR
    if normalized.startswith(("warn", "warning", "reminder")):
        return logging.WARNING
    return logging.INFO


class JobStore:
    def __init__(self, database_path: Path = JOB_DATABASE_PATH) -> None:
        # 内存缓存用于快速读取，SQLite 用于持久化和重启恢复。
        self._lock = threading.Lock()
        self._jobs: dict[str, JobState] = {}
        self._database_path = database_path
        self._initialize_database()
        self._restore_jobs()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize_database(self) -> None:
        # 第一次启动时创建表结构；WAL 模式能提高并发读写的稳定性。
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    logs_json TEXT NOT NULL,
                    outputs_json TEXT NOT NULL,
                    failures_json TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    error TEXT NOT NULL,
                    meta_json TEXT NOT NULL,
                    log_file TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL NOT NULL,
                    finished_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _decode_json(value: str, fallback: Any) -> Any:
        try:
            decoded = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback
        return decoded if isinstance(decoded, type(fallback)) else fallback

    def _restore_jobs(self) -> None:
        # 启动时从 SQLite 恢复历史任务；未完成任务会被降级为失败态。
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()

        restored: dict[str, JobState] = {}
        interrupted_ids: list[str] = []
        active_statuses = {"queued", "running"}
        for row in rows:
            job = JobState(
                id=str(row["id"]),
                kind=str(row["kind"]),
                status=str(row["status"]),
                progress=int(row["progress"]),
                total=int(row["total"]),
                logs=self._decode_json(row["logs_json"], []),
                outputs=self._decode_json(row["outputs_json"], []),
                failures=self._decode_json(row["failures_json"], []),
                output_dir=str(row["output_dir"]),
                error=str(row["error"]),
                meta=self._decode_json(row["meta_json"], {}),
                log_file=str(row["log_file"]),
                created_at=float(row["created_at"]),
                started_at=float(row["started_at"]),
                finished_at=float(row["finished_at"]),
            )
            if job.status in active_statuses:
                job.status = "failed"
                job.error = "The application stopped before this task finished."
                job.finished_at = time.time()
                job.logs.append("Recovered after restart: marked failed because the worker is no longer running.")
                interrupted_ids.append(job.id)
            restored[job.id] = job

        with self._lock:
            self._jobs = restored
        for job_id in interrupted_ids:
            self._persist(self._jobs[job_id])

    def _persist(self, job: JobState) -> None:
        # 每次状态变更都写回整份快照，保证实现简单且可恢复。
        payload = (
            job.id,
            job.kind,
            job.status,
            job.progress,
            job.total,
            json.dumps(job.logs, ensure_ascii=False, default=str),
            json.dumps(job.outputs, ensure_ascii=False, default=str),
            json.dumps(job.failures, ensure_ascii=False, default=str),
            job.output_dir,
            job.error,
            json.dumps(job.meta, ensure_ascii=False, default=str),
            job.log_file,
            job.created_at,
            job.started_at,
            job.finished_at,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, kind, status, progress, total, logs_json, outputs_json, failures_json,
                    output_dir, error, meta_json, log_file, created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    status = excluded.status,
                    progress = excluded.progress,
                    total = excluded.total,
                    logs_json = excluded.logs_json,
                    outputs_json = excluded.outputs_json,
                    failures_json = excluded.failures_json,
                    output_dir = excluded.output_dir,
                    error = excluded.error,
                    meta_json = excluded.meta_json,
                    log_file = excluded.log_file,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at
                """,
                payload,
            )

    def create(self, *, kind: str, total: int) -> JobState:
        # 创建任务时同时生成日志文件路径，并把初始快照写入数据库。
        job_id = uuid.uuid4().hex[:12]
        job = JobState(
            id=job_id,
            kind=kind,
            total=total,
            log_file=str(get_job_log_path(job_id)),
        )
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
        get_job_logger(job.id, kind).info("Job created. kind=%s total=%s log_file=%s", kind, total, job.log_file)
        return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: Any) -> JobState:
        # 更新任务字段后立即持久化，避免任务中途退出导致状态丢失。
        with self._lock:
            job = self._jobs[job_id]
            previous_status = job.status
            previous_error = job.error
            previous_output_dir = job.output_dir
            for key, value in changes.items():
                setattr(job, key, value)
            kind = job.kind
            new_status = job.status
            new_error = job.error
            new_output_dir = job.output_dir
            self._persist(job)
        job_logger = get_job_logger(job_id, kind)
        if "status" in changes and new_status != previous_status:
            job_logger.info("Status changed: %s -> %s", previous_status, new_status)
        if "error" in changes and new_error and new_error != previous_error:
            job_logger.error("Job error: %s", new_error)
        if "output_dir" in changes and new_output_dir and new_output_dir != previous_output_dir:
            job_logger.info("Output directory: %s", new_output_dir)
        return job

    def append_log(self, job_id: str, message: str, level: int | None = None) -> None:
        # 日志既写入任务快照，也写入单独的任务日志文件。
        text = str(message or "").strip()
        if not text:
            return
        with self._lock:
            job = self._jobs[job_id]
            job.logs.append(text)
            kind = job.kind
            self._persist(job)
        get_job_logger(job_id, kind).log(level if level is not None else _infer_log_level(text), text)

    def replace_outputs(self, job_id: str, outputs: list[dict[str, Any]]) -> None:
        # 输出文件列表用于前端“结果文件”区域和文件下载接口。
        with self._lock:
            job = self._jobs[job_id]
            job.outputs = outputs
            self._persist(job)

    def replace_failures(self, job_id: str, failures: list[dict[str, Any]]) -> None:
        # 失败项保留行号、阶段和错误码，方便失败续跑与导出。
        with self._lock:
            job = self._jobs[job_id]
            job.failures = failures
            self._persist(job)

    def merge_meta(self, job_id: str, **changes: Any) -> JobState:
        # meta 保存运行时上下文，例如原始提交参数、Comfy 健康检查和当前行号。
        with self._lock:
            job = self._jobs[job_id]
            merged = dict(job.meta)
            for key, value in changes.items():
                if key == "meta" and isinstance(value, dict):
                    merged.update(value)
                else:
                    merged[key] = value
            job.meta = merged
            self._persist(job)
            return job

    def has_active_jobs(self) -> bool:
        # 只有没有活动任务时，浏览器会话断开才允许自动关闭服务。
        terminal_statuses = {"completed", "partial", "failed", "cancelled", "timeout"}
        with self._lock:
            return any(job.status not in terminal_statuses for job in self._jobs.values())


STORE = JobStore()


class BrowserSessionStore:
    def __init__(self) -> None:
        # 浏览器会话用于前端连接状态记录，不参与业务任务状态保存。
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}
        self._had_browser_session = False

    def register(self, session_id: str) -> None:
        now = time.time()
        with self._lock:
            self._sessions[session_id] = now
            self._had_browser_session = True

    def heartbeat(self, session_id: str) -> bool:
        now = time.time()
        with self._lock:
            if session_id not in self._sessions:
                return False
            self._sessions[session_id] = now
            return True

    def close(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def snapshot(self, stale_after_seconds: float) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            stale_ids = [
                session_id
                for session_id, last_seen_at in self._sessions.items()
                if (now - last_seen_at) > stale_after_seconds
            ]
            for session_id in stale_ids:
                self._sessions.pop(session_id, None)
            active_count = len(self._sessions)
            return {
                "active_count": active_count,
                "had_browser_session": self._had_browser_session,
                "session_ids": sorted(self._sessions),
            }


BROWSER_SESSIONS = BrowserSessionStore()
SESSION_HEARTBEAT_TIMEOUT_SECONDS = 15.0


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    # 统一 JSON 返回格式，避免各路由重复写 header。
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def text_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    content: str,
    content_type: str = "text/plain; charset=utf-8",
) -> None:
    # 文本文件和调试内容走 UTF-8 文本响应。
    data = content.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def bytes_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    content: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    # 二进制文件直接回传，例如视频、图片和其他非文本产物。
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(content)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(content)


def read_body_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length) if length else b"{}"
    return json.loads(body.decode("utf-8") or "{}")


def open_folder(path: Path) -> None:
    # 按平台打开输出目录，Windows 走 startfile，Linux / macOS 走系统打开器。
    APP_LOGGER.info("Opening folder: %s", path)
    if hasattr(os, "startfile"):
        os.startfile(str(path))
        return

    if sys.platform == "darwin":
        opener = "open"
    else:
        opener = "xdg-open"

    opener_path = shutil.which(opener)
    if not opener_path:
        raise RuntimeError(f"Could not find '{opener}'. Please open the folder manually: {path}")

    try:
        subprocess.Popen([opener_path, str(path)])
    except OSError as exc:
        raise RuntimeError(f"Failed to open folder '{path}': {exc}") from exc


def job_snapshot(job: JobState) -> dict[str, Any]:
    # 前端轮询时读取的是可序列化快照，而不是原始 dataclass 对象。
    data = asdict(job)
    data["outputs_count"] = len(job.outputs)
    return data


def terminate_server_process(server: ThreadingHTTPServer, exit_code: int = 0) -> None:
    # 终止逻辑放在线程里，避免在请求处理线程中直接阻塞退出。
    def worker() -> None:
        try:
            server.shutdown()
            server.server_close()
        finally:
            time.sleep(0.2)
            os._exit(exit_code)

    threading.Thread(target=worker, daemon=True).start()


def _prompt_config_payload(kind: str) -> dict[str, Any]:
    # 返回配置文件路径 + 配置内容，前端可直接显示和编辑。
    return {
        "path": project_relative_path_text(prompt_config_path(kind)),
        "config": load_prompt_config(kind),
    }


def _api_config_payload(kind: str) -> dict[str, Any]:
    # 返回各 Prompt 子模块对应的运行时 API 配置。
    return {
        "path": project_relative_path_text(api_config_path()),
        "config": load_api_config(kind),
    }


def _start_job_worker(
    *,
    job: JobState,
    total: int,
    runner: Callable[[JobState], dict[str, Any]],
) -> JobState:
    # 统一的后台任务包装器：负责设置 running 状态、接收 runner 结果并落盘。
    STORE.update(job.id, status="running", started_at=time.time())

    def _first_failure_message(failures: list[dict[str, Any]]) -> str:
        if not failures:
            return ""
        first = failures[0] if isinstance(failures[0], dict) else {}
        return str(first.get("message") or first.get("error") or "").strip()

    def worker() -> None:
        try:
            result = runner(job)
            final_total = int(result.get("total") or total)
            # runner 统一返回 items / failures / output_dir / status，这里负责写回最终状态。
            STORE.replace_outputs(job.id, result["items"])
            STORE.replace_failures(job.id, result["failures"])
            status = str(result.get("status") or ("completed" if result["items"] or not result["failures"] else "failed"))
            STORE.update(
                job.id,
                status=status,
                progress=final_total,
                total=final_total,
                output_dir=result["output_dir"],
                error=str(result.get("error") or _first_failure_message(result["failures"]) or ""),
                finished_at=time.time(),
            )
            if result["failures"]:
                STORE.append_log(job.id, f"Failed items: {len(result['failures'])}", level=logging.WARNING)
            STORE.append_log(job.id, f"Done. Output: {result['output_dir']}")
        except Exception as exc:
            STORE.update(job.id, status="failed", error=str(exc), finished_at=time.time())
            get_job_logger(job.id, job.kind).exception("Job worker crashed.")
            STORE.append_log(job.id, f"Failed: {exc}", level=logging.ERROR)

    threading.Thread(target=worker, daemon=True).start()
    return job


def start_image_job(payload: dict[str, Any]) -> JobState:
    # 图片 Prompt 任务：合并前端输入、默认配置和模块配置后交给服务层执行。
    images = list(payload.get("images") or [])
    module_config = load_api_config(IMAGE_PROMPT_KIND)
    path_style = str(payload.get("pathStyle") or module_config.get("path_style") or "").strip().lower()
    output_root = resolve_output_path(
        payload.get("outputDir")
        or module_config.get("output_dir")
        or DEFAULTS.image_output_root
        or default_output_root(IMAGE_PROMPT_KIND),
        IMAGE_PROMPT_KIND,
        path_style=path_style,
    )
    ensure_dir(output_root)
    job = STORE.create(kind=IMAGE_PROMPT_KIND, total=len(images))
    get_job_logger(job.id, job.kind).info("Starting image prompt job. items=%s output_root=%s", len(images), output_root)

    def runner(job_state: JobState) -> dict[str, Any]:
        return run_image_generation(
            job_id=job_state.id,
            images=images,
            output_root=output_root,
            api_key=str(payload.get("apiKey") or module_config.get("api_key") or ""),
            base_url=str(payload.get("baseUrl") or module_config.get("base_url") or DEFAULTS.base_url),
            model=str(payload.get("model") or module_config.get("model") or DEFAULTS.model),
            overwrite=bool(payload.get("overwrite", module_config.get("overwrite", False))),
            use_mock=bool(payload.get("useMock", module_config.get("use_mock", True))),
            prompt_config=payload.get("promptConfig"),
            log=lambda message: STORE.append_log(job_state.id, message),
            progress=lambda current, total: STORE.update(job_state.id, progress=current, total=total),
        )
    return _start_job_worker(job=job, total=len(images), runner=runner)


def start_image_edit_job(payload: dict[str, Any]) -> JobState:
    # 图生图 Prompt 任务：逻辑与图片 Prompt 类似，但使用独立配置文件。
    images = list(payload.get("images") or [])
    module_config = load_api_config(IMAGE_EDIT_PROMPT_KIND)
    path_style = str(payload.get("pathStyle") or module_config.get("path_style") or "").strip().lower()
    output_root = resolve_output_path(
        payload.get("outputDir")
        or module_config.get("output_dir")
        or DEFAULTS.image_edit_output_root
        or default_output_root(IMAGE_EDIT_PROMPT_KIND),
        IMAGE_EDIT_PROMPT_KIND,
        path_style=path_style,
    )
    ensure_dir(output_root)
    job = STORE.create(kind=IMAGE_EDIT_PROMPT_KIND, total=len(images))
    get_job_logger(job.id, job.kind).info("Starting image edit prompt job. items=%s output_root=%s", len(images), output_root)

    def runner(job_state: JobState) -> dict[str, Any]:
        return run_image_edit_generation(
            job_id=job_state.id,
            images=images,
            output_root=output_root,
            api_key=str(payload.get("apiKey") or module_config.get("api_key") or ""),
            base_url=str(payload.get("baseUrl") or module_config.get("base_url") or DEFAULTS.base_url),
            model=str(payload.get("model") or module_config.get("model") or DEFAULTS.model),
            overwrite=bool(payload.get("overwrite", module_config.get("overwrite", False))),
            use_mock=bool(payload.get("useMock", module_config.get("use_mock", True))),
            prompt_config=payload.get("promptConfig"),
            log=lambda message: STORE.append_log(job_state.id, message),
            progress=lambda current, total: STORE.update(job_state.id, progress=current, total=total),
        )

    return _start_job_worker(job=job, total=len(images), runner=runner)


def start_video_job(payload: dict[str, Any]) -> JobState:
    # 视频 Prompt 任务：输入通常包含视频和参考图，输出是结构化 Prompt CSV。
    videos = list(payload.get("videos") or [])
    module_config = load_api_config(VIDEO_PROMPT_KIND)
    path_style = str(payload.get("pathStyle") or module_config.get("path_style") or "").strip().lower()
    output_root = resolve_output_path(
        payload.get("outputDir")
        or module_config.get("output_dir")
        or DEFAULTS.video_output_root
        or default_output_root(VIDEO_PROMPT_KIND),
        VIDEO_PROMPT_KIND,
        path_style=path_style,
    )
    ensure_dir(output_root)
    job = STORE.create(kind=VIDEO_PROMPT_KIND, total=len(videos))
    get_job_logger(job.id, job.kind).info("Starting video prompt job. items=%s output_root=%s", len(videos), output_root)

    def runner(job_state: JobState) -> dict[str, Any]:
        return run_video_generation(
            job_id=job_state.id,
            videos=videos,
            output_root=output_root,
            api_key=str(payload.get("apiKey") or module_config.get("api_key") or ""),
            base_url=str(payload.get("baseUrl") or module_config.get("base_url") or DEFAULTS.base_url),
            model=str(payload.get("model") or module_config.get("model") or DEFAULTS.model),
            overwrite=bool(payload.get("overwrite", module_config.get("overwrite", False))),
            use_mock=bool(payload.get("useMock", module_config.get("use_mock", True))),
            prompt_config=payload.get("promptConfig"),
            log=lambda message: STORE.append_log(job_state.id, message),
            progress=lambda current, total: STORE.update(job_state.id, progress=current, total=total),
        )
    return _start_job_worker(job=job, total=len(videos), runner=runner)


def start_video_clip_job(payload: dict[str, Any]) -> JobState:
    # 本地视频剪辑任务：裁切和合并都走这一条入口。
    job = STORE.create(kind="video_clip", total=0)
    get_job_logger(job.id, job.kind).info("Starting video clip job.")

    def runner(job_state: JobState) -> dict[str, Any]:
        return run_video_clip_job(
            job_id=job_state.id,
            payload=payload,
            log=lambda message: STORE.append_log(job_state.id, message),
            progress=lambda current, total: STORE.update(
                job_state.id,
                progress=current,
                total=total,
            ),
        )

    return _start_job_worker(job=job, total=0, runner=runner)


def start_comfy_generation_job(payload: dict[str, Any]) -> JobState:
    # Comfy 批跑任务：保留原始 payload，便于失败续跑、仅重跑失败行和跳过成功项续跑。
    job = STORE.create(kind=COMFY_JOB_KIND, total=100)
    STORE.merge_meta(job.id, original_payload=payload)
    get_job_logger(job.id, job.kind).info(
        "Starting ComfyUI batch job. csv_path=%s template_key=%s",
        str(payload.get("csvPath") or "").strip(),
        str(payload.get("templateKey") or "").strip(),
    )

    def update_job(job_id: str, **changes: Any) -> None:
        meta = changes.pop("meta", None)
        if meta and isinstance(meta, dict):
            STORE.merge_meta(job_id, meta=meta)
        if changes:
            STORE.update(job_id, **changes)

    def runner(job_state: JobState) -> dict[str, Any]:
        try:
            return run_comfy_job(
                job_id=job_state.id,
                payload=payload,
                log=lambda message: STORE.append_log(job_state.id, message),
                progress=lambda current, total: STORE.update(job_state.id, progress=current, total=total),
                update_job=lambda **changes: update_job(job_state.id, **changes),
            )
        except TimeoutError as exc:
            STORE.append_log(job_state.id, f"Timed out: {exc}", level=logging.ERROR)
            return {
                "status": "timeout",
                "job_id": job_state.id,
                "output_dir": "",
                "items": [],
                "failures": [],
                "total": 100,
            }

    return _start_job_worker(job=job, total=100, runner=runner)


def _job_output_files(job: JobState) -> list[dict[str, str]]:
    # 优先返回已经收集到的 Comfy 输出文件；否则退回输出目录扫描。
    files: list[dict[str, str]] = []
    if job.kind == COMFY_JOB_KIND and job.outputs:
        seen: set[str] = set()
        for item in job.outputs:
            path_text = str(item.get("path") or "").strip()
            if not path_text:
                continue
            path = Path(path_text)
            if not path.exists() or not path.is_file():
                continue
            if path.name in seen:
                continue
            seen.add(path.name)
            files.append({"name": path.name, "url": f"/api/jobs/{job.id}/files/{path.name}"})
        if files:
            return files

    if job.output_dir:
        for file_path in sorted(Path(job.output_dir).glob("*")):
            if file_path.is_file():
                files.append(
                    {
                        "name": file_path.name,
                        "url": f"/api/jobs/{job.id}/files/{file_path.name}",
                    }
                )
    return files


def _resolve_job_output_file(job: JobState, filename: str) -> Path | None:
    # 文件下载时优先按已收集的结果路径定位，避免同名文件误取。
    if job.kind == COMFY_JOB_KIND and job.outputs:
        for item in job.outputs:
            path_text = str(item.get("path") or "").strip()
            if not path_text:
                continue
            path = Path(path_text)
            if path.name == filename and path.exists() and path.is_file():
                return path
    if not job.output_dir:
        return None
    file_path = Path(job.output_dir) / filename
    if file_path.exists() and file_path.is_file():
        return file_path
    return None


class LoggedThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: tuple[str, int]) -> None:
        # 统一捕获未处理异常，写入应用日志，便于排障。
        APP_LOGGER.exception("Unhandled request error. client=%s:%s", client_address[0], client_address[1])


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "PromptToolDemo/0.2"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        try:
            message = format % args
        except Exception:
            message = format
        HTTP_LOGGER.info("%s:%s - %s", self.client_address[0], self.client_address[1], message)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        # 静态资源入口。
        if path == "/":
            return self._serve_frontend("index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._serve_frontend("app.js", "application/javascript; charset=utf-8")
        if path == "/style.css":
            return self._serve_frontend("style.css", "text/css; charset=utf-8")

        # 全局配置接口。
        if path == "/api/config":
            image_api_config = load_api_config(IMAGE_PROMPT_KIND)
            image_edit_api_config = load_api_config(IMAGE_EDIT_PROMPT_KIND)
            video_api_config = load_api_config(VIDEO_PROMPT_KIND)
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "apiKey": "",
                    "baseUrl": DEFAULTS.base_url,
                    "model": DEFAULTS.model,
                    "outputRoot": DEFAULTS.output_root,
                    "imageOutputRoot": DEFAULTS.image_output_root,
                    "imageEditOutputRoot": DEFAULTS.image_edit_output_root,
                    "videoOutputRoot": DEFAULTS.video_output_root,
                    "imagePromptConfigPath": project_relative_path_text(prompt_config_path(IMAGE_PROMPT_KIND)),
                    "imageEditPromptConfigPath": project_relative_path_text(prompt_config_path(IMAGE_EDIT_PROMPT_KIND)),
                    "videoPromptConfigPath": project_relative_path_text(prompt_config_path(VIDEO_PROMPT_KIND)),
                    "imageApiConfigPath": project_relative_path_text(api_config_path()),
                    "imageEditApiConfigPath": project_relative_path_text(api_config_path()),
                    "videoApiConfigPath": project_relative_path_text(api_config_path()),
                    "imageApiConfig": image_api_config,
                    "imageEditApiConfig": image_edit_api_config,
                    "videoApiConfig": video_api_config,
                    "useMock": True,
                },
            )

        # 视频剪辑预设列表。
        if path == "/api/clip/presets":
            return json_response(self, HTTPStatus.OK, {"presets": list_clip_presets()})

        # Comfy 通信配置与健康检查。
        if path == "/api/comfy/config":
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "path": project_relative_path_text(comfy_config_path()),
                    "config": load_comfy_config(),
                },
            )

        if path == "/api/comfy/templates":
            config = load_comfy_config()
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "path": project_relative_path_text(resolve_workflow_manifest_dir(config)),
                    "templates": list_comfy_templates(config),
                },
            )

        if path == "/api/comfy/health":
            try:
                payload = comfy_health(load_comfy_config())
            except Exception as exc:
                return json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, {"online": False, "error": str(exc)})
            return json_response(self, HTTPStatus.OK, payload)

        # Prompt 配置读取接口。
        if path == "/api/prompt-config":
            return json_response(self, HTTPStatus.OK, _prompt_config_payload(IMAGE_PROMPT_KIND))
        if path == f"/api/prompt-config/{IMAGE_PROMPT_KIND}":
            return json_response(self, HTTPStatus.OK, _prompt_config_payload(IMAGE_PROMPT_KIND))
        if path == f"/api/prompt-config/{IMAGE_EDIT_PROMPT_KIND}":
            return json_response(self, HTTPStatus.OK, _prompt_config_payload(IMAGE_EDIT_PROMPT_KIND))
        if path == f"/api/prompt-config/{VIDEO_PROMPT_KIND}":
            return json_response(self, HTTPStatus.OK, _prompt_config_payload(VIDEO_PROMPT_KIND))
        if path == f"/api/runtime-config/{IMAGE_PROMPT_KIND}":
            return json_response(self, HTTPStatus.OK, _api_config_payload(IMAGE_PROMPT_KIND))
        if path == f"/api/runtime-config/{IMAGE_EDIT_PROMPT_KIND}":
            return json_response(self, HTTPStatus.OK, _api_config_payload(IMAGE_EDIT_PROMPT_KIND))
        if path == f"/api/runtime-config/{VIDEO_PROMPT_KIND}":
            return json_response(self, HTTPStatus.OK, _api_config_payload(VIDEO_PROMPT_KIND))

        if path == "/api/browser-session":
            return json_response(
                self,
                HTTPStatus.OK,
                BROWSER_SESSIONS.snapshot(SESSION_HEARTBEAT_TIMEOUT_SECONDS),
            )

        # 任务文件列表与文件下载接口。
        if path.startswith("/api/jobs/") and path.endswith("/files"):
            job_id = path.split("/")[3]
            job = STORE.get(job_id)
            if not job:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Job not found"})
            return json_response(self, HTTPStatus.OK, {"files": _job_output_files(job)})

        if path.startswith("/api/jobs/") and "/files/" in path:
            parts = path.split("/")
            job_id = parts[3]
            filename = unquote(parts[-1])
            job = STORE.get(job_id)
            if not job:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Job not found"})
            if not job.output_dir:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Output directory not ready"})
            file_path = _resolve_job_output_file(job, filename)
            if not file_path:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "File not found"})
            guessed_type, _ = mimetypes.guess_type(str(file_path))
            content_type = guessed_type or "application/octet-stream"
            if file_path.suffix.lower() in {".json", ".txt", ".csv", ".md"}:
                return text_response(self, HTTPStatus.OK, file_path.read_text(encoding="utf-8"), f"{content_type}; charset=utf-8")
            return bytes_response(self, HTTPStatus.OK, file_path.read_bytes(), content_type)

        if path.startswith("/api/jobs/"):
            job_id = path.split("/")[3]
            job = STORE.get(job_id)
            if not job:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Job not found"})
            return json_response(self, HTTPStatus.OK, job_snapshot(job))

        return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        # 视频剪辑任务提交入口。
        if path == "/api/clip/run":
            payload = read_body_json(self)
            if not str(payload.get("preset") or "").strip():
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing clip preset"})
            job = start_video_clip_job(payload)
            return json_response(self, HTTPStatus.ACCEPTED, {"jobId": job.id, "job": job_snapshot(job)})

        # Comfy 配置保存与任务控制入口。
        if path == "/api/comfy/config":
            payload = read_body_json(self)
            normalized = save_comfy_config(payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(comfy_config_path()),
                    "config": normalized,
                },
            )

        if path == "/api/comfy/run":
            payload = read_body_json(self)
            if not str(payload.get("csvPath") or "").strip():
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Please provide a CSV path."})
            job = start_comfy_generation_job(payload)
            return json_response(self, HTTPStatus.ACCEPTED, {"jobId": job.id, "job": job_snapshot(job)})

        if path == "/api/comfy/cancel":
            payload = read_body_json(self)
            job_id = str(payload.get("jobId") or "").strip()
            if not job_id:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing jobId"})
            job = STORE.get(job_id)
            if not job:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Job not found"})
            try:
                result = cancel_comfy_job(job_id, load_comfy_config())
            except Exception as exc:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            STORE.append_log(job_id, result.get("message") or "Cancel requested.")
            STORE.merge_meta(job_id, cancel_requested=True)
            return json_response(self, HTTPStatus.OK, {"ok": True, "result": result, "job": job_snapshot(STORE.get(job_id) or job)})

        if path == "/api/comfy/retry":
            payload = read_body_json(self)
            job_id = str(payload.get("jobId") or "").strip()
            failed_only = bool(payload.get("failedOnly", False))
            skip_succeeded = bool(payload.get("skipSucceeded", False))
            if not job_id:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing jobId"})
            if failed_only and skip_succeeded:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Choose either failedOnly or skipSucceeded, not both."})
            job = STORE.get(job_id)
            if not job:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Job not found"})
            original_payload = job.meta.get("original_payload") if isinstance(job.meta, dict) else None
            if not isinstance(original_payload, dict):
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "The original ComfyUI payload is not available for retry."})
            retry_payload = dict(original_payload)
            if failed_only:
                failed_rows = sorted(
                    {
                        int(item.get("row_index"))
                        for item in (job.failures or [])
                        if isinstance(item, dict) and item.get("row_index") is not None
                    }
                )
                if not failed_rows:
                    return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "There are no failed rows available for retry."})
                retry_payload["rowIndices"] = failed_rows
            if skip_succeeded:
                selected_rows = job.meta.get("selected_row_indices") if isinstance(job.meta, dict) else None
                row_count = int(job.meta.get("row_count") or 0) if isinstance(job.meta, dict) else 0
                if isinstance(selected_rows, list) and selected_rows:
                    base_rows = {int(item) for item in selected_rows}
                else:
                    base_rows = set(range(1, row_count + 1)) if row_count > 0 else set()
                succeeded_rows = {
                    int(item.get("row_index"))
                    for item in (job.outputs or [])
                    if isinstance(item, dict) and item.get("row_index") is not None
                }
                remaining_rows = sorted(base_rows - succeeded_rows)
                if not remaining_rows:
                    return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "There are no remaining rows to resume."})
                retry_payload["rowIndices"] = remaining_rows
            retry_job = start_comfy_generation_job(retry_payload)
            STORE.merge_meta(retry_job.id, retry_of=job_id)
            return json_response(self, HTTPStatus.ACCEPTED, {"jobId": retry_job.id, "job": job_snapshot(retry_job)})

        # Prompt 任务提交入口。
        if path in {"/api/generate", f"/api/generate/{IMAGE_PROMPT_KIND}-prompt"}:
            payload = read_body_json(self)
            images = payload.get("images") or []
            if not images:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "No images supplied"})
            job = start_image_job(payload)
            return json_response(self, HTTPStatus.ACCEPTED, {"jobId": job.id, "job": job_snapshot(job)})

        if path == "/api/generate/image-edit-prompt":
            payload = read_body_json(self)
            images = payload.get("images") or []
            if not images:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "No images supplied"})
            job = start_image_edit_job(payload)
            return json_response(self, HTTPStatus.ACCEPTED, {"jobId": job.id, "job": job_snapshot(job)})

        if path == f"/api/generate/{VIDEO_PROMPT_KIND}-prompt":
            payload = read_body_json(self)
            videos = payload.get("videos") or []
            if not videos:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "No videos supplied"})
            job = start_video_job(payload)
            return json_response(self, HTTPStatus.ACCEPTED, {"jobId": job.id, "job": job_snapshot(job)})

        if path == "/api/video/scan-match":
            payload = read_body_json(self)
            return json_response(
                self,
                HTTPStatus.OK,
                build_video_matches(payload.get("videos") or [], payload.get("references") or []),
            )

        if path == "/api/prompt-config":
            payload = read_body_json(self)
            normalized = save_prompt_config(IMAGE_PROMPT_KIND, payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(prompt_config_path(IMAGE_PROMPT_KIND)),
                    "config": normalized,
                },
            )

        if path == f"/api/prompt-config/{IMAGE_PROMPT_KIND}":
            payload = read_body_json(self)
            normalized = save_prompt_config(IMAGE_PROMPT_KIND, payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(prompt_config_path(IMAGE_PROMPT_KIND)),
                    "config": normalized,
                },
            )

        if path == f"/api/prompt-config/{IMAGE_EDIT_PROMPT_KIND}":
            payload = read_body_json(self)
            normalized = save_prompt_config(IMAGE_EDIT_PROMPT_KIND, payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(prompt_config_path(IMAGE_EDIT_PROMPT_KIND)),
                    "config": normalized,
                },
            )

        if path == f"/api/prompt-config/{VIDEO_PROMPT_KIND}":
            payload = read_body_json(self)
            normalized = save_prompt_config(VIDEO_PROMPT_KIND, payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(prompt_config_path(VIDEO_PROMPT_KIND)),
                    "config": normalized,
                },
            )

        if path == f"/api/runtime-config/{IMAGE_PROMPT_KIND}":
            payload = read_body_json(self)
            normalized = save_api_config(IMAGE_PROMPT_KIND, payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(api_config_path()),
                    "config": normalized,
                },
            )

        if path == f"/api/runtime-config/{IMAGE_EDIT_PROMPT_KIND}":
            payload = read_body_json(self)
            normalized = save_api_config(IMAGE_EDIT_PROMPT_KIND, payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(api_config_path()),
                    "config": normalized,
                },
            )

        if path == f"/api/runtime-config/{VIDEO_PROMPT_KIND}":
            payload = read_body_json(self)
            normalized = save_api_config(VIDEO_PROMPT_KIND, payload.get("config") or {})
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "path": project_relative_path_text(api_config_path()),
                    "config": normalized,
                },
            )

        # 浏览器会话接口只负责控制服务生命周期，不保存业务任务。
        if path == "/api/browser-session/register":
            payload = read_body_json(self)
            session_id = str(payload.get("sessionId") or "").strip()
            if not session_id:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing sessionId"})
            BROWSER_SESSIONS.register(session_id)
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "sessionId": session_id,
                    **BROWSER_SESSIONS.snapshot(SESSION_HEARTBEAT_TIMEOUT_SECONDS),
                },
            )

        if path == "/api/browser-session/heartbeat":
            payload = read_body_json(self)
            session_id = str(payload.get("sessionId") or "").strip()
            if not session_id:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing sessionId"})
            known = BROWSER_SESSIONS.heartbeat(session_id)
            if not known:
                BROWSER_SESSIONS.register(session_id)
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "sessionId": session_id,
                    **BROWSER_SESSIONS.snapshot(SESSION_HEARTBEAT_TIMEOUT_SECONDS),
                },
            )

        if path == "/api/browser-session/close":
            payload = read_body_json(self)
            session_id = str(payload.get("sessionId") or "").strip()
            if not session_id:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Missing sessionId"})
            BROWSER_SESSIONS.close(session_id)
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "sessionId": session_id,
                    **BROWSER_SESSIONS.snapshot(SESSION_HEARTBEAT_TIMEOUT_SECONDS),
                },
            )

        if path == "/api/app/terminate":
            payload = read_body_json(self)
            session_id = str(payload.get("sessionId") or "").strip()
            if session_id:
                BROWSER_SESSIONS.close(session_id)
            APP_LOGGER.info("Shutdown requested by client. session_id=%s", session_id or "unknown")
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "ok": True,
                    "message": "Server is shutting down.",
                },
            )
            terminate_server_process(self.server)
            return

        if path.startswith("/api/jobs/") and path.endswith("/open-output"):
            job_id = path.split("/")[3]
            job = STORE.get(job_id)
            if not job:
                return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Job not found"})
            if not job.output_dir:
                return json_response(self, HTTPStatus.BAD_REQUEST, {"error": "Output folder is not ready yet"})
            open_folder(Path(job.output_dir))
            return json_response(self, HTTPStatus.OK, {"ok": True, "path": job.output_dir})

        return json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _serve_frontend(self, filename: str, content_type: str) -> None:
        file_path = FRONTEND_DIR / filename
        if not file_path.exists():
            return json_response(self, HTTPStatus.NOT_FOUND, {"error": f"Missing frontend file: {filename}"})
        text_response(self, HTTPStatus.OK, file_path.read_text(encoding="utf-8"), content_type)


def main() -> None:
    # 启动顺序：日志 -> 目录 -> 配置 -> 模板目录 -> HTTP 服务。
    log_paths = setup_logging()
    APP_LOGGER.info("Application startup. date=2026-08-18 log_dir=%s", log_paths.root_dir)
    ensure_dir(default_output_root())
    ensure_dir(default_output_root(IMAGE_PROMPT_KIND))
    ensure_dir(default_output_root(IMAGE_EDIT_PROMPT_KIND))
    ensure_dir(default_output_root(VIDEO_PROMPT_KIND))
    ensure_dir(Path(__file__).resolve().parents[2] / "uploads")
    load_api_config()
    comfy_config = load_comfy_config()
    ensure_dir(resolve_workflow_manifest_dir(comfy_config))
    load_prompt_config(IMAGE_PROMPT_KIND)
    load_prompt_config(IMAGE_EDIT_PROMPT_KIND)
    load_prompt_config(VIDEO_PROMPT_KIND)
    server = LoggedThreadingHTTPServer(("127.0.0.1", 8000), DemoHandler)
    APP_LOGGER.info("Prompt tool demo running at http://127.0.0.1:8000")
    print("Prompt tool demo running at http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        APP_LOGGER.info("Server stopped by KeyboardInterrupt.")
        print("\nStopped.")


if __name__ == "__main__":
    main()
