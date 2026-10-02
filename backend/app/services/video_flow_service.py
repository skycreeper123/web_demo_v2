"""Persistent, sequential video recipes built on the existing Prompt and Comfy adapters.

Creating a recipe never submits generation work. A worker is claimed explicitly,
and each completed step owns named artifacts, so retries cannot silently reuse
outputs from an earlier version of an upstream step.
"""
from __future__ import annotations

import base64
import copy
import csv
import json
import math
import mimetypes
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from web_demo.backend.app.core.config import load_api_config, load_comfy_config, project_root
from web_demo.backend.app.core.llm_client import OpenAICompatibleClient
from web_demo.backend.app.services.comfyui_comm import run_comfy_job
from web_demo.backend.app.services.comfyui_comm.workflow_binder import resolve_template_payload
from web_demo.backend.app.services.video_flow_media import (
    assemble_video, finalize_spatial, prepare_temporal, probe_video,
)

FLOW_KIND = "video_flow"
FLOW_ROOT = project_root() / "output" / "video_flows"
_LOCK = threading.RLock()
_ACTIVE: set[str] = set()
_ID = re.compile(r"^[a-f0-9]{16}$")
MODES = {"spatial": "局部空间替换", "prefix": "替换前段", "suffix": "替换后段", "mixed": "混合替换"}
TEMPLATES = {
    "spatial": {"key": "Wan视频编辑V5-简易-替换单人-最新V2版模型.json", "output": "1400"},
    "first_image": {"key": "qwen2511图片编辑V1.json", "output": "144"},
    "motion": {"key": "wan2.2_14B_KJ版本_全功能.json", "output": "145"},
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def _directory(flow_id: str) -> Path:
    if not _ID.fullmatch(str(flow_id)):
        raise ValueError("流程编号无效。")
    return FLOW_ROOT / flow_id


def _save(flow: dict[str, Any]) -> None:
    directory = _directory(flow["id"])
    directory.mkdir(parents=True, exist_ok=True)
    flow["updatedAt"] = time.time()
    temporary = directory / "flow.json.tmp"
    temporary.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(directory / "flow.json")


def _load(flow_id: str) -> dict[str, Any]:
    path = _directory(flow_id) / "flow.json"
    if not path.is_file():
        raise FileNotFoundError("找不到此流程。")
    flow = json.loads(path.read_text(encoding="utf-8"))
    # A process restart cannot resume an in-memory Comfy/FFmpeg worker safely.
    if flow["status"] == "running" and flow_id not in _ACTIVE:
        flow["status"] = "failed"
        flow["error"] = "服务曾重启，当前步骤未确认完成；请检查服务器队列后重试此步骤。"
        for step in flow["steps"]:
            if step["status"] == "running":
                step.update(status="failed", error=flow["error"])
        _save(flow)
    return flow


def _artifact(key: str, path: str | Path, flow_id: str) -> dict[str, str]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    return {
        "key": key, "name": file_path.name, "path": str(file_path),
        "kind": "image" if suffix in _IMAGE_SUFFIXES else "video" if suffix in _VIDEO_SUFFIXES else "text",
        "url": f"/api/video-flows/{flow_id}/files/{key}",
    }


def _public(flow: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(flow)
    result["outputs"] = [item for step in result["steps"] for item in step["outputs"]]
    result["completedSteps"] = sum(step["status"] == "completed" for step in result["steps"])
    result["totalSteps"] = len(result["steps"])
    return result


def get_flow(flow_id: str) -> dict[str, Any]:
    with _LOCK:
        return _public(_load(flow_id))


def list_flows() -> list[dict[str, Any]]:
    with _LOCK:
        flows = []
        if FLOW_ROOT.exists():
            for path in FLOW_ROOT.glob("*/flow.json"):
                try:
                    flow = _public(_load(path.parent.name))
                except (ValueError, OSError, KeyError):
                    continue
                flows.append({key: flow[key] for key in (
                    "id", "name", "mode", "status", "createdAt", "updatedAt", "completedSteps", "totalSteps",
                )})
        return sorted(flows, key=lambda item: item["updatedAt"], reverse=True)


def flow_options() -> dict[str, Any]:
    return {"modes": [{"key": key, "label": label} for key, label in MODES.items()], "templates": TEMPLATES,
            "mixedOrder": "先空间替换，再对处理结果做前段或后段替换。", "cutMeaning": "切点为从原视频开始计算的秒数。"}


def _input_path(value: Any, label: str, suffixes: set[str], required: bool = True) -> str:
    text = str(value or "").strip()
    if not text and not required:
        return ""
    path = Path(text).expanduser()
    if not text or not path.is_file():
        raise ValueError(f"{label}不存在或不是服务器可读取的文件。")
    if path.suffix.lower() not in suffixes:
        raise ValueError(f"{label}格式不支持。")
    return str(path.resolve())


def create_flow(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("流程配置必须是对象。")
    mode = str(payload.get("mode") or "spatial")
    if mode not in MODES:
        raise ValueError("请选择有效的视频流程。")
    temporal = str(payload.get("temporalMode") or "prefix") if mode == "mixed" else mode
    if mode == "mixed" and temporal not in {"prefix", "suffix"}:
        raise ValueError("混合替换需要选择替换前段或后段。")
    spatial = mode in {"spatial", "mixed"}
    is_temporal = mode != "spatial"
    spatial_target = str(payload.get("spatialTarget") or "foreground")
    if spatial_target not in {"foreground", "background"}:
        raise ValueError("空间替换范围必须是前景或背景。")
    prompt_source = str(payload.get("promptSource") or "ai")
    if prompt_source not in {"ai", "manual"}:
        raise ValueError("提示词来源无效。")
    cut = float(payload.get("cutSeconds") or 0) if is_temporal else 0.0
    if is_temporal and (not math.isfinite(cut) or cut <= 0):
        raise ValueError("请填写大于 0 的切点秒数。")
    inputs = {
        "videoPath": _input_path(payload.get("videoPath"), "原视频", _VIDEO_SUFFIXES),
        "referenceImagePath": _input_path(payload.get("referenceImagePath"), "空间替换参考图", _IMAGE_SUFFIXES, spatial),
        "startImagePath": _input_path(payload.get("startImagePath"), "新首图", _IMAGE_SUFFIXES, False),
        "endImagePath": _input_path(payload.get("endImagePath"), "目标尾图", _IMAGE_SUFFIXES, is_temporal and temporal == "suffix"),
        "spatialTarget": spatial_target, "temporalMode": temporal, "cutSeconds": cut,
        "editInstruction": str(payload.get("editInstruction") or "").strip()[:12000],
        "keepAudio": payload.get("keepAudio", True) is not False, "promptSource": prompt_source,
    }
    flow_id = uuid.uuid4().hex[:16]
    flow: dict[str, Any] = {
        "id": flow_id, "name": str(payload.get("name") or f"{Path(inputs['videoPath']).stem} · {MODES[mode]}").strip()[:160],
        "mode": mode, "status": "draft", "createdAt": time.time(), "updatedAt": time.time(),
        "inputs": inputs, "steps": [], "artifacts": {}, "error": "", "jobId": "", "stopRequested": False,
        "media": {},
    }
    for key, field in (("source_video", "videoPath"), ("reference_image", "referenceImagePath"),
                       ("start_image", "startImagePath"), ("target_end", "endImagePath")):
        if inputs[field]:
            flow["artifacts"][key] = _artifact(key, inputs[field], flow_id)

    def add(step_id: str, title: str, kind: str, description: str, **settings: Any) -> None:
        dependency = [flow["steps"][-1]["id"]] if flow["steps"] else []
        flow["steps"].append({"id": step_id, "title": title, "kind": kind, "description": description,
                              "dependsOn": dependency, "status": "pending", "settings": settings,
                              "outputs": [], "error": "", "jobId": "", "attempts": 0})

    def prompt(step_id: str, title: str, instruction: str, media: list[str], api_kind: str) -> None:
        direction = instruction + (f"\n用户具体要求：{inputs['editInstruction']}" if inputs["editInstruction"] else "")
        add(step_id, title, "prompt", "生成后可编辑提示词；后续生成步骤自动读取保存的文字。",
            instruction=direction, prompt=direction if prompt_source == "manual" else "",
            negativePrompt="闪烁，主体变形，身份漂移，画面跳变，文字水印，未指定区域改变",
            promptEdited=prompt_source == "manual", media=media, apiKind=api_kind)

    if spatial:
        instruction = (
            "根据参考图替换原视频的前景主体。保留原背景、镜头、动作轨迹、时间节奏和非目标物体，保持跨帧外观一致。"
            if spatial_target == "foreground" else
            "根据参考图替换原视频的背景环境。保留原视频的前景主体身份、外观、动作和时间节奏；仅重建背景，匹配透视、光线和遮挡关系。"
        )
        prompt("spatial_prompt", "生成空间替换提示词", instruction, ["source_video", "reference_image"], "video")
        add("spatial_render", "生成空间替换视频", "comfy", "Wan 视频编辑 V5；按所选范围设置遮罩，并读取完整视频。",
            role="spatial", promptStep="spatial_prompt", outputKey="spatial_video")
    if is_temporal:
        add("prepare", "裁切并提取衔接帧", "media", "按切点保留原片段，提取实际保留片段的边界帧。",
            sourceKey="spatial_video" if spatial else "source_video")
        if temporal == "prefix" and not inputs["startImagePath"]:
            prompt("first_prompt", "生成新首图的编辑提示词",
                   "以原视频首帧为基础设计新的起始画面。保留主体身份、场景布局、镜头和光线，按用户要求调整起始状态，使后续动作能自然衔接原视频保留后段的首帧。描述一张静态图片的编辑要求。",
                   ["original_first_frame", "boundary_frame"], "image_edit")
            add("first_render", "生成新的首图", "comfy", "使用 Qwen 图片编辑，从原首帧生成新的起始画面。",
                role="first_image", promptStep="first_prompt", outputKey="start_image")
        motion_media = ["start_image", "boundary_frame"] if temporal == "prefix" else ["boundary_frame", "target_end"]
        prompt("motion_prompt", "生成首尾帧过渡提示词",
               "按输入的第一张首图到第二张尾图生成连续视频。准确描述起始状态、结束状态和两者之间的动作过渡，保留主体身份与镜头连贯性；在尾帧处自然衔接，避免突然切镜或多余动作。",
               motion_media, "image")
        add("motion_render", "双图生成替换片段", "comfy", "首图和尾图分别投递；生成长度按被替换片段计算。",
            role="motion", promptStep="motion_prompt", outputKey="replacement_video")
        add("assemble", "拼接并导出成片", "assemble", "按替换方向拼接、统一原片尺寸和帧率，并按设置恢复原音轨。")
    else:
        add("finish", "导出空间替换成片", "assemble", "使用纯生成输出，匹配原片尺寸、时长和帧率，并按设置恢复原音轨。")
    with _LOCK:
        _save(flow)
    return _public(flow)


def _step(flow: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in flow["steps"]:
        if step["id"] == step_id:
            return step
    raise ValueError("找不到此步骤。")


def _invalidate(flow: dict[str, Any], index: int) -> None:
    for step in flow["steps"][index:]:
        for output in step["outputs"]:
            flow["artifacts"].pop(output["key"], None)
        step.update(status="pending", outputs=[], error="", jobId="")
        if step["kind"] == "prompt" and not step["settings"].get("promptEdited"):
            step["settings"]["prompt"] = ""
    if any(step["id"] == "prepare" for step in flow["steps"][index:]):
        flow["media"] = {}
    flow.update(status="ready", error="")


def update_step(flow_id: str, step_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        flow = _load(flow_id)
        if flow_id in _ACTIVE:
            raise ValueError("流程正在执行，请等待当前步骤结束后再编辑。")
        step = _step(flow, step_id)
        if step["kind"] != "prompt":
            raise ValueError("仅提示词步骤支持编辑文字。")
        allowed = {"prompt", "negativePrompt", "instruction"}
        if not isinstance(payload, dict) or not payload or not set(payload).issubset(allowed):
            raise ValueError("请提供提示词、负向提示词或编辑指令。")
        for key, value in payload.items():
            if not isinstance(value, str) or len(value) > 24000:
                raise ValueError("提示词必须是 24000 字以内的文字。")
            step["settings"][key] = value.strip()
        if "prompt" in payload:
            step["settings"]["promptEdited"] = bool(payload["prompt"].strip())
        elif "instruction" in payload and flow["inputs"]["promptSource"] == "ai":
            step["settings"]["promptEdited"] = False
        elif "negativePrompt" in payload and step["settings"].get("prompt"):
            step["settings"]["promptEdited"] = True
        _invalidate(flow, flow["steps"].index(step))
        _save(flow)
        return _public(flow)


def claim_run(flow_id: str, job_id: str, step_id: str = "") -> dict[str, Any]:
    with _LOCK:
        flow = _load(flow_id)
        if flow_id in _ACTIVE:
            raise ValueError("此流程已经在执行中。")
        step = _step(flow, step_id) if step_id else next((s for s in flow["steps"] if s["status"] != "completed"), None)
        if step is None:
            raise ValueError("此流程已完成；如需重做，请选择具体步骤。")
        if any(_step(flow, dependency)["status"] != "completed" for dependency in step["dependsOn"]):
            raise ValueError("请先完成此步骤之前的步骤。")
        # Failed or completed reruns invalidate every dependent result.
        _invalidate(flow, flow["steps"].index(step))
        flow.update(status="running", jobId=job_id, error="", stopRequested=False, activeStep=step["id"])
        _ACTIVE.add(flow_id)
        try:
            _save(flow)
        except Exception:
            _ACTIVE.discard(flow_id)
            raise
        return _public(flow)


def request_stop(flow_id: str) -> dict[str, Any]:
    with _LOCK:
        flow = _load(flow_id)
        if flow_id in _ACTIVE:
            flow["stopRequested"] = True
            _save(flow)
        return _public(flow)


def resolve_flow_file(flow_id: str, key: str) -> Path:
    with _LOCK:
        flow = _load(flow_id)
        artifact = flow["artifacts"].get(key)
        if not artifact:
            raise FileNotFoundError("此素材尚未生成，或已被上游修改作废。")
        path = Path(artifact["path"])
        if not path.is_file():
            raise FileNotFoundError("素材文件不存在。")
        return path


def _path(flow: dict[str, Any], key: str) -> Path:
    item = flow["artifacts"].get(key)
    if not item or not Path(item["path"]).is_file():
        raise ValueError(f"缺少步骤素材：{key}，请重新执行生成该素材的步骤。")
    return Path(item["path"])


def _media_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _parse_prompt(text: str) -> tuple[str, str]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean).strip()
    try:
        value = json.loads(clean)
    except ValueError:
        if not clean:
            raise ValueError("提示词接口没有返回文字。")
        return clean, ""
    if not isinstance(value, dict):
        raise ValueError("提示词接口返回格式错误。")
    positive = str(value.get("positive_prompt") or value.get("en_prompt") or value.get("zh_prompt") or "").strip()
    negative = str(value.get("negative_prompt") or "").strip()
    if not positive:
        raise ValueError("提示词接口未返回有效的 positive_prompt。")
    return positive, negative


def _run_prompt(flow: dict[str, Any], step: dict[str, Any], directory: Path, log: Callable[[str], None]) -> list[dict[str, str]]:
    settings = step["settings"]
    prompt = str(settings.get("prompt") or "").strip()
    negative = str(settings.get("negativePrompt") or "").strip()
    media_paths = [_path(flow, key) for key in settings["media"]]
    if not (settings.get("promptEdited") and prompt):
        if flow["inputs"]["promptSource"] == "manual":
            if not prompt:
                raise ValueError("请先填写并保存此步骤的提示词。")
        else:
            config = load_api_config(settings["apiKind"])
            if config.get("use_mock", True):
                raise ValueError("对应 Prompt 模块仍启用了 Mock，请关闭 Mock 并保存 API 配置，或手动填写此步骤的提示词。")
            api_key = str(config.get("api_key") or "").strip()
            if not api_key:
                raise ValueError("请先在对应 Prompt 模块保存 API 密钥，或手动填写并保存此步骤的提示词。")
            client = OpenAICompatibleClient(base_url=str(config.get("base_url") or ""), api_key=api_key,
                                            model=str(config.get("model") or ""))
            media = [{"kind": "video" if p.suffix.lower() in _VIDEO_SUFFIXES else "image", "url": _media_url(p)} for p in media_paths]
            duration_text = f"\n目标片段时长：{flow['media']['replacement_duration']:.3f} 秒。" if step["id"] == "motion_prompt" else ""
            system = ("你是视频编辑流程的提示词设计师。按本次步骤要求和输入素材生成可直接用于模型的提示词。"
                      "不得把背景替换改成人物替换；双图任务必须同时理解两张图片。"
                      "只返回 JSON 对象，包含 positive_prompt 和 negative_prompt 两个字符串，不要添加解释。")
            log("使用已保存的 Prompt API 配置生成此步骤的提示词。")
            response = client.chat_with_media(system, settings["instruction"] + duration_text, media)
            prompt, generated_negative = _parse_prompt(response.text)
            negative = generated_negative or negative
    if not prompt:
        raise ValueError("提示词不能为空。")
    settings.update(prompt=prompt, negativePrompt=negative)
    prompt_file = directory / "prompt.txt"
    prompt_file.write_text(prompt + "\n\n负向提示词：\n" + negative, encoding="utf-8")
    # Retain an ordinary CSV as an escape hatch into the existing Comfy workbench.
    csv_file = directory / "prompts.csv"
    row = {"positive_prompt": prompt, "negative_prompt": negative, "image_path": "", "video_path": "",
           "start_image_path": "", "end_image_path": ""}
    if step["id"] == "motion_prompt":
        row.update(start_image_path=str(media_paths[0]), end_image_path=str(media_paths[1]))
    else:
        for path in media_paths:
            row["video_path" if path.suffix.lower() in _VIDEO_SUFFIXES else "image_path"] = str(path)
        if step["id"] == "first_prompt":
            row["image_path"] = str(media_paths[0])
    with csv_file.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return [_artifact(step["id"], prompt_file, flow["id"]), _artifact(step["id"] + "_csv", csv_file, flow["id"])]


def _run_comfy(flow: dict[str, Any], step: dict[str, Any], directory: Path, job_id: str,
               log: Callable[[str], None], update_job: Callable[..., Any]) -> list[dict[str, str]]:
    settings = step["settings"]
    role = settings["role"]
    template = TEMPLATES[role]
    prompt_settings = _step(flow, settings["promptStep"])["settings"]
    form: dict[str, Any] = {"positive_prompt": prompt_settings["prompt"], "negative_prompt": prompt_settings.get("negativePrompt", "")}
    expected: dict[str, Any] = {}
    if role == "spatial":
        form.update(image_ref=str(_path(flow, "reference_image")), video_ref=str(_path(flow, "source_video")))
        expected = {"params.node_1437.invert_output": flow["inputs"]["spatialTarget"] == "background",
                    "params.node_1412.frame_load_cap": 0, "params.node_1412.skip_first_frames": 0,
                    "params.node_1412.force_rate": 16}
    elif role == "first_image":
        form["image_ref"] = str(_path(flow, "original_first_frame"))
    else:
        prefix = flow["inputs"]["temporalMode"] == "prefix"
        form.update(start_image_ref=str(_path(flow, "start_image" if prefix else "boundary_frame")),
                    end_image_ref=str(_path(flow, "boundary_frame" if prefix else "target_end")))
        duration = float(flow["media"]["replacement_duration"])
        frames = max(5, math.ceil((duration * 16 - 1) / 4) * 4 + 1)
        expected = {"params.node_162.value": frames, "params.node_145.frame_rate": 16}
    # Fixed production recipes fail clearly if their graph was replaced or changed.
    resolved = resolve_template_payload({"templateKey": template["key"]}, load_comfy_config())
    missing = set(expected) - set(resolved["bindings"])
    required_media = {key for key in form if key.endswith("_ref")}
    missing |= required_media - set(resolved["bindings"])
    if missing or template["output"] not in resolved["workflow"]:
        raise ValueError("流程模板接口已变化，请检查绑定和输出节点：" + ", ".join(sorted(missing)))
    form.update(expected)
    payload = {"inputMode": "direct", "templateKey": template["key"], "outputNodeId": template["output"],
               "formInputs": form, "defaultOutputPrefixBase": f"video_flows/{flow['id']}/{step['id']}/{step['attempts']}"}
    stage_job_id = f"{job_id}_{step['id']}_{step['attempts']:03d}"
    result = run_comfy_job(job_id=stage_job_id, payload=payload, log=log, progress=lambda *_: None, update_job=update_job)
    if result.get("status") != "completed" or not result.get("items"):
        failures = result.get("failures") or []
        message = failures[0].get("message") if failures else result.get("status")
        if any(f.get("error_code") == "JOB_TIMEOUT" for f in failures):
            message = f"{message}；服务器任务可能仍在执行，请检查 Comfy 队列后再重试。"
        raise RuntimeError(f"Comfy 生成未完成：{message or '没有返回结果'}")
    source = Path(result["items"][0]["path"])
    wanted = _IMAGE_SUFFIXES if role == "first_image" else _VIDEO_SUFFIXES
    if not source.is_file() or source.suffix.lower() not in wanted:
        raise RuntimeError("指定的输出节点未返回此步骤需要的图片或视频。")
    target = directory / (settings["outputKey"] + source.suffix.lower())
    shutil.copy2(source, target)
    return [_artifact(settings["outputKey"], target, flow["id"])]


def _execute_step(flow: dict[str, Any], step: dict[str, Any], job_id: str,
                  log: Callable[[str], None], update_job: Callable[..., Any]) -> list[dict[str, str]]:
    directory = _directory(flow["id"]) / step["id"] / f"attempt_{step['attempts']:03d}"
    directory.mkdir(parents=True, exist_ok=True)
    inputs = flow["inputs"]
    if step["kind"] == "prompt":
        return _run_prompt(flow, step, directory, log)
    if step["kind"] == "comfy":
        return _run_comfy(flow, step, directory, job_id, log, update_job)
    if step["kind"] == "media":
        source = _path(flow, step["settings"]["sourceKey"])
        extra_outputs = []
        if step["settings"]["sourceKey"] == "spatial_video":
            normalized = directory / "spatial_normalized.mp4"
            finalize_spatial(source, _path(flow, "source_video"), normalized, keep_audio=False)
            source = normalized
            extra_outputs.append(_artifact("spatial_normalized", normalized, flow["id"]))
        media = prepare_temporal(source, directory, inputs["temporalMode"], inputs["cutSeconds"])
        flow["media"] = {key: value for key, value in media.items() if key not in {"retained_video", "boundary_frame", "original_first_frame"}}
        return extra_outputs + [_artifact(key, media[key], flow["id"]) for key in ("retained_video", "boundary_frame", "original_first_frame")]
    output = directory / "final.mp4"
    if step["id"] == "finish":
        finalize_spatial(_path(flow, "spatial_video"), _path(flow, "source_video"), output, keep_audio=inputs["keepAudio"])
    else:
        assemble_video(_path(flow, "retained_video"), _path(flow, "replacement_video"), _path(flow, "source_video"),
                       output, direction=inputs["temporalMode"], cut_seconds=inputs["cutSeconds"], keep_audio=inputs["keepAudio"])
    return [_artifact("final_video", output, flow["id"])]


def run_flow_steps(*, flow_id: str, job_id: str, run_all: bool,
                   log: Callable[[str], None], progress: Callable[[int, int], None],
                   update_job: Callable[..., Any]) -> dict[str, Any]:
    current_id = ""
    try:
        with _LOCK:
            flow = _load(flow_id)
            current_id = flow["activeStep"]
            start_index = next(i for i, step in enumerate(flow["steps"]) if step["id"] == current_id)
        # Check temporal bounds before any paid prompt or GPU request, including mixed recipes.
        if flow["mode"] != "spatial":
            source_meta = probe_video(_path(flow, "source_video"))
            cut = flow["inputs"]["cutSeconds"]
            if not 0 < cut < source_meta["duration"]:
                raise ValueError(f"切点必须在 0 到 {source_meta['duration']:.3f} 秒之间。")
            if min(cut, source_meta["duration"] - cut) < 1 / source_meta["fps"]:
                raise ValueError("切点两侧都必须至少保留一帧，请调整切点。")
        for index in range(start_index, len(flow["steps"])):
            with _LOCK:
                flow = _load(flow_id)
                if flow.get("stopRequested"):
                    break
                step = flow["steps"][index]
                current_id = step["id"]
                step.update(status="running", error="", jobId=job_id, attempts=step["attempts"] + 1)
                flow["activeStep"] = current_id
                _save(flow)
            log(f"步骤 {index + 1}/{len(flow['steps'])}：{step['title']}")
            outputs = _execute_step(flow, step, job_id, log, update_job)
            with _LOCK:
                # Preserve stop requests received while the long-running adapter was active.
                flow["stopRequested"] = _load(flow_id).get("stopRequested", False)
                step.update(status="completed", outputs=outputs, error="")
                for output in outputs:
                    flow["artifacts"][output["key"]] = output
                _save(flow)
            progress(index + 1, len(flow["steps"]))
            if not run_all:
                break
        with _LOCK:
            flow = _load(flow_id)
            complete = all(step["status"] == "completed" for step in flow["steps"])
            flow.update(status="completed" if complete else "ready", activeStep="", error="")
            _save(flow)
        log("流程已完成。" if complete else "当前步骤已保存，可检查结果后继续。")
        return {"status": "completed", "items": [o for s in flow["steps"] for o in s["outputs"]],
                "failures": [], "output_dir": str(_directory(flow_id)), "total": len(flow["steps"])}
    except Exception as exc:
        with _LOCK:
            flow = _load(flow_id)
            if current_id:
                _step(flow, current_id).update(status="failed", error=str(exc))
            flow.update(status="failed", error=str(exc), activeStep="")
            _save(flow)
        log(f"步骤失败：{exc}")
        return {"status": "failed", "items": [o for s in flow["steps"] for o in s["outputs"]],
                "failures": [{"step_id": current_id, "message": str(exc)}], "error": str(exc),
                "output_dir": str(_directory(flow_id)), "total": len(flow["steps"])}
    finally:
        with _LOCK:
            _ACTIVE.discard(flow_id)
