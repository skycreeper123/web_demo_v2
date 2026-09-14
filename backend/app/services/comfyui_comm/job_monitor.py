from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse


@dataclass
class ComfyJobTracker:
    job_id: str
    prompt_id: str = ""
    state: str = "CREATED"
    current_node: str = ""
    queue_remaining: int = 0
    progress_value: int = 0
    progress_max: int = 0
    error_message: str = ""
    cancel_requested: bool = False
    execution_finished: bool = False
    execution_success: bool = False
    interrupted: bool = False
    updated_at: float = 0.0


class ComfyJobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_job_id: dict[str, ComfyJobTracker] = {}
        self._by_prompt_id: dict[str, str] = {}

    def register(self, job_id: str) -> ComfyJobTracker:
        tracker = ComfyJobTracker(job_id=job_id, updated_at=time.time())
        with self._lock:
            self._by_job_id[job_id] = tracker
        return tracker

    def attach_prompt(self, job_id: str, prompt_id: str) -> None:
        with self._lock:
            tracker = self._by_job_id[job_id]
            tracker.prompt_id = prompt_id
            tracker.updated_at = time.time()
            self._by_prompt_id[prompt_id] = job_id

    def get(self, job_id: str) -> ComfyJobTracker | None:
        with self._lock:
            tracker = self._by_job_id.get(job_id)
            if tracker is None:
                return None
            return ComfyJobTracker(**tracker.__dict__)

    def mark_cancel_requested(self, job_id: str) -> None:
        with self._lock:
            tracker = self._by_job_id.get(job_id)
            if tracker:
                tracker.cancel_requested = True
                tracker.updated_at = time.time()

    def update_queue_remaining(self, queue_remaining: int) -> None:
        with self._lock:
            for tracker in self._by_job_id.values():
                tracker.queue_remaining = queue_remaining
                tracker.updated_at = time.time()

    def handle_message(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "").strip()
        data = message.get("data") if isinstance(message.get("data"), dict) else {}

        if message_type == "status":
            status_payload = data.get("status") if isinstance(data.get("status"), dict) else {}
            exec_info = status_payload.get("exec_info") if isinstance(status_payload.get("exec_info"), dict) else {}
            queue_remaining = int(exec_info.get("queue_remaining") or 0)
            self.update_queue_remaining(queue_remaining)
            return

        prompt_id = str(data.get("prompt_id") or "").strip()
        if not prompt_id:
            return

        with self._lock:
            job_id = self._by_prompt_id.get(prompt_id)
            if not job_id:
                return
            tracker = self._by_job_id.get(job_id)
            if tracker is None:
                return

            if message_type == "execution_start":
                tracker.state = "RUNNING"
            elif message_type == "execution_cached":
                tracker.state = "RUNNING"
            elif message_type == "executing":
                node = data.get("node")
                if node is None:
                    tracker.execution_finished = True
                else:
                    tracker.state = "RUNNING"
                    tracker.current_node = str(node)
            elif message_type == "progress":
                tracker.state = "RUNNING"
                tracker.progress_value = int(data.get("value") or 0)
                tracker.progress_max = int(data.get("max") or 0)
            elif message_type == "execution_success":
                tracker.execution_finished = True
                tracker.execution_success = True
            elif message_type == "execution_error":
                tracker.execution_finished = True
                tracker.state = "FAILED"
                tracker.error_message = str(data.get("exception_message") or data.get("error") or "execution_error")
            elif message_type == "execution_interrupted":
                tracker.execution_finished = True
                tracker.interrupted = True
                tracker.state = "CANCELLED" if tracker.cancel_requested else "FAILED"
            tracker.updated_at = time.time()


class ComfyWebSocketManager:
    def __init__(self, registry: ComfyJobRegistry) -> None:
        self._registry = registry
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | ssl.SSLSocket | None = None
        self._base_url = ""
        self._client_id = ""
        self._connected = False
        self._stop_requested = False
        self._log = lambda _message: None

    def ensure_started(self, config: dict[str, Any], log: callable | None = None) -> str:
        with self._lock:
            base_url = str(config.get("comfy_base_url") or "http://127.0.0.1:8188").rstrip("/")
            if not self._client_id:
                self._client_id = str(uuid.uuid4())
            self._base_url = base_url
            if log is not None:
                self._log = log
            if self._thread is None or not self._thread.is_alive():
                self._stop_requested = False
                self._thread = threading.Thread(target=self._run_forever, daemon=True)
                self._thread.start()
            return self._client_id

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def _run_forever(self) -> None:
        while not self._stop_requested:
            try:
                sock = self._connect()
                with self._lock:
                    self._socket = sock
                    self._connected = True
                self._log("ComfyUI WebSocket connected.")
                self._read_loop(sock)
            except Exception as exc:
                self._log(f"ComfyUI WebSocket disconnected: {exc}")
            finally:
                with self._lock:
                    self._connected = False
                    try:
                        if self._socket:
                            self._socket.close()
                    except OSError:
                        pass
                    self._socket = None
            time.sleep(2.0)

    def _connect(self) -> socket.socket | ssl.SSLSocket:
        parsed = urlparse(self._base_url)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if scheme == "https" else 80)
        ws_scheme = "wss" if scheme == "https" else "ws"
        path_root = parsed.path.rstrip("/")
        ws_path = f"{path_root}/ws?clientId={quote(self._client_id)}" if path_root else f"/ws?clientId={quote(self._client_id)}"
        sock = socket.create_connection((host, port), timeout=10)
        if ws_scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {ws_path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = self._recv_http_headers(sock)
        if "101" not in response.splitlines()[0]:
            raise RuntimeError(f"WebSocket handshake failed: {response.splitlines()[0]}")
        accept_expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if accept_expected.lower() not in response.lower():
            raise RuntimeError("WebSocket handshake returned an unexpected Sec-WebSocket-Accept value.")
        return sock

    @staticmethod
    def _recv_http_headers(sock: socket.socket | ssl.SSLSocket) -> str:
        chunks = bytearray()
        while b"\r\n\r\n" not in chunks:
            data = sock.recv(4096)
            if not data:
                break
            chunks.extend(data)
        return bytes(chunks).decode("utf-8", errors="replace")

    def _read_loop(self, sock: socket.socket | ssl.SSLSocket) -> None:
        while not self._stop_requested:
            opcode, payload = self._read_frame(sock)
            if opcode == 0x1:
                try:
                    message = json.loads(payload.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict):
                    self._registry.handle_message(message)
            elif opcode == 0x2:
                continue
            elif opcode == 0x8:
                return
            elif opcode == 0x9:
                self._send_frame(sock, 0xA, payload)

    @staticmethod
    def _read_exact(sock: socket.socket | ssl.SSLSocket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            data = sock.recv(size - len(chunks))
            if not data:
                raise RuntimeError("WebSocket connection closed.")
            chunks.extend(data)
        return bytes(chunks)

    def _read_frame(self, sock: socket.socket | ssl.SSLSocket) -> tuple[int, bytes]:
        head = self._read_exact(sock, 2)
        opcode = head[0] & 0x0F
        masked = (head[1] & 0x80) != 0
        payload_length = head[1] & 0x7F
        if payload_length == 126:
            payload_length = int.from_bytes(self._read_exact(sock, 2), "big")
        elif payload_length == 127:
            payload_length = int.from_bytes(self._read_exact(sock, 8), "big")
        masking_key = self._read_exact(sock, 4) if masked else b""
        payload = self._read_exact(sock, payload_length) if payload_length else b""
        if masked and masking_key:
            payload = bytes(byte ^ masking_key[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _send_frame(self, sock: socket.socket | ssl.SSLSocket, opcode: int, payload: bytes = b"") -> None:
        with self._write_lock:
            header = bytearray()
            header.append(0x80 | (opcode & 0x0F))
            payload_length = len(payload)
            mask_bit = 0x80
            if payload_length < 126:
                header.append(mask_bit | payload_length)
            elif payload_length < (1 << 16):
                header.append(mask_bit | 126)
                header.extend(payload_length.to_bytes(2, "big"))
            else:
                header.append(mask_bit | 127)
                header.extend(payload_length.to_bytes(8, "big"))
            masking_key = os.urandom(4)
            masked_payload = bytes(byte ^ masking_key[index % 4] for index, byte in enumerate(payload))
            sock.sendall(bytes(header) + masking_key + masked_payload)

