from __future__ import annotations

import json
import ntpath
import os
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


IMAGE_PROMPT_KIND = "image"
IMAGE_EDIT_PROMPT_KIND = "image_edit"
VIDEO_PROMPT_KIND = "video"


@dataclass(frozen=True)
class DemoDefaults:
    api_key: str = ""
    base_url: str = "https://apinebula.ai/v1"
    model: str = "Prompt"
    output_root: str = ""
    image_output_root: str = ""
    image_edit_output_root: str = ""
    video_output_root: str = ""


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def project_relative_path_text(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_root().resolve()).as_posix()
    except ValueError:
        try:
            return resolved.relative_to(backend_root().resolve()).as_posix()
        except ValueError:
            return str(resolved)


def default_output_root(kind: str | None = None) -> Path:
    return project_root() / "output"


def default_output_root_text(kind: str | None = None) -> str:
    return project_relative_path_text(default_output_root(kind))


def normalize_path_style(value: Any) -> str:
    style = str(value or "").strip().lower()
    return style if style in {"", "windows", "linux"} else ""


def is_absolute_path_text(value: str | None, path_style: str | None = None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if Path(text).is_absolute():
        return True
    style = normalize_path_style(path_style)
    if style == "linux":
        return posixpath.isabs(text.replace("\\", "/"))
    if style == "windows":
        return ntpath.isabs(text)
    return False


def _normalize_relative_output_dir_text(text: str) -> str:
    normalized = Path(text).as_posix().strip()
    normalized = normalized.lstrip("./")
    lowered = normalized.lower()
    legacy_values = {
        "outputs",
        "outputs/image",
        "outputs/video",
        "backend/outputs",
        "backend/outputs/image",
        "backend/outputs/video",
        "output/image",
        "output/video",
    }
    if lowered in legacy_values:
        return "output"
    return normalized


def _normalize_output_path_text(value: str | None, path_style: str | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text)
    if not is_absolute_path_text(text, path_style):
        return _normalize_relative_output_dir_text(path.as_posix())
    if not path.is_absolute():
        return text.replace("\\", "/") if normalize_path_style(path_style) == "linux" else str(path).replace("\\", "/")
    resolved = path.resolve()
    lowered_parts = [part.lower() for part in resolved.parts]
    if "backend" in lowered_parts:
        backend_index = lowered_parts.index("backend")
        trailing_parts = resolved.parts[backend_index + 1 :]
        if trailing_parts:
            return _normalize_relative_output_dir_text(Path(*trailing_parts).as_posix())
    for base in (backend_root().resolve(), project_root().resolve()):
        try:
            return _normalize_relative_output_dir_text(resolved.relative_to(base).as_posix())
        except ValueError:
            continue
    return str(path).replace("\\", "/")


def resolve_output_path(value: str | None, kind: str | None = None, path_style: str | None = None) -> Path:
    text = str(value or "").strip()
    if not text:
        return default_output_root(kind)
    if is_absolute_path_text(text, path_style):
        return Path(text).expanduser()
    path = Path(text)
    normalized = _normalize_relative_output_dir_text(path.as_posix())
    return (project_root() / normalized).resolve()


def default_upload_root() -> Path:
    return backend_root() / "uploads"


def api_config_path() -> Path:
    return backend_root() / "api_config.json"


def comfy_config_path() -> Path:
    return backend_root() / "comfyui_comm_config.json"


def comfy_workflow_manifest_dir() -> Path:
    return project_root() / "workflow"


def _prompt_config_filename(kind: str) -> str:
    if kind == IMAGE_PROMPT_KIND:
        return "image_prompt_config.json"
    if kind == IMAGE_EDIT_PROMPT_KIND:
        return "image_edit_prompt_config.json"
    if kind == VIDEO_PROMPT_KIND:
        return "video_prompt_config.json"
    raise ValueError(f"Unsupported prompt config kind: {kind}")


def prompt_config_path(kind: str = IMAGE_PROMPT_KIND) -> Path:
    return backend_root() / _prompt_config_filename(kind)


def default_prompt_config(kind: str) -> dict[str, Any]:
    if kind == IMAGE_PROMPT_KIND:
        return {
            "system_prompt": """You are an expert image-to-video prompt director and prompt generator.

Your job is to observe the input image and generate production-ready prompts for an Image-to-Video model.

Core objective:
Animate the existing image naturally without redesigning it into a new scene.

Rules:
1. Treat the input image as the single source of truth. Do not invent important subjects, props, text, logos, background structures, or events that are not clearly supported by the image.
2. Preserve the original subject identity, facial features, hairstyle, clothing, colors, materials, object shapes, object count, scene layout, composition, lighting logic, and overall visual style unless tiny motion-related variation is necessary.
3. The prompt should function as animation direction, not as a static image caption. Focus on:
   - what must remain unchanged,
   - who or what should move,
   - how the motion happens,
   - how the camera behaves,
   - what subtle environmental motion is allowed,
   - what errors and unsafe outcomes must be avoided.
4. Prefer plausible motion that fits the image. If the action is ambiguous, choose subtle, natural, restrained motion rather than dramatic scene changes.
5. The Chinese prompt must clearly include:
   - preserving the original image,
   - main subject,
   - core action,
   - motion direction, range, and speed,
   - initial state and final state,
   - camera language,
   - timing and rhythm,
   - environmental motion,
   - composition and spatial stability,
   - visual style and quality,
   - mood,
   - unchanged elements,
   - negative constraints.
6. The English prompt should be natural, concise but complete, and ready to submit directly to an image-to-video model.
7. Include strong negative constraints against:
   - identity drift,
   - face, hand, or body distortion,
   - clothing changes,
   - background reconstruction,
   - object count changes,
   - flicker,
   - sudden camera cuts,
   - watermarks,
   - unreadable or garbled text,
   - private or sensitive information,
   - unsafe content.
8. If the image contains a person, prioritize face, identity, clothing, hands, and body stability.
9. If the image contains a product, package, document, logo, or visible text, prioritize exact consistency of shape, material, color, logo, and text content.
10. If the image is a landscape, architecture, or still life, prioritize layout stability, structure preservation, object count consistency, and natural environmental motion.
11. Keep the prompt clear but restrained. Do not overbuild a new story.
12. Return strict JSON only. Do not use Markdown. Do not add explanations.

JSON schema:
{
  "subject": "main subject",
  "scene_summary": "brief description of the input image",
  "zh_prompt": "complete Chinese image-to-video prompt",
  "en_prompt": "complete English image-to-video prompt",
  "keep_unchanged": ["elements that must remain unchanged"],
  "avoid": ["problems to avoid"],
  "quality_check": ["items to check after generation"]
}
""",
            "user_text": """Generate an image-to-video prompt based on this input image.

Work in this order:
1. Briefly identify the visible scene and the main subject the user will care about most.
2. Decide the minimal natural motion that can turn the still image into a short video without redesigning the scene.
3. Describe how the motion starts and how it ends, including direction, range, and speed.
4. Add camera language, timing and rhythm, and subtle environmental motion that fit the image.
5. Explicitly state what must remain unchanged.
6. Add concise negative constraints and quality-check items.

Requirements for the Chinese prompt:
- Start by stating that the video is generated from the input image and that the original subject and scene should remain consistent.
- Clearly include:
  - subject,
  - core action,
  - motion direction, range, and speed,
  - initial state and final state,
  - camera language,
  - timing and rhythm,
  - environmental motion,
  - composition and spatial stability,
  - visual style and quality,
  - mood,
  - unchanged elements,
  - things to avoid.
- Write it as animation direction, not as a rewritten scene description.
- Keep it clear, complete, and restrained.

Requirements for the English prompt:
- Write a natural, model-ready paragraph.
- Emphasize animation direction more than static scene description.
- Keep the prompt complete but not verbose.
- Do not introduce new unseen subjects, props, or story beats.

Quality expectations:
- The prompt should help the video remain faithful to the original image.
- The prompt should reduce identity drift, deformation, flicker, background changes, and unsafe output.
""",
            "mock_result": {
                "subject": "{stem}",
                "scene_summary": "Mock prompt for the reference frame {image_name}",
                "zh_prompt": "基于输入图片生成一段短视频，保持原图中的 {stem}、主体身份、构图、镜头视角、背景布局、色彩关系和整体风格一致。让主体产生自然且克制的连续动作，动作幅度小而明确，起始状态与原图高度衔接，结束状态只做轻微推进。镜头运动稳定，可使用轻微推拉、平移或静稳跟随，环境中仅加入与场景一致的细小动态变化。避免新增人物或物体，避免改变身份、服装、文字或 logo，避免出现闪烁、镜头跳变、背景重构、脸部或手部畸形、水印、乱码或不安全内容。",
                "en_prompt": "Generate a short image-to-video result from the input image while keeping the original {stem}, subject identity, framing, camera viewpoint, background layout, color relationships, and overall visual style consistent. Introduce a small but clear natural motion progression for the main subject, with the starting state closely matching the source image and the ending state advancing only slightly. Keep the camera stable with subtle push, pan, or gentle follow movement if needed, allow only minimal scene-consistent environmental motion, and avoid adding new subjects or objects, changing identity, outfit, text, or logo, or introducing flicker, camera jumps, background reconstruction, face or hand distortion, watermarks, unreadable text, or unsafe content.",
                "keep_unchanged": [
                    "subject identity and appearance",
                    "scene layout, framing, and camera viewpoint",
                    "background structure and object count",
                    "colors, materials, and overall style",
                ],
                "avoid": [
                    "scene redesign or extra subjects",
                    "identity drift or body deformation",
                    "flicker, sudden camera cuts, or background reconstruction",
                    "watermarks, gibberish text, or unsafe content",
                ],
                "quality_check": [
                    "the motion feels natural and continuous",
                    "subject identity and structure remain stable",
                    "background layout and object positions stay highly consistent",
                    "no flicker, distortion, watermark, or unreadable text",
                ],
            },
        }

    if kind == IMAGE_EDIT_PROMPT_KIND:
        return {
            "system_prompt": """You are an expert image-to-image editing prompt designer and prompt generator.
Observe the input image carefully and generate production-ready prompts for an Image-to-Image editing model.

Core objective:
Create a controlled edit prompt that keeps the original image highly recognizable while making only a minimal, useful, visually coherent change.

Rules:
1. Treat the input image as the source of truth. Do not invent important subjects, props, text, logos, or background structures that are not clearly supported by the image.
2. Preserve the original subject identity, pose, composition, layout, object count, background structure, lighting logic, and overall visual style unless the chosen edit explicitly requires a small change.
3. Because no user edit instruction is provided, infer one conservative, high-value edit direction from the image itself. Prefer refinement, styling, material enhancement, lighting polish, or one limited attribute adjustment over dramatic scene redesign.
4. The prompt must read like editing direction, not like a full scene rewrite. Focus on: what stays unchanged, what gets edited, how much it changes, whether the edit is local or global, what visual qualities to emphasize, and what artifacts or unsafe outcomes must be avoided.
5. If the image contains a person, prioritize identity, face, body, clothing, and hand stability.
6. If the image contains a product, package, document, logo, or visible text, prioritize exact preservation of text, logo, geometry, material logic, and brand structure.
7. If the image contains landscape, architecture, still life, or interior content, prioritize layout stability, object count consistency, and avoidance of unintended regional edits.
8. The Chinese prompt must clearly include: preserving the original image, edit target, edit type, desired result, local/global edit scope, style and quality, unchanged elements, and negative constraints.
9. The English prompt should be natural, concise but complete, and ready to submit directly to an image-editing model.
10. Include strong negative constraints against identity drift, face or hand distortion, object count changes, unwanted region edits, background reconstruction, text corruption, logo changes, watermarks, unreadable text, and unsafe content.
11. Return strict JSON only. Do not use Markdown. Do not add explanations.

JSON schema:
{
  "subject": "main subject",
  "source_summary": "brief description of the input image",
  "edit_goal": "the conservative edit direction inferred from the image",
  "zh_prompt": "complete Chinese image-to-image editing prompt",
  "en_prompt": "complete English image-to-image editing prompt",
  "keep_unchanged": ["elements that must remain unchanged"],
  "add_or_emphasize": ["what to edit, add, refine, or emphasize"],
  "avoid": ["problems to avoid"],
  "quality_check": ["items to check after generation"]
}
""",
            "user_text": """Generate an image-to-image editing prompt based on this input image.

Work in this order:
1. Briefly identify the visible scene and the main subject the user will care about most.
2. Infer one conservative edit goal that improves, stylizes, or adjusts the image without redesigning the whole scene.
3. Specify which part should be edited, whether the change is local or global, and how far the edit should go.
4. Explicitly state what must remain unchanged.
5. Add style, quality, and negative constraints.
6. Add concise quality-check items.

Requirements for the Chinese prompt:
- Start by stating that the result should be edited from the input image while preserving the original subject and layout as much as possible.
- Clearly include: subject, edit target, edit type, desired result, local/global scope, style and quality, unchanged elements, and things to avoid.
- Emphasize minimal necessary change rather than complete redraw.
- If the image contains a person, prioritize identity, face, body, hands, and clothing stability.
- If the image contains a product, document, logo, or visible text, prioritize exact preservation of structure, text, logo, and material logic.
- If the image is a landscape, architecture, or still life, prioritize stable layout and preventing unrelated regions from being changed.

Requirements for the English prompt:
- Write a natural, model-ready paragraph.
- Emphasize controlled editing rather than scene rewriting.
- Keep the prompt complete but not verbose.
""",
            "mock_result": {
                "subject": "{stem}",
                "source_summary": "Mock image-edit prompt for {image_name}",
                "edit_goal": "Apply a conservative image edit that enhances the visual quality of {stem} while preserving the original composition and identity.",
                "zh_prompt": "基于输入图片进行图生图编辑，尽量保持原图中的 {stem}、构图、背景布局、物体数量与整体风格不变。仅对主体相关的质感、光影层次与局部视觉重点做有限且可控的优化增强，使结果更精致、更统一，但不要重构场景或新增无关元素。编辑范围以主体与关键视觉区域为主，整体保持自然写实和高细节质感。避免改变主体身份、姿态、文字、logo、背景结构或数量关系，避免未指定区域被误改，避免出现脸部或手部畸形、边缘脏污、伪影、水印、乱码文字或不安全内容。",
                "en_prompt": "Edit the input image with a minimal, controlled enhancement while preserving the original {stem}, composition, background layout, object count, and overall visual style. Refine the subject-related texture, lighting hierarchy, and focal details only where beneficial, keeping the scene recognizable and avoiding a full redesign. Keep the edit limited to the key visual regions, maintain a natural high-detail look, and avoid identity changes, pose drift, text or logo changes, background reconstruction, unrelated region edits, distortion, artifacts, watermarks, unreadable text, or unsafe content.",
                "keep_unchanged": [
                    "subject identity and core appearance",
                    "composition and background layout",
                    "object count and spatial relationships",
                    "text, logo, and overall scene structure",
                ],
                "add_or_emphasize": [
                    "controlled texture refinement",
                    "cleaner lighting hierarchy",
                    "more focused visual emphasis on the main subject",
                ],
                "avoid": [
                    "over-redesign or scene rewriting",
                    "identity drift or body distortion",
                    "unintended changes to unrelated regions",
                    "artifacts, watermarks, gibberish text, or unsafe content",
                ],
                "quality_check": [
                    "the edited result still clearly matches the source image",
                    "only intended regions or attributes are changed",
                    "subject identity and layout remain stable",
                    "no distortion, artifact, watermark, or unreadable text",
                ],
            },
        }

    if kind == VIDEO_PROMPT_KIND:
        return {
            "system_prompt": """You are a professional video-to-video prompt generator specialized in character replacement.
You will receive the source video as a publicly accessible URL, followed by one or more reference images provided as publicly accessible URLs.

Core objective:
Preserve the source video's scene, action, camera movement, timing, composition, background, lighting logic, and narrative flow as much as possible, while replacing the main target person with the person shown in the reference images.

Rules:
1. Treat the first media item as the source video to be understood and preserved.
2. Treat the remaining media items as identity and appearance references for the replacement person.
3. The main goal is character replacement, not full scene redesign, style transfer of the whole video, or camera re-staging.
4. Analyze the source video carefully, including the main person or people, scene, action, motion trajectory, camera movement, timing, continuity, and important composition.
5. Analyze the reference images carefully, including face identity, hairstyle, facial traits, age impression, skin tone, body shape if visible, clothing or accessories if clearly visible, and other appearance cues that are reliable enough to transfer.
6. Replace only the main target person's identity and visible appearance with the reference person while preserving the original action logic, pose progression, motion path, camera logic, background structure, and scene continuity as much as possible.
7. If the reference images do not provide enough information for some attributes, do not invent overly specific unsupported details. Use conservative language and keep missing parts aligned with the source video where reasonable.
8. If multiple people appear in the source video, assume only the main target person should be replaced unless the source content strongly indicates otherwise. Do not unintentionally modify background people.
9. Explicitly prioritize temporal consistency, face consistency, body consistency, hand consistency, motion continuity, and natural integration of the new identity into the original video.
10. Explicitly avoid background corruption, identity drift, pose mismatch, extra limbs, scene rewriting, accidental replacement of other people, and frame-to-frame flicker.
11. Output both a Chinese prompt and an English prompt.
12. Return strict JSON only. Do not use Markdown. Do not add explanations.

JSON schema:
{
  "source_summary": "brief summary of the source video content, including person, scene, action, and camera",
  "reference_summary": "brief summary of the replacement person's identity and visible appearance from the reference images",
  "edit_goal": "clear statement that the source video's target person should be replaced by the reference person while preserving scene and motion",
  "zh_prompt": "complete Chinese video editing prompt for character replacement",
  "en_prompt": "complete English video editing prompt for character replacement",
  "keep_unchanged": ["elements that must remain unchanged"],
  "add_or_emphasize": ["replacement-related elements to emphasize"],
  "avoid": ["problems to avoid"],
  "quality_check": ["things to verify in the final result"]
}
""",
            "user_text": """Generate a video-editing prompt for character replacement.

Please first understand the source video itself:
- who appears in the video
- what the main target person is doing
- what the scene and environment are
- how the camera moves
- what the composition, shot continuity, and timing are
- what should remain unchanged

Then understand the reference images:
- who the replacement person is
- what identity and appearance traits are clearly visible
- which traits are reliable enough to transfer
- which traits are unclear or incomplete

Then generate a prompt that:
- replaces the main target person in the source video with the person from the reference images
- preserves the source video's scene, environment, action logic, pose logic, camera movement, shot continuity, timing, background structure, lighting logic, and narrative flow as much as possible
- keeps non-target people and non-target objects unchanged unless absolutely necessary
- makes the replaced person look like the reference person in identity and visible appearance
- keeps the new person naturally integrated into the original video action and scene

The Chinese prompt must clearly describe:
- the original video content
- the target person to be replaced
- the replacement identity from the reference images
- the scene, action, and camera continuity that should be preserved
- the replacement traits that should be emphasized
- what should remain unchanged
- what problems must be avoided

The English prompt should be complete, natural, production-ready, and directly usable for a video editing or generation model.

Important priorities:
- preserve source action, camera path, and scene structure
- replace person identity accurately
- keep temporal consistency
- keep face, body, and hand consistency
- avoid flicker, identity drift, background corruption, pose mismatch, extra limbs, or accidental changes to other people
""",
            "mock_result": {
                "source_summary": "Mock source summary for {video_name}",
                "reference_summary": "Reference images: {reference_names}",
                "edit_goal": "Replace the main target person in the source video with the person from the reference images while preserving the original scene, action, camera logic, and temporal continuity.",
                "zh_prompt": "请基于源视频 {video_name} 进行人物替换式视频编辑，将主目标人物替换为参考图像 {reference_names} 中的人物身份与可见外观特征，同时尽量保留原视频的动作轨迹、姿态逻辑、镜头运动、场景布局、背景结构、光照逻辑、节奏与叙事连续性。替换后的人物应在脸部、发型、体态和整体身份上与参考图像一致，并自然融入原视频动作与环境。不要误改其他人物，不要改变非目标物体和背景，不要出现身份漂移、脸手畸形、肢体错位、闪烁、背景重构、时序跳变、水印、乱码或不安全内容。",
                "en_prompt": "Edit the source video {video_name} by replacing the main target person with the person shown in the reference images {reference_names}, while preserving the original action trajectory, pose logic, camera movement, scene layout, background structure, lighting logic, rhythm, and narrative continuity as much as possible. The replaced person should match the reference identity and visible appearance in face, hairstyle, body impression, and overall character presence, and should integrate naturally into the original motion and environment. Do not alter other people, non-target objects, or the background, and avoid identity drift, face or hand distortion, body mismatch, flicker, background corruption, temporal instability, watermarks, unreadable text, or unsafe content.",
                "keep_unchanged": [
                    "source camera motion and shot continuity",
                    "scene layout and background structure",
                    "non-target people and non-target objects",
                ],
                "add_or_emphasize": [
                    "reference identity and facial traits",
                    "body and hand consistency",
                    "natural integration into the original motion",
                ],
                "avoid": [
                    "identity drift or accidental replacement of other people",
                    "flicker, pose mismatch, or temporal instability",
                    "background corruption or over-redesign",
                ],
                "quality_check": [
                    "the replaced person consistently matches the reference identity",
                    "motion, camera, and continuity remain natural",
                    "no background corruption, flicker, or structural distortion",
                ],
            },
        }

    raise ValueError(f"Unsupported prompt config kind: {kind}")


def default_api_config(kind: str | None = None) -> dict[str, Any]:
    base_url = os.getenv("APINEBULA_BASE_URL", "https://apinebula.ai/v1")
    model = os.getenv("APINEBULA_MODEL", "Prompt")
    full = {
        IMAGE_PROMPT_KIND: {
            "api_key": "",
            "base_url": base_url,
            "model": model,
            "output_dir": default_output_root_text(IMAGE_PROMPT_KIND),
            "source_root_dir": "",
            "path_style": "linux",
            "use_mock": True,
            "overwrite": False,
        },
        IMAGE_EDIT_PROMPT_KIND: {
            "api_key": "",
            "base_url": base_url,
            "model": model,
            "output_dir": default_output_root_text(IMAGE_EDIT_PROMPT_KIND),
            "source_root_dir": "",
            "path_style": "linux",
            "use_mock": True,
            "overwrite": False,
        },
        VIDEO_PROMPT_KIND: {
            "api_key": "",
            "base_url": base_url,
            "model": model,
            "output_dir": default_output_root_text(VIDEO_PROMPT_KIND),
            "video_source_root_dir": "",
            "reference_source_root_dir": "",
            "path_style": "linux",
            "use_mock": True,
            "overwrite": False,
        },
    }
    if kind is None:
        return full
    if kind not in full:
        raise ValueError(f"Unsupported API config kind: {kind}")
    return dict(full[kind])


def _merge_dict(default: dict[str, Any], value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return dict(default)
    merged = dict(default)
    for key, default_value in default.items():
        if isinstance(default_value, dict):
            merged[key] = _merge_dict(default_value, value.get(key))
        else:
            merged[key] = value.get(key, default_value)
    for key, item in value.items():
        if key not in merged:
            merged[key] = item
    return merged


def merge_prompt_config(kind: str, config: dict[str, Any] | None) -> dict[str, Any]:
    return _merge_dict(default_prompt_config(kind), config)


def _merge_api_config(config: dict[str, Any] | None) -> dict[str, Any]:
    defaults = default_api_config()
    raw = config if isinstance(config, dict) else {}
    merged = {
        IMAGE_PROMPT_KIND: _merge_dict(defaults[IMAGE_PROMPT_KIND], raw.get(IMAGE_PROMPT_KIND)),
        IMAGE_EDIT_PROMPT_KIND: _merge_dict(defaults[IMAGE_EDIT_PROMPT_KIND], raw.get(IMAGE_EDIT_PROMPT_KIND)),
        VIDEO_PROMPT_KIND: _merge_dict(defaults[VIDEO_PROMPT_KIND], raw.get(VIDEO_PROMPT_KIND)),
    }
    for kind in (IMAGE_PROMPT_KIND, IMAGE_EDIT_PROMPT_KIND, VIDEO_PROMPT_KIND):
        merged[kind]["path_style"] = normalize_path_style(merged[kind].get("path_style"))
    merged[IMAGE_PROMPT_KIND]["output_dir"] = _normalize_output_path_text(
        merged[IMAGE_PROMPT_KIND].get("output_dir"),
        merged[IMAGE_PROMPT_KIND].get("path_style"),
    )
    merged[IMAGE_PROMPT_KIND]["source_root_dir"] = _normalize_output_path_text(
        merged[IMAGE_PROMPT_KIND].get("source_root_dir"),
        merged[IMAGE_PROMPT_KIND].get("path_style"),
    )
    merged[IMAGE_EDIT_PROMPT_KIND]["output_dir"] = _normalize_output_path_text(
        merged[IMAGE_EDIT_PROMPT_KIND].get("output_dir"),
        merged[IMAGE_EDIT_PROMPT_KIND].get("path_style"),
    )
    merged[IMAGE_EDIT_PROMPT_KIND]["source_root_dir"] = _normalize_output_path_text(
        merged[IMAGE_EDIT_PROMPT_KIND].get("source_root_dir"),
        merged[IMAGE_EDIT_PROMPT_KIND].get("path_style"),
    )
    merged[VIDEO_PROMPT_KIND]["output_dir"] = _normalize_output_path_text(
        merged[VIDEO_PROMPT_KIND].get("output_dir"),
        merged[VIDEO_PROMPT_KIND].get("path_style"),
    )
    merged[VIDEO_PROMPT_KIND]["video_source_root_dir"] = _normalize_output_path_text(
        merged[VIDEO_PROMPT_KIND].get("video_source_root_dir"),
        merged[VIDEO_PROMPT_KIND].get("path_style"),
    )
    merged[VIDEO_PROMPT_KIND]["reference_source_root_dir"] = _normalize_output_path_text(
        merged[VIDEO_PROMPT_KIND].get("reference_source_root_dir"),
        merged[VIDEO_PROMPT_KIND].get("path_style"),
    )
    for key, value in raw.items():
        if key not in merged:
            merged[key] = value
    return merged


def load_prompt_config(kind: str = IMAGE_PROMPT_KIND) -> dict[str, Any]:
    path = prompt_config_path(kind)
    if not path.exists():
        defaults = default_prompt_config(kind)
        save_prompt_config(kind, defaults)
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_prompt_config(kind)
    return merge_prompt_config(kind, raw if isinstance(raw, dict) else {})


def save_prompt_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    path = prompt_config_path(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = merge_prompt_config(kind, config)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def load_api_config(kind: str | None = None) -> dict[str, Any]:
    path = api_config_path()
    if not path.exists():
        defaults = _merge_api_config({})
        path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
        return defaults if kind is None else dict(defaults[kind])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        defaults = _merge_api_config({})
        return defaults if kind is None else dict(defaults[kind])
    normalized = _merge_api_config(raw if isinstance(raw, dict) else {})
    if normalized != raw:
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized if kind is None else dict(normalized[kind])


def save_api_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    path = api_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_api_config()
    current[kind] = _merge_dict(default_api_config(kind), config if isinstance(config, dict) else {})
    current[kind]["path_style"] = normalize_path_style(current[kind].get("path_style"))
    current[kind]["output_dir"] = _normalize_output_path_text(
        current[kind].get("output_dir"),
        current[kind].get("path_style"),
    )
    if kind in {IMAGE_PROMPT_KIND, IMAGE_EDIT_PROMPT_KIND}:
        current[kind]["source_root_dir"] = _normalize_output_path_text(
            current[kind].get("source_root_dir"),
            current[kind].get("path_style"),
        )
    if kind == VIDEO_PROMPT_KIND:
        current[kind]["video_source_root_dir"] = _normalize_output_path_text(
            current[kind].get("video_source_root_dir"),
            current[kind].get("path_style"),
        )
        current[kind]["reference_source_root_dir"] = _normalize_output_path_text(
            current[kind].get("reference_source_root_dir"),
            current[kind].get("path_style"),
        )
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return dict(current[kind])


def default_comfy_config() -> dict[str, Any]:
    return {
        "comfy_base_url": "http://127.0.0.1:8188",
        "comfy_root_dir": "",
        "comfy_input_dir": "",
        "comfy_output_dir": "",
        "temp_dir": "output/comfy_temp",
        "path_style": "linux",
        "request_timeout_sec": 30,
        "job_timeout_sec": 1800,
        "poll_interval_sec": 2,
        "ws_enabled": True,
        "workflow_manifest_dir": "workflow",
    }


def _normalize_comfy_path_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute():
        return str(path).replace("\\", "/")
    return path.as_posix()


def _merge_comfy_config(config: dict[str, Any] | None) -> dict[str, Any]:
    defaults = default_comfy_config()
    raw = config if isinstance(config, dict) else {}
    merged = _merge_dict(defaults, raw)
    for key in ("comfy_root_dir", "comfy_input_dir", "comfy_output_dir", "temp_dir", "workflow_manifest_dir"):
        merged[key] = _normalize_comfy_path_text(merged.get(key))
    if str(merged.get("workflow_manifest_dir") or "").strip().lower() in {
        "backend/comfyui_workflows",
        "comfyui_workflows",
    }:
        merged["workflow_manifest_dir"] = defaults["workflow_manifest_dir"]
    merged["comfy_base_url"] = str(merged.get("comfy_base_url") or defaults["comfy_base_url"]).rstrip("/")
    merged["path_style"] = str(merged.get("path_style") or "").strip().lower()
    if merged["path_style"] not in {"", "windows", "linux"}:
        merged["path_style"] = ""
    for key in ("request_timeout_sec", "job_timeout_sec", "poll_interval_sec"):
        try:
            merged[key] = int(merged.get(key) or defaults[key])
        except (TypeError, ValueError):
            merged[key] = defaults[key]
    merged["ws_enabled"] = bool(merged.get("ws_enabled", True))
    return merged


def load_comfy_config() -> dict[str, Any]:
    path = comfy_config_path()
    if not path.exists():
        defaults = _merge_comfy_config({})
        path.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _merge_comfy_config({})
    normalized = _merge_comfy_config(raw if isinstance(raw, dict) else {})
    if normalized != raw:
        path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def save_comfy_config(config: dict[str, Any]) -> dict[str, Any]:
    path = comfy_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = _merge_comfy_config(config)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def load_defaults() -> DemoDefaults:
    return DemoDefaults(
        api_key="",
        base_url=os.getenv("APINEBULA_BASE_URL", "https://apinebula.ai/v1"),
        model=os.getenv("APINEBULA_MODEL", "Prompt"),
        output_root=default_output_root_text(),
        image_output_root=default_output_root_text(IMAGE_PROMPT_KIND),
        image_edit_output_root=default_output_root_text(IMAGE_EDIT_PROMPT_KIND),
        video_output_root=default_output_root_text(VIDEO_PROMPT_KIND),
    )


def normalize_base_url(value: str) -> str:
    if re.search(r"apinebula\.ai/v1/?$", value or ""):
        return "https://api.yhlxj.ai/v1"
    return (value or "").rstrip("/")
