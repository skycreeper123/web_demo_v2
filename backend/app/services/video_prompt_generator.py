from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from web_demo.backend.app.core.config import VIDEO_PROMPT_KIND, load_prompt_config, merge_prompt_config
from web_demo.backend.app.core.llm_client import OpenAICompatibleClient
from web_demo.backend.app.utils.file_writer import ensure_dir, write_csv, write_json, write_text
from web_demo.backend.app.utils.image_loader import parse_data_url


@dataclass
class GeneratedVideoAsset:
    video: str
    video_path: str
    match_key: str
    image_path: str
    reference_main: str
    reference_alt_1: str
    reference_alt_2: str
    source_summary: str
    reference_summary: str
    edit_goal: str
    zh_prompt: str
    en_prompt: str
    positive_prompt: str
    negative_prompt: str
    keep_unchanged: list[str] = field(default_factory=list)
    add_or_emphasize: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    quality_check: list[str] = field(default_factory=list)
    raw_response: str = ""
    json_file: str = ""
    txt_file: str = ""


DEFAULT_NEGATIVE_TERMS = [
    "identity drift",
    "face distortion",
    "hand distortion",
    "body mismatch",
    "flicker",
    "temporal instability",
    "pose mismatch",
    "background corruption",
    "extra limbs",
    "accidental replacement of other people",
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


def _format_placeholders(value: str, *, video_name: str, stem: str, reference_names: str) -> str:
    return str(value).format(video_name=video_name, stem=stem, reference_names=reference_names)


def _mock_result(video_name: str, references: list[dict[str, str]], prompt_config: dict[str, Any]) -> dict[str, Any]:
    stem = Path(video_name).stem
    reference_names = ", ".join(reference["name"] for reference in references) if references else "none"
    mock_config = prompt_config.get("mock_result", {})
    return {
        "source_summary": _format_placeholders(
            mock_config.get("source_summary", "Mock source summary for {video_name}"),
            video_name=video_name,
            stem=stem,
            reference_names=reference_names,
        ),
        "reference_summary": _format_placeholders(
            mock_config.get("reference_summary", "Reference images: {reference_names}"),
            video_name=video_name,
            stem=stem,
            reference_names=reference_names,
        ),
        "edit_goal": _format_placeholders(
            mock_config.get("edit_goal", ""),
            video_name=video_name,
            stem=stem,
            reference_names=reference_names,
        ),
        "zh_prompt": _format_placeholders(mock_config.get("zh_prompt", ""), video_name=video_name, stem=stem, reference_names=reference_names),
        "en_prompt": _format_placeholders(mock_config.get("en_prompt", ""), video_name=video_name, stem=stem, reference_names=reference_names),
        "keep_unchanged": list(mock_config.get("keep_unchanged", []) or []),
        "add_or_emphasize": list(mock_config.get("add_or_emphasize", []) or []),
        "avoid": list(mock_config.get("avoid", []) or []),
        "quality_check": list(mock_config.get("quality_check", []) or []),
    }


def _format_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Edit Goal:\n{payload.get('edit_goal', '')}",
        "",
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
        "Add Or Emphasize:\n" + "; ".join(payload.get("add_or_emphasize", []) or []),
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


def _default_output_prefix(match_key: str) -> str:
    return f"comfy/video_edit/{match_key}"


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
    folder_name: str,
    source_path: str,
    data_url: str,
    filename: str,
) -> str:
    text = str(data_url or "").strip()
    if text.startswith("data:"):
        _, payload = parse_data_url(text)
        source_root = ensure_dir(job_output_dir / "source_media" / folder_name)
        target = _unique_media_path(source_root, filename)
        target.write_bytes(payload)
        return str(target)
    return source_path


def run_video_generation(
    *,
    job_id: str,
    videos: list[dict[str, Any]],
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
    config = merge_prompt_config(VIDEO_PROMPT_KIND, prompt_config) if prompt_config else load_prompt_config(VIDEO_PROMPT_KIND)
    system_prompt = str(config.get("system_prompt", "")).strip()
    base_user_text = str(config.get("user_text", "")).strip()
    job_output_dir = _create_timestamp_output_dir(output_root)
    assets: list[GeneratedVideoAsset] = []
    failures: list[dict[str, str]] = []
    total = len(videos)

    for index, video_item in enumerate(videos, start=1):
        video_name = str(video_item.get("name", "video"))
        match_key = str(video_item.get("matchKey") or Path(video_name).stem)
        references = list(video_item.get("references") or [])
        video_url = str(video_item.get("videoUrl") or video_item.get("videoDataUrl") or "")
        video_source_path = _materialize_local_source(
            job_output_dir=job_output_dir,
            folder_name="videos",
            source_path=_normalize_source_path(video_item.get("sourcePath")),
            data_url=str(video_item.get("videoDataUrl") or ""),
            filename=video_name,
        )
        reference_source_paths: dict[str, str] = {}
        for reference in references:
            reference_name = str(reference.get("name") or "").strip()
            if not reference_name:
                continue
            reference_source_paths[reference_name] = _materialize_local_source(
                job_output_dir=job_output_dir,
                folder_name="references",
                source_path=_normalize_source_path(reference.get("sourcePath")),
                data_url=str(reference.get("dataUrl") or ""),
                filename=reference_name,
            )
        reference_main = str(video_item.get("referenceMain") or "")
        reference_alt_1 = str(video_item.get("referenceAlt1") or "")
        reference_alt_2 = str(video_item.get("referenceAlt2") or "")
        reference_main_path = reference_source_paths.get(reference_main, "")
        json_path = job_output_dir / f"{match_key}.prompt.json"
        txt_path = job_output_dir / f"{match_key}.prompt.txt"

        try:
            if not overwrite and json_path.exists():
                log(f"Skip existing: {video_name}")
                continue

            log(f"Processing video: {video_name}")
            if video_source_path:
                log(f"Source video staged: {video_source_path}")
            if reference_main_path:
                log(f"Main reference staged: {reference_main_path}")
            if use_mock or not api_key.strip():
                payload = _mock_result(video_name, references, config)
                raw_response = json.dumps(payload, ensure_ascii=False, indent=2)
            else:
                if not video_url:
                    raise RuntimeError("Missing source video URL.")
                media_items = [{"kind": "video", "url": video_url}]
                media_items.extend(
                    {
                        "kind": "image",
                        "url": str(reference.get("url") or reference.get("dataUrl") or ""),
                    }
                    for reference in references
                    if reference.get("url") or reference.get("dataUrl")
                )
                reference_names = ", ".join(reference.get("name", "") for reference in references if reference.get("name")) or "none"
                user_text = (
                    f"{base_user_text}\n\n"
                    f"Source video file: {video_name}\n"
                    f"Reference images: {reference_names}\n"
                    "Media order: the first media item is the source video, and the remaining media items are reference images."
                )
                response = client.chat_with_media(system_prompt, user_text, media_items)
                raw_response = response.text
                payload = _try_parse_json(raw_response) or {
                    "source_summary": "",
                    "reference_summary": "",
                    "edit_goal": "",
                    "zh_prompt": raw_response,
                    "en_prompt": "",
                    "negative_prompt": "",
                    "keep_unchanged": [],
                    "add_or_emphasize": [],
                    "avoid": [],
                    "quality_check": [],
                    "raw_response": raw_response,
                }

            positive_prompt = _derive_positive_prompt(payload)
            negative_prompt = _derive_negative_prompt(payload)
            normalized = {
                "video": video_name,
                "video_path": video_source_path,
                "match_key": match_key,
                "image_path": reference_main_path,
                "reference_main": reference_main,
                "reference_alt_1": reference_alt_1,
                "reference_alt_2": reference_alt_2,
                "source_summary": payload.get("source_summary", ""),
                "reference_summary": payload.get("reference_summary", ""),
                "edit_goal": payload.get("edit_goal", ""),
                "zh_prompt": payload.get("zh_prompt", ""),
                "en_prompt": payload.get("en_prompt", ""),
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "keep_unchanged": payload.get("keep_unchanged", []) or [],
                "add_or_emphasize": payload.get("add_or_emphasize", []) or [],
                "avoid": payload.get("avoid", []) or [],
                "quality_check": payload.get("quality_check", []) or [],
                "raw_response": raw_response,
            }

            write_json(json_path, normalized)
            write_text(txt_path, _format_text(normalized))
            assets.append(
                GeneratedVideoAsset(
                    video=normalized["video"],
                    video_path=normalized["video_path"],
                    match_key=normalized["match_key"],
                    image_path=normalized["image_path"],
                    reference_main=normalized["reference_main"],
                    reference_alt_1=normalized["reference_alt_1"],
                    reference_alt_2=normalized["reference_alt_2"],
                    source_summary=normalized["source_summary"],
                    reference_summary=normalized["reference_summary"],
                    edit_goal=normalized["edit_goal"],
                    zh_prompt=normalized["zh_prompt"],
                    en_prompt=normalized["en_prompt"],
                    positive_prompt=normalized["positive_prompt"],
                    negative_prompt=normalized["negative_prompt"],
                    keep_unchanged=list(normalized["keep_unchanged"]),
                    add_or_emphasize=list(normalized["add_or_emphasize"]),
                    avoid=list(normalized["avoid"]),
                    quality_check=list(normalized["quality_check"]),
                    raw_response=raw_response,
                    json_file=str(json_path),
                    txt_file=str(txt_path),
                )
            )
            log(f"Saved: {json_path.name} / {txt_path.name}")
        except Exception as exc:
            failures.append({"video": video_name, "error": str(exc)})
            log(f"Failed: {video_name} -> {exc}")
        finally:
            progress(index, total)

    summary_rows = [
        {
            "image_path": item.image_path,
            "video_path": item.video_path,
            "image_name": item.reference_main,
            "video_name": item.video,
            "positive_prompt": item.positive_prompt,
            "negative_prompt": item.negative_prompt,
            "seed": "",
            "output_prefix": _default_output_prefix(item.match_key),
            "params_json": "{}",
            "workflow_type": "video_to_video",
            "prompt_module": VIDEO_PROMPT_KIND,
            "video": item.video,
            "match_key": item.match_key,
            "reference_main": item.reference_main,
            "reference_alt_1": item.reference_alt_1,
            "reference_alt_2": item.reference_alt_2,
            "source_summary": item.source_summary,
            "reference_summary": item.reference_summary,
            "edit_goal": item.edit_goal,
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
