from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin


class ComfyServerClient:
    def __init__(self, config: dict[str, Any]) -> None:
        self.base_url = str(config.get("comfy_base_url") or "http://127.0.0.1:8188").rstrip("/") + "/"
        self.timeout = int(config.get("request_timeout_sec") or 30)

    def _request(self, method: str, path: str, payload: Any | None = None) -> Any:
        url = urljoin(self.base_url, path.lstrip("/"))
        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ComfyUI HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接 ComfyUI：{exc.reason}") from exc

        if not raw:
            return {}
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}

    def get_system_stats(self) -> dict[str, Any]:
        value = self._request("GET", "/system_stats")
        return value if isinstance(value, dict) else {}

    def get_object_info(self) -> dict[str, Any]:
        value = self._request("GET", "/object_info")
        return value if isinstance(value, dict) else {}

    def get_queue(self) -> dict[str, Any]:
        value = self._request("GET", "/queue")
        return value if isinstance(value, dict) else {}

    def get_history(self, prompt_id: str) -> dict[str, Any]:
        value = self._request("GET", f"/history/{prompt_id}")
        return value if isinstance(value, dict) else {}

    def post_prompt(self, workflow: dict[str, Any], *, client_id: str, prompt_id: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": workflow,
            "client_id": client_id,
        }
        if prompt_id:
            payload["prompt_id"] = prompt_id
        value = self._request("POST", "/prompt", payload)
        if not isinstance(value, dict):
            raise RuntimeError("ComfyUI /prompt 返回了非 JSON 数据。")
        return value

    def post_interrupt(self) -> dict[str, Any]:
        value = self._request("POST", "/interrupt", {})
        return value if isinstance(value, dict) else {}

    def post_queue_delete(self, prompt_ids: list[str]) -> dict[str, Any]:
        value = self._request("POST", "/queue", {"delete": prompt_ids})
        return value if isinstance(value, dict) else {}

    def post_free(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        value = self._request("POST", "/free", payload or {})
        return value if isinstance(value, dict) else {}

    def health(self) -> dict[str, Any]:
        system_stats = self.get_system_stats()
        object_info = self.get_object_info()
        queue = self.get_queue()
        pending = 0
        running = 0
        if isinstance(queue.get("queue_pending"), list):
            pending = len(queue["queue_pending"])
        if isinstance(queue.get("queue_running"), list):
            running = len(queue["queue_running"])
        return {
            "online": True,
            "base_url": self.base_url.rstrip("/"),
            "object_info_count": len(object_info),
            "queue_pending": pending,
            "queue_running": running,
            "system_stats": system_stats,
        }

