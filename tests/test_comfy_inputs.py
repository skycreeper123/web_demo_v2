import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services.comfyui_comm.workflow_binder import (
    resolve_template_payload, bind_workflow, describe_workflow_inputs,
)
from web_demo.backend.app.services.comfyui_comm import _build_row_payload
from web_demo.backend.app.services.comfyui_comm.input_stager import stage_input_files
from web_demo.backend.app.services import comfyui_comm


class WorkflowInputTests(unittest.TestCase):
    def setUp(self):
        self.config = {"workflow_manifest_dir": str(ROOT / "workflow")}
        self.key = "Wan视频编辑-测试版V6.1-云端.json"
        self.template = resolve_template_payload({"templateKey": self.key}, self.config)

    def row(self, payload, row=None):
        return _build_row_payload(parent_job_id="test", row_index=1, row=row or {},
                                  payload=payload, template_payload=self.template)

    def test_wan_inputs_and_connections(self):
        fields = {f["key"]: f for f in self.template["input_fields"]}
        self.assertTrue(fields["image_ref"]["required"])
        self.assertTrue(fields["video_ref"]["required"])
        self.assertEqual(fields["params.node_27.steps"]["default"], "5")
        self.assertEqual(fields["params.node_222.value"]["default"], "832")
        self.assertEqual(fields["params.node_27.cfg"]["type"], "float")
        self.assertNotIn("params.node_27.model", fields)
        self.assertFalse(any("hiddenJson" in k for k in fields))

    def test_form_values_reach_wan_without_mutating_template(self):
        row = self.row({"formInputs": {"positive_prompt": "walk", "params.node_27.steps": "9", "params.node_222.value": "640", "seed": "1844674407370955161"}})
        bound = bind_workflow(payload=row, staged_inputs={"image_ref": "input.png", "video_ref": "video.mp4"}, template_payload=self.template)
        self.assertEqual(bound["27"]["inputs"]["steps"], 9)
        self.assertEqual(bound["222"]["inputs"]["value"], 640)
        self.assertEqual(bound["216"]["inputs"]["seed"], 1844674407370955161)
        self.assertEqual(bound["27"]["inputs"]["seed"], ["216", 0])
        self.assertEqual(bound["252"]["inputs"]["negative_prompt"], self.template["workflow"]["252"]["inputs"]["negative_prompt"])
        self.assertEqual(self.template["workflow"]["27"]["inputs"]["steps"], 5)

    def test_csv_overrides_form_and_defaults(self):
        row = self.row({"defaultParams": {"a": 1, "b": 2}, "formInputs": {"params.a": 3, "positive_prompt": "form", "image_ref": "fallback.png"}},
                       {"params_json": '{"a":4}', "positive_prompt": "csv"})
        self.assertEqual(row["params"], {"a": 4, "b": 2})
        self.assertEqual(row["positivePrompt"], "csv")
        self.assertEqual(row["imagePath"], "fallback.png")

    def test_bindings_only_override_selected_template(self):
        template = resolve_template_payload({"templateKey": self.key, "bindingsJsonText": json.dumps({"params.steps": [{"node": "27", "input": "steps", "type": "int"}]})}, self.config)
        bound = bind_workflow(payload={"params": {"steps": 7}}, staged_inputs={}, template_payload=template)
        self.assertEqual(bound["27"]["inputs"]["steps"], 7)
        self.assertNotIn("params.node_27.steps", template["bindings"])

    def test_invalid_and_duplicate_bindings_rejected(self):
        for bindings in ({"seed": [{"node": "missing", "input": "seed"}]},
                         {"seed": [{"node": "216", "input": "seed"}], "params.other": [{"node": "216", "input": "seed"}]}):
            with self.assertRaises(RuntimeError):
                resolve_template_payload({"templateKey": self.key, "bindingsJsonText": json.dumps(bindings)}, self.config)

    def test_missing_required_media_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "image_ref"):
            bind_workflow(payload={"positivePrompt": "walk"}, staged_inputs={"video_ref": "video.mp4"}, template_payload=self.template)

    def test_direct_media_is_staged_and_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.png").write_bytes(b"image")
            (root / "video.mp4").write_bytes(b"video")
            row = self.row({"formInputs": {"image_ref": str(root / "image.png"), "video_ref": str(root / "video.mp4"), "positive_prompt": "walk"}})
            staged = stage_input_files("test", row, {"comfy_input_dir": str(root / "input"), "path_style": "windows"})
            bound = bind_workflow(payload=row, staged_inputs=staged, template_payload=self.template)
            self.assertEqual(bound["234"]["inputs"]["image"], "jobs/test/input.png")
            self.assertEqual(bound["237"]["inputs"]["video"], "jobs/test/source.mp4")

    def test_direct_run_submits_without_reading_saved_csv(self):
        config = {**self.config, "ws_enabled": False, "csv_import": {"csv_path": "missing.csv"}}
        client = MagicMock()
        client.post_prompt.return_value = {"prompt_id": "submitted"}
        client.get_queue.return_value = {}
        with patch.object(comfyui_comm, "load_comfy_config", return_value=config), \
             patch.object(comfyui_comm, "comfy_health", return_value={"online": True}), \
             patch.object(comfyui_comm, "ComfyServerClient", return_value=client), \
             patch.object(comfyui_comm, "_load_csv_rows", side_effect=AssertionError("Direct mode must not read CSV")), \
             patch.object(comfyui_comm, "stage_input_files", return_value={"image_ref": "input.png", "video_ref": "video.mp4"}), \
             patch.object(comfyui_comm, "summarize_history_state", return_value={"state": "SUCCEEDED"}), \
             patch.object(comfyui_comm, "collect_result", return_value={"output_dir": "output", "output_path": "output/result.mp4"}):
            result = comfyui_comm.run_comfy_job(job_id="direct-test", payload={
                "inputMode": "direct", "templateKey": self.key,
                "formInputs": {"positive_prompt": "walk", "params.node_27.cfg": 1.5}
            }, log=lambda text: None, progress=lambda a, b: None, update_job=lambda **kwargs: None)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["total"], 1)
        submitted = client.post_prompt.call_args.args[0]
        self.assertEqual(submitted["27"]["inputs"]["cfg"], 1.5)


if __name__ == "__main__":
    unittest.main()
