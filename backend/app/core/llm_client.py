from __future__ import annotations

import json
import http.client
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from web_demo.backend.app.core.config import normalize_base_url


@dataclass
class LLMResponse:
    text: str
    raw: dict[str, Any]


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 120,
        retries: int = 2,
        retry_backoff: float = 1.0,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # A transient disconnect while uploading/reading a multimodal request is
        # common with proxies and some OpenSSL/server combinations.  Keep the
        # retry policy local to the HTTP adapter so all prompt modules benefit.
        try:
            self.retries = max(0, int(retries))
        except (TypeError, ValueError):
            self.retries = 2
        try:
            self.retry_backoff = max(0.0, float(retry_backoff))
        except (TypeError, ValueError):
            self.retry_backoff = 1.0

    def chat_with_image(self, system_prompt: str, user_text: str, image_data_url: str) -> LLMResponse:
        return self.chat_with_media(
            system_prompt,
            user_text,
            [{"kind": "image", "url": image_data_url}],
        )

    def chat_with_media_urls(self, system_prompt: str, user_text: str, media_urls: list[str]) -> LLMResponse:
        return self.chat_with_media(
            system_prompt,
            user_text,
            [{"kind": "image", "url": media_url} for media_url in media_urls],
        )

    def chat_with_media(self, system_prompt: str, user_text: str, media_items: list[dict[str, str]]) -> LLMResponse:
        content: list[dict[str, Any]] = [{"type": "text", "text": self._build_prompt_text(system_prompt, user_text)}]
        for item in media_items:
            media_kind = str(item.get("kind") or "image").strip().lower()
            media_url = str(item.get("url") or "").strip()
            self._validate_media_url(media_url, media_kind)
            if media_kind == "video":
                content.append({"type": "video_url", "video_url": {"url": media_url}})
            else:
                content.append({"type": "image_url", "image_url": {"url": media_url}})

        url = self.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": content},
            ],
            "stream": False,
            "temperature": 0.3,
        }
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # Do not reuse a half-closed keep-alive connection after a proxy or
            # upstream has sent an EOF.  This is especially helpful on Linux.
            "Connection": "close",
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        raw_text = ""
        attempts = self.retries + 1
        for attempt in range(attempts):
            try:
                # Build a fresh Request for every attempt.  urllib may otherwise
                # retain request state after a failed TLS handshake/upload.
                if attempt:
                    request = urllib.request.Request(
                        url,
                        data=json.dumps(body).encode("utf-8"),
                        headers=headers,
                        method="POST",
                    )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw_text = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
            except (
                urllib.error.URLError,
                ssl.SSLError,
                socket.timeout,
                TimeoutError,
                ConnectionError,
                http.client.RemoteDisconnected,
                http.client.IncompleteRead,
            ) as exc:
                if attempt >= attempts - 1:
                    raise RuntimeError(f"Network error: {self._network_error_detail(exc)}") from exc
                # Exponential backoff, capped to avoid making a batch appear
                # hung when the upstream is unavailable.
                delay = min(self.retry_backoff * (2**attempt), 8.0)
                if delay:
                    time.sleep(delay)

        raw = json.loads(raw_text)
        text = self._extract_text(raw)
        return LLMResponse(text=text, raw=raw)

    @classmethod
    def _network_error_detail(cls, exc: BaseException) -> str:
        reason = getattr(exc, "reason", None)
        if reason is not None and reason is not exc:
            return str(reason)
        return str(exc)

    @staticmethod
    def _build_prompt_text(system_prompt: str, user_text: str) -> str:
        system_text = system_prompt.strip()
        user_content = user_text.strip()
        if system_text and user_content:
            return f"{system_text}\n\n{user_content}"
        return system_text or user_content

    @staticmethod
    def _validate_media_url(media_url: str, media_kind: str = "image") -> None:
        text = str(media_url).strip()
        if text.startswith("data:") and ";base64," in text:
            return
        parsed = urlparse(text)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return
        if media_kind == "video":
            raise RuntimeError("Video input must be a publicly accessible http(s) URL or a base64 data URL.")
        raise RuntimeError("Image input must be a publicly accessible http(s) URL or a base64 data URL.")

    @staticmethod
    def _extract_text(raw: dict[str, Any]) -> str:
        choices = raw.get("choices") or []
        if not choices:
            return json.dumps(raw, ensure_ascii=False, indent=2)
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
            if parts:
                return "".join(parts)
        return json.dumps(raw, ensure_ascii=False, indent=2)
