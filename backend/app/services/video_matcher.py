from __future__ import annotations

from pathlib import Path
from typing import Any


SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _normalize_name(item: str | dict[str, Any]) -> str:
    if isinstance(item, dict):
        return str(item.get("name", "")).strip()
    return str(item).strip()


def build_video_matches(videos: list[str | dict[str, Any]], references: list[str | dict[str, Any]]) -> dict[str, Any]:
    normalized_videos = []
    for item in videos:
        name = _normalize_name(item)
        if name and Path(name).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            normalized_videos.append(name)

    normalized_references = []
    for item in references:
        name = _normalize_name(item)
        if name and Path(name).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            normalized_references.append(name)

    results: list[dict[str, Any]] = []
    summary = {
        "total": len(normalized_videos),
        "matched": 0,
        "partial_match": 0,
        "missing_reference": 0,
        "naming_conflict": 0,
    }

    for video_name in normalized_videos:
        match_key = Path(video_name).stem
        slot_candidates = {
            "reference_main": [name for name in normalized_references if Path(name).stem.lower() == match_key.lower()],
            "reference_alt_1": [name for name in normalized_references if Path(name).stem.lower() == f"{match_key.lower()}_1"],
            "reference_alt_2": [name for name in normalized_references if Path(name).stem.lower() == f"{match_key.lower()}_2"],
        }

        conflicts = {slot: files for slot, files in slot_candidates.items() if len(files) > 1}
        selected = {slot: files[0] if len(files) == 1 else "" for slot, files in slot_candidates.items()}

        if conflicts:
            status = "naming_conflict"
        elif not selected["reference_main"]:
            status = "missing_reference"
        elif selected["reference_alt_1"] or selected["reference_alt_2"]:
            status = "matched"
        else:
            status = "partial_match"

        summary[status] += 1
        results.append(
            {
                "video": video_name,
                "matchKey": match_key,
                "referenceMain": selected["reference_main"],
                "referenceAlt1": selected["reference_alt_1"],
                "referenceAlt2": selected["reference_alt_2"],
                "status": status,
                "canGenerate": status in {"matched", "partial_match"},
                "conflicts": conflicts,
            }
        )

    return {
        "matches": results,
        "summary": summary,
        "supportedVideoExtensions": sorted(SUPPORTED_VIDEO_EXTENSIONS),
        "supportedImageExtensions": sorted(SUPPORTED_IMAGE_EXTENSIONS),
    }
