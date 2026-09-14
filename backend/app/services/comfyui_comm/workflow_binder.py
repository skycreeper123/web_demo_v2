from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .path_resolver import resolve_workflow_manifest_dir


def _safe_json_loads(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label}不是合法 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label}必须是 JSON 对象。")
    return value


def _workflow_relative_path(path: Path, manifest_dir: Path) -> str:
    return path.relative_to(manifest_dir).as_posix()


def _workflow_key(path: Path, manifest_dir: Path) -> str:
    return _workflow_relative_path(path, manifest_dir).replace("/", "__")


def _workflow_label(path: Path, manifest_dir: Path) -> str:
    relative_path = Path(_workflow_relative_path(path, manifest_dir))
    if len(relative_path.parts) <= 1:
        return path.stem
    return f"{path.stem} ({relative_path.parent.as_posix()})"


def _manifest_summary(path: Path, manifest_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    bindings = payload.get("bindings") or {}
    return {
        "key": str(payload.get("key") or _workflow_key(path, manifest_dir)),
        "label": str(payload.get("label") or _workflow_label(path, manifest_dir)),
        "workflow_type": str(payload.get("workflow_type") or ""),
        "description": str(payload.get("description") or ""),
        "path": str(path).replace("\\", "/"),
        "relative_path": _workflow_relative_path(path, manifest_dir),
        "bindings_count": len(bindings) if isinstance(bindings, dict) else 0,
        "bindings_keys": sorted(bindings.keys()) if isinstance(bindings, dict) else [],
        "bindings": bindings if isinstance(bindings, dict) else {},
        "source_type": str(payload.get("source_type") or "manifest"),
        "bindings_inferred": bool(payload.get("bindings_inferred")),
    }


def _looks_like_api_workflow(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    for key, value in payload.items():
        if not str(key).strip():
            return False
        if not isinstance(value, dict):
            return False
        if "class_type" not in value or "inputs" not in value:
            return False
    return True


def _node_title_lower(node_payload: dict[str, Any]) -> str:
    meta = node_payload.get("_meta") or {}
    return str(meta.get("title") or "").strip().lower()


def _infer_workflow_type(path: Path, workflow: dict[str, Any]) -> str:
    lowered_name = path.stem.lower()
    class_types = [str(node.get("class_type") or "").strip().lower() for node in workflow.values() if isinstance(node, dict)]
    has_video_loader = any("loadvideo" in class_type for class_type in class_types)
    has_image_loader = any("loadimage" in class_type for class_type in class_types)
    has_image_edit = any(
        marker in class_type
        for class_type in class_types
        for marker in ("imageedit", "image edit", "qwenimageedit", "img2img")
    )

    if has_video_loader and has_image_loader:
        return "image_video_to_video"
    if has_video_loader:
        return "video_to_video"
    if has_image_edit:
        return "image_edit"
    if has_image_loader:
        return "image_to_video"
    if "video" in lowered_name and "image" in lowered_name:
        return "image_video_to_video"
    if "video" in lowered_name:
        return "video_to_video"
    if "edit" in lowered_name:
        return "image_edit"
    if "image" in lowered_name:
        return "image_to_video"
    return ""


def _append_binding(bindings: dict[str, list[dict[str, Any]]], binding_key: str, target: dict[str, Any]) -> None:
    existing = bindings.setdefault(binding_key, [])
    normalized_target = {
        "node": str(target.get("node") or "").strip(),
        "input": str(target.get("input") or "").strip(),
    }
    if target.get("type"):
        normalized_target["type"] = str(target["type"]).strip()
    if target.get("required"):
        normalized_target["required"] = True
    if not normalized_target["node"] or not normalized_target["input"]:
        return
    if normalized_target not in existing:
        existing.append(normalized_target)


def _looks_like_prompt_title(title_lower: str) -> bool:
    return any(token in title_lower for token in ("prompt", "提示词", "正向", "描述"))


def _looks_like_negative_title(title_lower: str) -> bool:
    return any(token in title_lower for token in ("negative", "负向", "反向"))


def _infer_bindings(workflow: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    bindings: dict[str, list[dict[str, Any]]] = {}
    generic_seed_targets: list[dict[str, Any]] = []

    for node_id, node_payload in workflow.items():
        if not isinstance(node_payload, dict):
            continue
        inputs = node_payload.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue

        class_type_lower = str(node_payload.get("class_type") or "").strip().lower()
        title_lower = _node_title_lower(node_payload)

        if "loadimage" in class_type_lower and "image" in inputs:
            _append_binding(bindings, "image_ref", {"node": node_id, "input": "image", "required": True})

        for video_input_name in ("video", "path", "filename", "file"):
            if "loadvideo" in class_type_lower and video_input_name in inputs:
                _append_binding(bindings, "video_ref", {"node": node_id, "input": video_input_name, "required": True})
                break

        if "positive_prompt" in inputs:
            _append_binding(bindings, "positive_prompt", {"node": node_id, "input": "positive_prompt", "required": True})
        elif "prompt" in inputs and (
            "textencode" in class_type_lower
            or "prompt" in class_type_lower
            or _looks_like_prompt_title(title_lower)
        ):
            _append_binding(bindings, "positive_prompt", {"node": node_id, "input": "prompt", "required": True})
        elif "text" in inputs and ("cliptextencode" in class_type_lower or "prompt" in class_type_lower):
            _append_binding(bindings, "positive_prompt", {"node": node_id, "input": "text", "required": True})
        elif "value" in inputs and class_type_lower.startswith("primitivestring") and _looks_like_prompt_title(title_lower) and not _looks_like_negative_title(title_lower):
            _append_binding(bindings, "positive_prompt", {"node": node_id, "input": "value", "required": True})

        if "negative_prompt" in inputs:
            _append_binding(bindings, "negative_prompt", {"node": node_id, "input": "negative_prompt"})
        elif "value" in inputs and class_type_lower.startswith("primitivestring") and _looks_like_negative_title(title_lower):
            _append_binding(bindings, "negative_prompt", {"node": node_id, "input": "value"})

        if "filename_prefix" in inputs:
            _append_binding(bindings, "output_prefix", {"node": node_id, "input": "filename_prefix"})

        if "seed" in inputs:
            seed_target = {"node": node_id, "input": "seed", "type": "int"}
            if "seed" in class_type_lower or any(token in title_lower for token in ("seed", "随机种", "随机种子", "random")):
                _append_binding(bindings, "seed", seed_target)
            else:
                generic_seed_targets.append(seed_target)

    if "seed" not in bindings:
        for target in generic_seed_targets:
            _append_binding(bindings, "seed", target)

    return bindings


def _infer_template_from_raw_api(path: Path, manifest_dir: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    bindings = _infer_bindings(workflow)
    workflow_type = _infer_workflow_type(path, workflow)
    binding_note = f"Auto-inferred bindings: {', '.join(bindings.keys())}" if bindings else "No common bindings were inferred automatically."
    return {
        "key": _workflow_key(path, manifest_dir),
        "label": _workflow_label(path, manifest_dir),
        "workflow_type": workflow_type,
        "description": f"Raw API workflow file detected automatically. {binding_note}",
        "workflow": workflow,
        "bindings": bindings,
        "source_type": "raw_api_workflow",
        "bindings_inferred": bool(bindings),
    }


def _template_payload_from_file(path: Path, manifest_dir: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if "workflow" in payload and isinstance(payload.get("workflow"), dict):
        normalized = dict(payload)
        normalized.setdefault("key", _workflow_key(path, manifest_dir))
        normalized.setdefault("label", _workflow_label(path, manifest_dir))
        normalized.setdefault("bindings", {})
        normalized.setdefault("source_type", "manifest")
        normalized.setdefault("bindings_inferred", False)
        return normalized
    if _looks_like_api_workflow(payload):
        return _infer_template_from_raw_api(path, manifest_dir, payload)
    return None


def list_workflow_templates(config: dict[str, Any]) -> list[dict[str, Any]]:
    manifest_dir = resolve_workflow_manifest_dir(config)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    templates: list[dict[str, Any]] = []
    for path in sorted(manifest_dir.rglob("*.json")):
        payload = _template_payload_from_file(path, manifest_dir)
        if payload is None:
            continue
        templates.append(_manifest_summary(path, manifest_dir, payload))
    return templates


def load_workflow_template(config: dict[str, Any], template_key: str) -> dict[str, Any]:
    manifest_dir = resolve_workflow_manifest_dir(config)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(manifest_dir.rglob("*.json")):
        payload = _template_payload_from_file(path, manifest_dir)
        if payload is None:
            continue
        key = str(payload.get("key") or _workflow_key(path, manifest_dir))
        if key == template_key:
            return payload
    raise RuntimeError(f"找不到工作流模板：{template_key}")


def _resolve_binding_value(source: dict[str, Any], key: str) -> Any:
    if key.startswith("params."):
        params = source.get("params") or {}
        return params.get(key.split(".", 1)[1])
    return source.get(key)


def _coerce_value(value: Any, binding: dict[str, Any]) -> Any:
    binding_type = str(binding.get("type") or "").strip().lower()
    if value is None or binding_type == "":
        return value
    if binding_type == "int":
        return int(value)
    if binding_type == "float":
        return float(value)
    if binding_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    if binding_type == "json":
        if isinstance(value, str):
            return json.loads(value)
        return value
    return value


def bind_workflow(
    *,
    payload: dict[str, Any],
    staged_inputs: dict[str, Any],
    template_payload: dict[str, Any],
) -> dict[str, Any]:
    workflow = copy.deepcopy(template_payload.get("workflow") or {})
    if not workflow:
        raise RuntimeError("工作流模板为空，请提供有效的 API workflow JSON。")

    bindings = template_payload.get("bindings") or {}
    if not isinstance(bindings, dict):
        raise RuntimeError("工作流 bindings 必须是对象。")

    bind_source = {
        "positive_prompt": str(payload.get("positivePrompt") or ""),
        "negative_prompt": str(payload.get("negativePrompt") or ""),
        "image_ref": staged_inputs.get("image_ref") or "",
        "video_ref": staged_inputs.get("video_ref") or "",
        "seed": payload.get("seed"),
        "output_prefix": str(payload.get("outputPrefix") or ""),
        "workflow_type": str(payload.get("workflowType") or template_payload.get("workflow_type") or ""),
        "params": payload.get("params") or {},
    }

    for binding_key, targets in bindings.items():
        if not isinstance(targets, list):
            raise RuntimeError(f"binding '{binding_key}' 必须是数组。")
        value = _resolve_binding_value(bind_source, binding_key)
        for target in targets:
            if not isinstance(target, dict):
                raise RuntimeError(f"binding '{binding_key}' 的目标必须是对象。")
            node_id = str(target.get("node") or "").strip()
            input_name = str(target.get("input") or "").strip()
            if not node_id or not input_name:
                raise RuntimeError(f"binding '{binding_key}' 缺少 node 或 input。")
            if node_id not in workflow:
                raise RuntimeError(f"工作流中找不到节点：{node_id}")
            workflow[node_id].setdefault("inputs", {})
            required = bool(target.get("required", False))
            target_value = _coerce_value(value, target)
            if required and (target_value is None or target_value == ""):
                raise RuntimeError(f"binding '{binding_key}' 缺少必填值。")
            if target_value is None:
                continue
            workflow[node_id]["inputs"][input_name] = target_value

    return workflow


def resolve_template_payload(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    workflow_json_text = str(payload.get("workflowJsonText") or "").strip()
    bindings_json_text = str(payload.get("bindingsJsonText") or "").strip()
    template_key = str(payload.get("templateKey") or "").strip()

    if workflow_json_text:
        template_payload = {
            "key": template_key or "inline_workflow",
            "label": template_key or "内联工作流",
            "workflow_type": str(payload.get("workflowType") or ""),
            "description": "Inline workflow JSON provided by the app UI.",
            "workflow": _safe_json_loads(workflow_json_text, "工作流 JSON"),
            "bindings": _safe_json_loads(bindings_json_text or "{}", "绑定 JSON"),
        }
        return template_payload

    if not template_key:
        raise RuntimeError("请先选择工作流模板，或直接填写工作流 JSON。")
    return load_workflow_template(config, template_key)
