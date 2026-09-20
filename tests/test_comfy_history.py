import importlib.util
from pathlib import Path
import sys
import unittest


# The checkout directory can differ from the application's package name.
ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services.comfyui_comm.result_collector import summarize_history_state


class HistoryStateTests(unittest.TestCase):
    def summarize(self, status, outputs):
        return summarize_history_state({"prompt": {"status": status, "outputs": outputs}}, "prompt")

    def test_node_error_with_intermediate_output_preserves_cause(self):
        detail = {"node_id": "1112.0.0.22", "exception_message": "model load failed"}
        result = self.summarize(
            {"completed": False, "status_str": "error", "messages": [["execution_error", detail]]},
            {"237": {"frame_count": [192]}},
        )
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(result["message"], "model load failed")
        self.assertEqual(result["detail"]["node_id"], "1112.0.0.22")

    def test_error_event_overrides_success_status(self):
        result = self.summarize(
            {"completed": True, "status_str": "success", "messages": [["execution_error", {"exception_message": "failed"}]]},
            {"237": {}},
        )
        self.assertEqual(result["state"], "FAILED")

    def test_intermediate_outputs_do_not_finish_running_job(self):
        for status in ({}, {"completed": False, "status_str": "running"}):
            with self.subTest(status=status):
                self.assertEqual(self.summarize(status, {"237": {"frame_count": [192]}})["state"], "PENDING")

    def test_completed_video_is_ready_for_collection(self):
        result = self.summarize(
            {"completed": True, "status_str": "success"},
            {"save": {"videos": [{"filename": "result.mp4"}]}},
        )
        self.assertEqual(result["state"], "SUCCEEDED")

    def test_completed_without_outputs_reports_failure(self):
        result = self.summarize({"completed": True, "status_str": "success"}, {})
        self.assertEqual(result["state"], "FAILED")

    def test_failed_status_without_event_overrides_outputs(self):
        result = self.summarize({"completed": False, "status_str": "error"}, {"237": {}})
        self.assertEqual(result["state"], "FAILED")


if __name__ == "__main__":
    unittest.main()
