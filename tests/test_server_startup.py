"""Exercise cloud startup in an isolated project without touching saved jobs."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


class ServerStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / "backend/app", self.root / "backend/app",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "frontend", self.root / "frontend")
        self.command = [sys.executable, "-B", str(self.root / "backend/app/main.py")]

    def test_custom_port_serves_health_and_frontend(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with (self.root / "console.log").open("w+") as log:
            process = subprocess.Popen(self.command + ["--host", "127.0.0.1", "--port", str(port)],
                                       cwd=self.root, stdout=log, stderr=log,
                                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                url = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        with opener.open(url + "/api/health", timeout=1) as response:
                            self.assertEqual(response.read(), b"prompt-tool-ready")
                        break
                    except OSError:
                        if process.poll() is not None:
                            log.seek(0)
                            self.fail(log.read())
                        time.sleep(0.1)
                else:
                    self.fail("Server did not become ready")
                with opener.open(url, timeout=2) as response:
                    self.assertTrue(response.read().lower().startswith(b"<!doctype html>"))
            finally:
                process.terminate()
                process.wait(timeout=10)

    def test_invalid_port_is_rejected(self):
        result = subprocess.run(self.command + ["--port", "65536"], cwd=self.root,
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"--port must be between 1 and 65535", result.stderr)


if __name__ == "__main__":
    unittest.main()
