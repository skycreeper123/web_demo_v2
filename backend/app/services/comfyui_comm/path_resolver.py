from __future__ import annotations

import os
import ntpath
import posixpath
from pathlib import Path
from typing import Any

from web_demo.backend.app.core.config import project_root


def _auto_path_style() -> str:
    return "windows" if os.name == "nt" else "linux"


def effective_path_style(config: dict[str, Any]) -> str:
    value = str(config.get("path_style") or "").strip().lower()
    return value if value in {"windows", "linux"} else _auto_path_style()


def _is_absolute_configured_path(text: str, path_style: str) -> bool:
    if Path(text).is_absolute():
        return True
    if path_style == "linux":
        return posixpath.isabs(text.replace("\\", "/"))
    if path_style == "windows":
        return ntpath.isabs(text)
    return False


def resolve_configured_path(
    value: str | None,
    *,
    fallback: Path | None = None,
    path_style: str | None = None,
) -> Path:
    text = str(value or "").strip()
    if not text:
        if fallback is None:
            raise RuntimeError("Missing required path configuration.")
        return fallback
    path = Path(text)
    if _is_absolute_configured_path(text, path_style or _auto_path_style()):
        return path
    return (project_root() / path).resolve()


def resolve_comfy_root_dir(config: dict[str, Any]) -> Path:
    path_style = effective_path_style(config)
    return resolve_configured_path(
        config.get("comfy_root_dir") or None,
        fallback=project_root(),
        path_style=path_style,
    )


def resolve_comfy_input_dir(config: dict[str, Any]) -> Path:
    root = resolve_comfy_root_dir(config)
    return resolve_configured_path(
        config.get("comfy_input_dir") or None,
        fallback=root / "input",
        path_style=effective_path_style(config),
    )


def resolve_comfy_output_dir(config: dict[str, Any]) -> Path:
    root = resolve_comfy_root_dir(config)
    return resolve_configured_path(
        config.get("comfy_output_dir") or None,
        fallback=root / "output",
        path_style=effective_path_style(config),
    )


def resolve_temp_dir(config: dict[str, Any]) -> Path:
    return resolve_configured_path(
        config.get("temp_dir") or None,
        fallback=project_root() / "output" / "comfy_temp",
        path_style=effective_path_style(config),
    )


def resolve_workflow_manifest_dir(config: dict[str, Any]) -> Path:
    return resolve_configured_path(
        config.get("workflow_manifest_dir") or None,
        fallback=project_root() / "workflow",
        path_style=effective_path_style(config),
    )


def workflow_ref(*parts: str) -> str:
    return Path(*parts).as_posix()
