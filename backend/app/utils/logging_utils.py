from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path


MAX_LOG_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


@dataclass(frozen=True)
class LoggingPaths:
    root_dir: Path
    app_log: Path
    error_log: Path
    http_log: Path
    jobs_dir: Path


_LOGGING_LOCK = threading.Lock()
_JOB_LOGGER_LOCK = threading.Lock()
_LOGGING_PATHS: LoggingPaths | None = None
_EXCEPTION_HOOKS_INSTALLED = False
_PREVIOUS_SYS_EXCEPTHOOK = sys.excepthook
_PREVIOUS_THREAD_EXCEPTHOOK = getattr(threading, "excepthook", None)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log_formatter() -> logging.Formatter:
    return logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")


def _new_rotating_file_handler(path: Path, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(_log_formatter())
    return handler


def _build_paths(log_root: Path | None = None) -> LoggingPaths:
    root_dir = _ensure_dir((log_root or (Path(__file__).resolve().parents[3] / "logs")).resolve())
    jobs_dir = _ensure_dir(root_dir / "jobs")
    return LoggingPaths(
        root_dir=root_dir,
        app_log=root_dir / "app.log",
        error_log=root_dir / "error.log",
        http_log=root_dir / "http.log",
        jobs_dir=jobs_dir,
    )


def _install_exception_hooks() -> None:
    global _EXCEPTION_HOOKS_INSTALLED
    if _EXCEPTION_HOOKS_INSTALLED:
        return

    def _sys_excepthook(exc_type, exc_value, exc_traceback) -> None:
        logging.getLogger("web_demo.crash").critical(
            "Unhandled top-level exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        _PREVIOUS_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

    def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
        logging.getLogger("web_demo.crash").critical(
            "Unhandled thread exception thread=%s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        if _PREVIOUS_THREAD_EXCEPTHOOK is not None:
            _PREVIOUS_THREAD_EXCEPTHOOK(args)

    sys.excepthook = _sys_excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook
    _EXCEPTION_HOOKS_INSTALLED = True


def setup_logging(log_root: Path | None = None) -> LoggingPaths:
    global _LOGGING_PATHS
    with _LOGGING_LOCK:
        paths = _build_paths(log_root)

        app_root_logger = logging.getLogger("web_demo")
        app_root_logger.setLevel(logging.DEBUG)
        app_root_logger.handlers.clear()
        app_root_logger.propagate = False

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(_log_formatter())
        app_root_logger.addHandler(console_handler)
        app_root_logger.addHandler(_new_rotating_file_handler(paths.app_log, logging.INFO))
        app_root_logger.addHandler(_new_rotating_file_handler(paths.error_log, logging.ERROR))

        http_logger = logging.getLogger("web_demo.http")
        http_logger.setLevel(logging.INFO)
        http_logger.handlers.clear()
        http_logger.propagate = True
        http_logger.addHandler(_new_rotating_file_handler(paths.http_log, logging.INFO))

        _install_exception_hooks()
        _LOGGING_PATHS = paths
        logging.getLogger("web_demo.app").info("Logging initialized. log_dir=%s", paths.root_dir)
        return paths


def logging_paths() -> LoggingPaths:
    if _LOGGING_PATHS is None:
        return setup_logging()
    return _LOGGING_PATHS


def get_job_log_path(job_id: str) -> Path:
    return logging_paths().jobs_dir / f"{job_id}.log"


def get_job_logger(job_id: str, kind: str = "job") -> logging.Logger:
    paths = logging_paths()
    logger_name = f"web_demo.job.{job_id}"
    logger = logging.getLogger(logger_name)
    with _JOB_LOGGER_LOCK:
        logger.setLevel(logging.INFO)
        logger.propagate = True
        expected_path = get_job_log_path(job_id).resolve()
        has_expected_handler = False
        for handler in logger.handlers:
            if isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename).resolve() == expected_path:
                has_expected_handler = True
                break
        if not has_expected_handler:
            logger.handlers.clear()
            logger.addHandler(_new_rotating_file_handler(expected_path, logging.INFO))
    logger.debug("Job logger ready. kind=%s file=%s", kind, paths.jobs_dir / f"{job_id}.log")
    return logger
