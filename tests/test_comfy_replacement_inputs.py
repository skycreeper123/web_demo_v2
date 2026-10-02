"""Local regression cases for media roles and final-output selection (no Comfy server)."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services.comfyui_comm import _build_row_payload
from web_demo.backend.app.services.comfyui_comm.input_stager import stage_input_files
from web_demo.backend.app.services.comfyui_comm.result_collector import collect_result
from web_demo.backend.app.services.comfyui_comm.workflow_binder import bind_workflow, resolve_template_payload


class ReplacementInputTests(unittest.TestCase):
    def template(self, name):
        return resolve_template_payload(
            {"templateKey": name}, {"workflow_manifest_dir": str(ROOT / "workflow")},
        )

    def test_distinct_first_last_frames_survive_csv_staging_and_binding(self):
        template = self.template("wan2.2_14B_KJ版本_全功能.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.png"
            last = root / "last.png"
            first.write_bytes(b"first-frame")
            last.write_bytes(b"last-frame")
            payload = _build_row_payload(
                parent_job_id="frames", row_index=1,
                row={"start_image_path": str(first), "end_image_path": str(last), "positive_prompt": "walk"},
                payload={"formInputs": {"start_image_ref": "unused.png"}, "outputNodeId": "145"},
                template_payload=template,
            )
            staged = stage_input_files("frames", payload, {"comfy_input_dir": str(root / "input")})
            bound = bind_workflow(payload=payload, staged_inputs=staged, template_payload=template)
            self.assertEqual(bound["158"]["inputs"]["image"], "jobs/frames/start.png")
            self.assertEqual(bound["224"]["inputs"]["image"], "jobs/frames/end.png")
            self.assertEqual((root / "input/jobs/frames/start.png").read_bytes(), b"first-frame")
            self.assertEqual((root / "input/jobs/frames/end.png").read_bytes(), b"last-frame")
            self.assertEqual(payload["outputNodeId"], "145")

    def test_missing_last_frame_does_not_reuse_first_frame(self):
        template = self.template("wan2.2_14B_KJ版本_全功能.json")
        with self.assertRaisesRegex(RuntimeError, "end_image_ref"):
            bind_workflow(payload={"positivePrompt": "walk"},
                          staged_inputs={"start_image_ref": "first.png", "image_ref": "legacy.png"},
                          template_payload=template)

    def test_qwen_keeps_negative_conditioning_separate(self):
        template = self.template("qwen2511图片编辑V1.json")
        bound = bind_workflow(
            payload={"positivePrompt": "new scene", "negativePrompt": "blur"},
            staged_inputs={"image_ref": "reference.png"}, template_payload=template,
        )
        self.assertEqual(bound["110"]["inputs"]["prompt"], "blur")
        self.assertEqual(bound["205"]["inputs"]["prompt"], "new scene")
        self.assertEqual(bound["148"]["inputs"]["value"], "new scene")

    def test_invalid_output_node_is_rejected_before_submission(self):
        template = self.template("qwen2511图片编辑V1.json")
        with self.assertRaisesRegex(RuntimeError, "输出节点"):
            bind_workflow(payload={"outputNodeId": "missing"}, staged_inputs={}, template_payload=template)


class SelectedOutputTests(unittest.TestCase):
    def history(self, outputs):
        return {"prompt": {"status": {"completed": True, "status_str": "success"}, "outputs": outputs}}

    def test_pure_result_is_selected_even_when_comparison_is_larger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pure.mp4").write_bytes(b"pure")
            (root / "compare.mp4").write_bytes(b"comparison" * 20)
            result = collect_result(
                history_payload=self.history({
                    "1380": {"gifs": [{"filename": "compare.mp4"}]},
                    "1400": {"gifs": [{"filename": "pure.mp4"}]},
                }), prompt_id="prompt", output_prefix="", output_node_id="1400",
                config={"comfy_output_dir": str(root)},
            )
            self.assertEqual(Path(result["output_path"]).name, "pure.mp4")
            self.assertEqual(len(result["items"]), 1)

    def test_missing_selected_output_never_falls_back_to_prefix_or_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compare.mp4").write_bytes(b"comparison")
            for selected_output in (None, {}, {"gifs": [{"filename": "missing.mp4"}]}):
                outputs = {"1380": {"gifs": [{"filename": "compare.mp4"}]}}
                if selected_output is not None:
                    outputs["1400"] = selected_output
                with self.subTest(selected_output=selected_output), self.assertRaisesRegex(RuntimeError, "1400"):
                    collect_result(history_payload=self.history(outputs), prompt_id="prompt",
                                   output_prefix="compare", output_node_id="1400",
                                   config={"comfy_output_dir": str(root)})


if __name__ == "__main__":
    unittest.main()
