from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from web_demo.backend.app.core.config import IMAGE_PROMPT_KIND, load_prompt_config, merge_prompt_config
from web_demo.backend.app.core.llm_client import OpenAICompatibleClient
from web_demo.backend.app.utils.file_writer import ensure_dir, write_csv, write_json, write_text
from web_demo.backend.app.utils.image_loader import parse_data_url


@dataclass
class GeneratedAsset:
    image: str
    image_path: str
    subject: str
    scene_summary: str
    zh_prompt: str
    en_prompt: str
    positive_prompt: str
    negative_prompt: str
    keep_unchanged: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    quality_check: list[str] = field(default_factory=list)
    raw_response: str = ""
    json_file: str = ""
    txt_file: str = ""


DEFAULT_NEGATIVE_TERMS = [
    "identity drift",
    "face distortion",
    "hand distortion",
    "body deformation",
    "clothing change",
    "background reconstruction",
    "object count change",
    "flicker",
    "camera jump",
    "watermark",
    "garbled text",
    "unsafe content",
]


def _try_parse_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json\n", "", 1).replace("JSON\n", "", 1)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(cleaned[start : end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return None
    return None


def _format_placeholders(value: str, *, image_name: str, stem: str) -> str:
    return str(value).format(image_name=image_name, stem=stem)


def _mock_result(image_name: str, prompt_config: dict[str, Any]) -> dict[str, Any]:
    stem = Path(image_name).stem.replace("_", " ").strip() or "image"
    mock_config = prompt_config.get("mock_result", {})
    return {
        "subject": _format_placeholders(mock_config.get("subject", "{stem}"), image_name=image_name, stem=stem),
        "scene_summary": _format_placeholders(
            mock_config.get("scene_summary", "Mock prompt for {image_name}"),
            image_name=image_name,
            stem=stem,
        ),
        "zh_prompt": _format_placeholders(mock_config.get("zh_prompt", ""), image_name=image_name, stem=stem),
        "en_prompt": _format_placeholders(mock_config.get("en_prompt", ""), image_name=image_name, stem=stem),
        "keep_unchanged": list(mock_config.get("keep_unchanged", []) or []),
        "avoid": list(mock_config.get("avoid", []) or []),
        "quality_check": list(mock_config.get("quality_check", []) or []),
    }


def _format_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Chinese Prompt:\n{payload.get('zh_prompt', '')}",
        "",
        f"English Prompt:\n{payload.get('en_prompt', '')}",
        "",
        f"Positive Prompt:\n{payload.get('positive_prompt', '')}",
        "",
        f"Negative Prompt:\n{payload.get('negative_prompt', '')}",
        "",
        "Keep Unchanged:\n" + "; ".join(payload.get("keep_unchanged", []) or []),
        "",
        "Avoid:\n" + "; ".join(payload.get("avoid", []) or []),
        "",
        "Quality Check:\n" + "; ".join(payload.get("quality_check", []) or []),
    ]
    return "\n".join(lines).strip() + "\n"


def _create_timestamp_output_dir(output_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    candidate = output_root / timestamp
    suffix = 1
    while candidate.exists():
        candidate = output_root / f"{timestamp}_{suffix}"
        suffix += 1
    return ensure_dir(candidate)


def _derive_positive_prompt(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("positive_prompt") or "").strip()
    if explicit:
        return explicit
    return str(payload.get("en_prompt") or payload.get("zh_prompt") or "").strip()


def _derive_negative_prompt(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("negative_prompt") or "").strip()
    if explicit:
        return explicit
    avoid = payload.get("avoid", []) or []
    candidate_terms: list[str] = []
    if isinstance(avoid, list):
        for item in avoid:
            candidate_terms.extend(part.strip() for part in str(item).split(",") if part.strip())
    terms: list[str] = []
    seen: set[str] = set()
    for item in [*candidate_terms, *DEFAULT_NEGATIVE_TERMS]:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(item)
    return ", ".join(terms)


def _default_output_prefix(image_name: str) -> str:
    return f"comfy/image_to_video/{Path(image_name).stem}"


def _normalize_source_path(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    return str(Path(candidate).expanduser())


def _unique_media_path(root: Path, filename: str) -> Path:
    safe_name = Path(str(filename or "source.bin")).name or "source.bin"
    candidate = root / safe_name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        next_candidate = root / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def _materialize_local_source(
    *,
    job_output_dir: Path,
    source_path: str,
    data_url: str,
    filename: str,
) -> str:
    text = str(data_url or "").strip()
    if text.startswith("data:"):
        _, payload = parse_data_url(text)
        source_root = ensure_dir(job_output_dir / "source_media" / "images")
        target = _unique_media_path(source_root, filename)
        target.write_bytes(payload)
        return str(target)
    return source_path


def run_image_generation(
    *,
    job_id: str,
    images: list[dict[str, Any]],
    output_root: Path,
    api_key: str,
    base_url: str,
    model: str,
    overwrite: bool,
    use_mock: bool,
    prompt_config: dict[str, Any] | None,
    log: Callable[[str], None],
    progress: Callable[[int, int], None],
) -> dict[str, Any]:
    client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model)
    config = merge_prompt_config(IMAGE_PROMPT_KIND, prompt_config) if prompt_config else load_prompt_config(IMAGE_PROMPT_KIND)
    system_prompt = str(config.get("system_prompt", "")).strip()
    user_text = str(config.get("user_text", "")).strip()
    job_output_dir = _create_timestamp_output_dir(output_root)
    assets: list[GeneratedAsset] = []
    failures: list[dict[str, str]] = []
    total = len(images)

    for index, image in enumerate(images, start=1):
        name = image["name"]
        image_url = str(image.get("imageUrl") or image.get("dataUrl") or "")
        image_source_path = _materialize_local_source(
            job_output_dir=job_output_dir,
            source_path=_normalize_source_path(image.get("sourcePath")),
            data_url=str(image.get("dataUrl") or ""),
            filename=name,
        )
        stem = Path(name).stem
        json_path = job_output_dir / f"{stem}.prompt.json"
        txt_path = job_output_dir / f"{stem}.prompt.txt"

        try:
            if not overwrite and json_path.exists():
                log(f"Skip existing: {name}")
                continue

            log(f"Processing: {name}")
            if image_source_path:
                log(f"Source media staged: {image_source_path}")
            if use_mock or not api_key.strip():
                payload = _mock_result(name, config)
                raw_response = json.dumps(payload, ensure_ascii=False, indent=2)
            else:
                if not image_url:
                    raise RuntimeError("Missing source image URL.")
                response = client.chat_with_image(system_prompt, user_text, image_url)
                raw_response = response.text
                payload = _try_parse_json(raw_response) or {
                    "subject": "",
                    "scene_summary": "",
                    "zh_prompt": raw_response,
                    "en_prompt": "",
                    "negative_prompt": "",
                    "keep_unchanged": [],
                    "avoid": [],
                    "quality_check": [],
                    "raw_response": raw_response,
                }

            positive_prompt = _derive_positive_prompt(payload)
            negative_prompt = _derive_negative_prompt(payload)
            normalized = {
                "subject": payload.get("subject", ""),
                "scene_summary": payload.get("scene_summary", ""),
                "zh_prompt": payload.get("zh_prompt", ""),
                "en_prompt": payload.get("en_prompt", ""),
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "keep_unchanged": payload.get("keep_unchanged", []) or [],
                "avoid": payload.get("avoid", []) or [],
                "quality_check": payload.get("quality_check", []) or [],
                "raw_response": raw_response,
            }

            write_json(json_path, normalized)
            write_text(txt_path, _format_text(normalized))
            assets.append(
                GeneratedAsset(
                    image=name,
                    image_path=image_source_path,
                    subject=normalized["subject"],
                    scene_summary=normalized["scene_summary"],
                    zh_prompt=normalized["zh_prompt"],
                    en_prompt=normalized["en_prompt"],
                    positive_prompt=normalized["positive_prompt"],
                    negative_prompt=normalized["negative_prompt"],
                    keep_unchanged=list(normalized["keep_unchanged"]),
                    avoid=list(normalized["avoid"]),
                    quality_check=list(normalized["quality_check"]),
                    raw_response=raw_response,
                    json_file=str(json_path),
                    txt_file=str(txt_path),
                )
            )
            log(f"Saved: {json_path.name} / {txt_path.name}")
        except Exception as exc:
            failures.append({"image": name, "error": str(exc)})
            log(f"Failed: {name} -> {exc}")
        finally:
            progress(index, total)

    summary_rows = [
        {
            "image_path": item.image_path,
            "video_path": "",
            "image_name": item.image,
            "video_name": "",
            "positive_prompt": item.positive_prompt,
            "negative_prompt": item.negative_prompt,
            "seed": "",
            "output_prefix": _default_output_prefix(item.image),
            "params_json": "{}",
            "workflow_type": "image_to_video",
            "prompt_module": IMAGE_PROMPT_KIND,
            "image": item.image,
            "subject": item.subject,
            "scene_summary": item.scene_summary,
            "zh_prompt": item.zh_prompt,
            "en_prompt": item.en_prompt,
            "json_file": item.json_file,
            "txt_file": item.txt_file,
        }
        for item in assets
    ]
    write_csv(job_output_dir / "prompts.csv", summary_rows)

    return {
        "job_id": job_id,
        "output_dir": str(job_output_dir),
        "items": [item.__dict__ for item in assets],
        "failures": failures,
        "summary_file": str(job_output_dir / "prompts.csv"),
    }
