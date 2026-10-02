"""Match server folders or browser metadata into distinct video recipe inputs."""
from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path, PurePosixPath
from typing import Any

from .video_matcher import build_video_matches


_GROUPS = ("videos", "references", "startImages", "endImages")
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_LABELS = {"videos": "视频", "references": "参考图", "startImages": "新首图", "endImages": "目标尾图"}
_FIELD_LABELS = {"videoPath": "视频", "referenceImagePath": "主参考图", "referenceAlt1Path": "补充参考图 1",
                 "referenceAlt2Path": "补充参考图 2", "startImagePath": "新首图", "endImagePath": "目标尾图"}


def _basename(value: Any) -> str:
    return PurePosixPath(str(value or "").replace("\\", "/")).name


def _collect(payload: dict[str, Any], mode: str) -> dict[str, list[dict[str, str]]]:
    source = payload.get("directories" if mode == "directories" else "files") or {}
    if not isinstance(source, dict):
        raise ValueError("素材目录或文件列表必须是对象。")
    groups: dict[str, list[dict[str, str]]] = {}
    seen: set[str] = set()
    for role in _GROUPS:
        allowed = _VIDEO_EXTS if role == "videos" else _IMAGE_EXTS
        records: list[dict[str, Any]] = []
        if mode == "directories":
            value = str(source.get(role) or "").strip()
            if value:
                directory = Path(value).expanduser()
                if not directory.is_dir():
                    raise ValueError(f"{_LABELS[role]}目录不存在或无法读取：{value}")
                directory = directory.resolve()
                try:
                    def fail_scan(exc: OSError) -> None:
                        raise exc
                    paths = [Path(root) / name for root, _, names in os.walk(directory, onerror=fail_scan)
                             for name in names if Path(name).suffix.lower() in allowed and (Path(root) / name).is_file()]
                    paths.sort(key=lambda path: path.relative_to(directory).as_posix().casefold())
                except OSError as exc:
                    raise ValueError(f"无法扫描{_LABELS[role]}目录：{value}；{exc}") from exc
                records = [{"id": f"{role}:{path.relative_to(directory).as_posix()}", "name": path.name,
                            "relativePath": path.relative_to(directory).as_posix(), "path": str(path.resolve())}
                           for path in paths]
        else:
            records = source.get(role) or []
            if not isinstance(records, list):
                raise ValueError(f"{_LABELS[role]}素材必须是数组。")
        assets = []
        for index, item in enumerate(records, 1):
            if not isinstance(item, dict):
                raise ValueError(f"{_LABELS[role]}第 {index} 项文件信息无效。")
            name = _basename(item.get("name") or item.get("relativePath") or item.get("path"))
            if not name or Path(name).suffix.lower() not in allowed:
                continue
            relative = str(item.get("relativePath") or name).replace("\\", "/")
            asset_id = str(item.get("id") or f"{role}:{index}:{relative}")
            if asset_id in seen:
                raise ValueError(f"素材 id 重复：{asset_id}；每个文件（包括不同角色的同名文件）必须有独立 id。")
            seen.add(asset_id)
            # Browser paths are metadata only. Server readability is checked
            # later, after the browser uploads selected files and creates rows.
            assets.append({"id": asset_id, "name": name, "relativePath": relative,
                           "path": str(item.get("path") or "")})
        groups[role] = assets
    if not groups["videos"]:
        raise ValueError("没有找到可用视频，请选择包含视频的目录或文件列表。")
    return groups


def _match_group(videos: list[dict[str, str]], images: list[dict[str, str]]) -> list[dict[str, Any]]:
    # Unique synthetic parent folders retain file identity for duplicate names.
    # Only the two extra formats supported by the flow need suffix aliases;
    # matching still uses the existing case-insensitive stem/_1/_2 convention.
    video_names = [f"video_{index}/{Path(item['name']).stem}.mp4" for index, item in enumerate(videos)]
    image_names = [f"image_{index}/{Path(item['name']).stem}.png" for index, item in enumerate(images)]
    lookup = dict(zip(image_names, images))
    results = build_video_matches(video_names, image_names)["matches"]
    for result in results:
        for key in ("referenceMain", "referenceAlt1", "referenceAlt2"):
            result[key] = lookup.get(result[key])
        result["conflicts"] = {slot: [lookup[name] for name in names]
                               for slot, names in result["conflicts"].items()}
    return results


def match_batch_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("defaults"), dict):
        raise ValueError("请提供流程类型等默认配置。")
    defaults = payload["defaults"]
    recipe = str(defaults.get("mode") or "spatial")
    if recipe not in {"spatial", "prefix", "suffix", "mixed"}:
        raise ValueError("请选择有效的流程类型。")
    direction = str(defaults.get("temporalMode") or "prefix") if recipe == "mixed" else recipe
    if recipe == "mixed" and direction not in {"prefix", "suffix"}:
        raise ValueError("请选择混合替换的时间方向。")
    mode = str(payload.get("inputMode") or "directories")
    if mode not in {"directories", "files"}:
        raise ValueError("素材输入模式必须是 directories 或 files。")
    groups = _collect(payload, mode)
    videos = groups["videos"]
    matches_by_role = {role: _match_group(videos, groups[role]) for role in _GROUPS if role != "videos"}
    spatial = recipe in {"spatial", "mixed"}
    required = ["videoPath"] + (["referenceImagePath"] if spatial else []) + (["endImagePath"] if direction == "suffix" else [])
    same_stem: dict[str, list[dict[str, str]]] = defaultdict(list)
    for video in videos:
        same_stem[Path(video["name"]).stem.casefold()].append(video)
    used_ids = {asset["id"] for items in groups.values() for asset in items}
    default_assets: dict[str, dict[str, str]] = {}
    previews = []
    for index, video in enumerate(videos):
        key = Path(video["name"]).stem
        assets = {"videoPath": video}
        issues = []

        def issue(field: str, code: str, message: str, candidates: list[dict[str, str]]) -> None:
            issues.append({"role": field, "code": code, "message": message, "candidates": candidates})

        def fallback(field: str) -> dict[str, str] | None:
            value = str(defaults.get(field) or "").strip()
            if not value:
                return None
            if field not in default_assets:
                asset_id = f"default:{field}"
                while asset_id in used_ids:
                    asset_id += ":shared"
                used_ids.add(asset_id)
                default_assets[field] = {"id": asset_id, "name": _basename(value), "relativePath": _basename(value), "path": value}
            return default_assets[field]

        def choose(field: str, sources: list[str], slot: str = "referenceMain") -> None:
            conflict_slot = {"referenceMain": "reference_main", "referenceAlt1": "reference_alt_1", "referenceAlt2": "reference_alt_2"}[slot]
            for source in sources:
                result = matches_by_role[source][index]
                conflicts = result["conflicts"].get(conflict_slot)
                if conflicts:
                    issue(field, "naming_conflict", f"{key} 的{_FIELD_LABELS[field]}匹配到多份同名素材，请保留唯一文件。", conflicts)
                    return
                if result[slot]:
                    assets[field] = result[slot]
                    return
            default_asset = fallback(field)
            if default_asset:
                assets[field] = default_asset
            elif field in required:
                issue(field, "missing_input", f"{key} 缺少同名的{_FIELD_LABELS[field]}素材。", [])

        duplicates = same_stem[key.casefold()]
        if len(duplicates) > 1:
            issue("videoPath", "naming_conflict", f"视频名称 {key} 重复，无法唯一配对，请调整名称。", duplicates)
        if spatial:
            choose("referenceImagePath", ["references"])
            choose("referenceAlt1Path", ["references"], "referenceAlt1")
            choose("referenceAlt2Path", ["references"], "referenceAlt2")
        if direction == "prefix":
            choose("startImagePath", ["startImages"] + (["references"] if recipe == "prefix" else []))
        elif direction == "suffix":
            choose("endImagePath", ["endImages"] + (["references"] if recipe == "suffix" else []))
        can_create = not issues
        needs_upload = any(not asset["path"] for asset in assets.values())
        row = {"name": key, **{field: asset["path"] for field, asset in assets.items()}}
        status = "naming_conflict" if any(item["code"] == "naming_conflict" for item in issues) else "missing_input" if issues else "matched"
        previews.append({"index": index + 1, "matchKey": key, "status": status, "canCreate": can_create,
                         "requiresUpload": needs_upload, "issues": issues, "assets": assets, "row": row})
    ready = [item for item in previews if item["canCreate"]]
    return {"inputMode": mode, "summary": {"total": len(previews), "ready": len(ready),
                                          "blocked": len(previews) - len(ready),
                                          "needsUpload": sum(item["requiresUpload"] for item in ready)},
            "requiredRoles": required, "matches": previews, "rows": [item["row"] for item in ready]}
