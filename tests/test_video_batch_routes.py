"""Exercise HTTP dispatch without starting the app, workers or database."""

import ast
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]


class VideoBatchRouteTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse((ROOT / "backend/app/main.py").read_text(encoding="utf-8-sig"))
        handler = next(node for node in source.body if isinstance(node, ast.ClassDef)
                       and any(isinstance(child, ast.FunctionDef) and child.name == "do_POST" for child in node.body))
        methods = [node for node in handler.body if isinstance(node, ast.FunctionDef)
                   and node.name in {"do_GET", "do_POST"}]
        self.batches = Mock()
        self.scan = Mock(return_value={"summary": {"total": 2, "ready": 2}, "rows": [{}, {}]})
        self.body = {"inputMode": "directories", "directories": {"videos": "/videos", "references": "/images"}}
        self.scope = {
            "urlparse": urlparse, "HTTPStatus": HTTPStatus,
            "video_batches": self.batches, "match_batch_inputs": self.scan,
            "json_response": lambda _handler, status, body: (status, body),
            "read_body_json": lambda _handler: self.body,
        }
        exec(compile(ast.Module(body=methods, type_ignores=[]), "isolated_batch_routes", "exec"), self.scope)
        self.handler = SimpleNamespace(path="", _serve_flow_file=lambda path: (HTTPStatus.OK, path))

    def request(self, method, path):
        self.handler.path = path
        return self.scope[f"do_{method}"](self.handler)

    def test_scan_is_read_only_and_does_not_create_a_batch(self):
        status, body = self.request("POST", "/api/video-batches/scan")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["summary"]["total"], 2)
        self.scan.assert_called_once_with(self.body)
        self.batches.create_batch.assert_not_called()

    def test_scan_validation_is_reported_without_dispatch(self):
        self.scan.side_effect = ValueError("视频目录不存在")
        status, body = self.request("POST", "/api/video-batches/scan")
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertEqual(body["error"], "视频目录不存在")
        self.batches.create_batch.assert_not_called()

    def test_invalid_body_is_rejected_before_scan(self):
        self.body = []
        self.assertEqual(self.request("POST", "/api/video-batches/scan")[0], HTTPStatus.BAD_REQUEST)
        self.scan.assert_not_called()

    def test_log_tail_is_returned_and_download_serves_registered_file(self):
        self.batches.read_logs.return_value = ["[time] first attempt", "[time] retry attempt"]
        self.batches.resolve_log.return_value = Path("batch.log")
        status, body = self.request("GET", "/api/video-batches/abcd/logs")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(len(body["logs"]), 2)
        self.batches.read_logs.assert_called_once_with("abcd")
        self.assertEqual(self.request("GET", "/api/video-batches/abcd/logs.txt"), (HTTPStatus.OK, Path("batch.log")))

    def test_missing_batch_logs_are_not_found(self):
        self.batches.read_logs.side_effect = FileNotFoundError("找不到此批次。")
        self.assertEqual(self.request("GET", "/api/video-batches/abcd/logs")[0], HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
