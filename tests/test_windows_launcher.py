"""Windows EXE integration tests; use a disposable project and no browser windows."""
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000/"
SERVER = '''from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"prompt-tool-ready" if self.path == "/api/health" else b"fixture page")
    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        import threading
        threading.Thread(target=self.server.shutdown, daemon=True).start()
HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
'''


@unittest.skipUnless(sys.platform == "win32", "Windows launcher integration")
class WindowsLauncherTests(unittest.TestCase):
    def setUp(self):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8000)) == 0:
                self.skipTest("Port 8000 is in use; do not disturb an existing server")
        self.temp = tempfile.TemporaryDirectory(prefix="prompt 启动 test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe = self.root / "PromptToolLauncher.exe"
        shutil.copy2(ROOT / "PromptToolLauncher.exe", self.exe)
        (self.root / "backend/app").mkdir(parents=True)
        (self.root / "frontend").mkdir()
        (self.root / "frontend/index.html").write_text("test", encoding="utf-8")
        self.main = self.root / "backend/app/main.py"
        self.main.write_text(SERVER, encoding="utf-8")
        self.env = dict(os.environ)
        self.env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + self.env.get("PATH", "")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def run_launcher(self):
        return subprocess.run([self.exe, "--no-browser", "--no-pause"],
                              cwd=self.root.parent, env=self.env, capture_output=True,
                              text=True, encoding="utf-8", timeout=20)

    def test_missing_project_files(self):
        self.main.unlink()
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Missing backend/app/main.py", result.stdout)

    def test_startup_traceback_is_preserved_without_waiting_for_timeout(self):
        self.main.write_text("raise RuntimeError('启动失败 fixture crash')", encoding="utf-8")
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1)
        self.assertIn("Backend exited during startup", result.stdout)
        self.assertIn("RuntimeError: 启动失败 fixture crash", result.stdout)
        self.assertIn("RuntimeError: 启动失败 fixture crash",
                      (self.root / "logs/launcher.log").read_text(encoding="utf-8"))
        self.assertNotIn("within 40 seconds", result.stdout)

    def test_unrelated_server_is_not_treated_as_ready(self):
        class ForeignHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"some other application")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 8000), ForeignHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = self.run_launcher()
            self.assertEqual(result.returncode, 1)
            self.assertIn("Port 8000 is occupied", result.stdout)
            self.assertNotIn("Starting backend", result.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_start_and_reuse_server_from_path_with_spaces_and_unicode(self):
        self.check_start_and_reuse()

    def test_broken_venv_process_falls_back_to_system_python(self):
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework/v4.0.30319/csc.exe"
        broken = self.root / ".venv/Scripts/python.exe"
        broken.parent.mkdir(parents=True)
        source = self.root / "BrokenPython.cs"
        source.write_text('class BrokenPython { static int Main() { System.Console.Error.WriteLine("broken venv fixture"); return 23; } }')
        subprocess.run([compiler, "/nologo", "/target:exe", "/out:" + str(broken), source], check=True, capture_output=True)
        output = self.check_start_and_reuse()
        self.assertIn("Python check failed (exit code 23)", output)
        self.assertIn("Starting backend with: python", output)

    def check_start_and_reuse(self):
        proc = subprocess.Popen([self.exe, "--no-browser", "--no-pause"], cwd=self.root.parent,
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8")
        ready = False
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and proc.poll() is None:
                try:
                    with self.opener.open(URL + "api/health", timeout=0.5) as response:
                        ready = response.read() == b"prompt-tool-ready"
                    if ready:
                        break
                except OSError:
                    pass
                time.sleep(0.1)
            self.assertTrue(ready, "Launcher did not start fixture server")
            second = self.run_launcher()
            self.assertEqual(second.returncode, 0, second.stdout)
            self.assertIn("already running", second.stdout)
            self.assertIsNone(proc.poll(), "Second launcher stopped the original server")
        finally:
            try:
                if ready:
                    with self.opener.open(urllib.request.Request(URL + "stop", data=b""), timeout=2):
                        pass
                output, _ = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                # Kill only this fixture's process tree, never the user's server.
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                output, _ = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn("Ready: " + URL, output)
        return output


if __name__ == "__main__":
    unittest.main()
