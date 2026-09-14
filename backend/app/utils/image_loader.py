from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.DOTALL)


@dataclass(frozen=True)
class ImageItem:
    name: str
    data_url: str


def image_to_data_url(path: Path) -> str:
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"Unsupported image type: {path.name}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def parse_data_url(value: str) -> tuple[str, bytes]:
    match = _DATA_URL_RE.match(value or "")
    if not match:
        raise ValueError("Invalid data URL")
    return match.group("mime"), base64.b64decode(match.group("data"))

