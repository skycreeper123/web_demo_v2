"""Offline checks for reusing the saved Prompt modules inside video recipes."""

import base64
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services import (
    image_edit_prompt_generator, prompt_generator, video_flow_service as flows,
    video_prompt_generator,
)


ROUTES = (
    ("spatial_prompt", "video", video_prompt_generator, ["source_video", "reference_image"]),
    ("first_prompt", "image_edit", image_edit_prompt_generator, ["original_first_frame", "boundary_frame"]),
    ("motion_prompt", "image", prompt_generator, ["start_image", "boundary_frame"]),
)


class VideoFlowPromptConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="flow_prompt_config_mock_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.calls = 0
        self.paths = {}
        for key in ("source_video", "reference_image", "original_first_frame", "boundary_frame", "start_image"):
            path = self.root / (key + (".mp4" if key == "source_video" else ".png"))
            path.write_bytes(f"offline placeholder: {key}".encode())
            self.paths[key] = path
        self.configs = {
            kind: {"system_prompt": f"  Saved {kind} system\nPreserve this exact formatting.\n",
                   "user_text": f"Saved {kind} user instructions.\n"}
            for _, kind, _, _ in ROUTES
        }
        self.patch("FLOW_ROOT", self.root / "flows")
        self.api_config = self.patch("load_api_config", return_value={
            "use_mock": False, "api_key": "offline-placeholder", "base_url": "https://unused.invalid/v1",
            "model": "offline-model",
        })
        self.prompt_config = self.patch("load_prompt_config", create=True,
                                        side_effect=lambda kind: dict(self.configs[kind]))
        self.client_factory = self.patch("OpenAICompatibleClient")
        self.client = self.client_factory.return_value
        self.respond({"positive_prompt": "Generated positive", "negative_prompt": "Generated negative"})
        # These guards fail immediately if a future change escapes the fake client.
        network_guard = patch("urllib.request.urlopen", side_effect=AssertionError("No network in these tests"))
        network_guard.start()
        self.addCleanup(network_guard.stop)
        self.patch("probe_video", side_effect=AssertionError("No media decoding in these tests"))
        self.patch("run_comfy_job", side_effect=AssertionError("No generation jobs in these tests"))

    def patch(self, name, *args, **kwargs):
        patcher = patch.object(flows, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def respond(self, payload, *, fenced=False):
        text = json.dumps(payload, ensure_ascii=False)
        self.client.chat_with_media.return_value = SimpleNamespace(text=f"```json\n{text}\n```" if fenced else text)

    def create(self, prompt_source="ai"):
        flow = flows.create_flow({
            "mode": "mixed", "temporalMode": "prefix", "cutSeconds": 4.125,
            "videoPath": str(self.paths["source_video"]),
            "referenceImagePath": str(self.paths["reference_image"]),
            "promptSource": prompt_source, "editInstruction": "FLOW_TASK_SENTINEL",
        })
        for key, path in self.paths.items():
            flow["artifacts"][key] = flows._artifact(key, path, flow["id"])
        flow["media"] = {"replacement_duration": 4.125}
        return flow

    def run_prompt(self, flow, step_id):
        step = next(step for step in flow["steps"] if step["id"] == step_id)
        self.calls += 1
        directory = self.root / f"prompt_run_{self.calls}"
        directory.mkdir()
        outputs = flows._run_prompt(flow, step, directory, lambda _: None)
        with (directory / "prompts.csv").open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        return step, outputs, row

    def test_three_routes_preserve_saved_templates_and_media_order(self):
        flow = self.create()
        for step_id, kind, _generator, expected_keys in ROUTES:
            with self.subTest(step=step_id):
                self.prompt_config.reset_mock()
                self.api_config.reset_mock()
                step, _, _ = self.run_prompt(flow, step_id)
                self.assertEqual(step["settings"]["apiKind"], kind)
                self.prompt_config.assert_called_once_with(kind)
                self.api_config.assert_called_once_with(kind)
                system, user_text, media_items = self.client.chat_with_media.call_args.args
                self.assertEqual(system, self.configs[kind]["system_prompt"])
                self.assertTrue(user_text.startswith(self.configs[kind]["user_text"]))
                self.assertIn("FLOW_TASK_SENTINEL", user_text)
                self.assertIn(step["settings"]["instruction"], user_text)
                self.assertEqual([item["kind"] for item in media_items],
                                 ["video" if key == "source_video" else "image" for key in expected_keys])
                self.assertEqual([base64.b64decode(item["url"].split(",", 1)[1]) for item in media_items],
                                 [self.paths[key].read_bytes() for key in expected_keys])

    def test_motion_context_and_export_preserve_start_end_images_and_duration(self):
        flow = self.create()
        _, _, row = self.run_prompt(flow, "motion_prompt")
        _, user_text, media_items = self.client.chat_with_media.call_args.args
        self.assertIn("4.125", user_text)
        self.assertIn("首图", user_text)
        self.assertIn("尾图", user_text)
        self.assertEqual(len(media_items), 2)
        self.assertEqual(row["start_image_path"], str(self.paths["start_image"]))
        self.assertEqual(row["end_image_path"], str(self.paths["boundary_frame"]))

    def test_spatial_context_labels_video_and_reference_without_recasting_video_as_image(self):
        flow = self.create()
        _, _, row = self.run_prompt(flow, "spatial_prompt")
        _, user_text, media_items = self.client.chat_with_media.call_args.args
        self.assertIn("原视频", user_text)
        self.assertIn("参考图", user_text)
        self.assertEqual([item["kind"] for item in media_items], ["video", "image"])
        self.assertTrue(media_items[0]["url"].startswith("data:video/"))
        self.assertEqual(row["video_path"], str(self.paths["source_video"]))
        self.assertEqual(row["image_path"], str(self.paths["reference_image"]))

    def test_each_ai_rerun_reads_latest_saved_configuration(self):
        flow = self.create()
        self.run_prompt(flow, "motion_prompt")
        self.configs["image"] = {"system_prompt": "NEW saved system\n", "user_text": "NEW saved user\n"}
        self.run_prompt(flow, "motion_prompt")
        self.assertEqual(self.prompt_config.call_count, 2)
        self.assertEqual(self.client.chat_with_media.call_count, 2)
        system, user_text, _ = self.client.chat_with_media.call_args.args
        self.assertEqual(system, "NEW saved system\n")
        self.assertTrue(user_text.startswith("NEW saved user\n"))

    def test_standard_generator_json_uses_module_specific_normalization(self):
        payload = {"en_prompt": " English chosen ", "zh_prompt": "不应选用这个中文候选",
                   "avoid": ["Flicker, blur", "flicker"], "quality_check": ["QUALITY_CHECK_MUST_STAY_OUT"]}
        self.respond(payload, fenced=True)
        flow = self.create()
        for step_id, _kind, generator, _keys in ROUTES:
            with self.subTest(step=step_id):
                step, _, row = self.run_prompt(flow, step_id)
                expected_negative = generator._derive_negative_prompt(payload)
                self.assertEqual(step["settings"]["prompt"], "English chosen")
                self.assertEqual(step["settings"]["negativePrompt"], expected_negative)
                self.assertEqual(row["positive_prompt"], "English chosen")
                self.assertEqual(row["negative_prompt"], expected_negative)
                self.assertNotIn("QUALITY_CHECK_MUST_STAY_OUT", row["negative_prompt"])

    def test_explicit_positive_and_negative_take_precedence(self):
        self.respond({"positive_prompt": " Explicit positive ", "negative_prompt": " Explicit negative ",
                      "en_prompt": "Ignored English", "zh_prompt": "忽略中文", "avoid": ["Ignored avoid"]})
        flow = self.create()
        for step_id, _kind, _generator, _keys in ROUTES:
            with self.subTest(step=step_id):
                step, _, row = self.run_prompt(flow, step_id)
                self.assertEqual(step["settings"]["prompt"], "Explicit positive")
                self.assertEqual(step["settings"]["negativePrompt"], "Explicit negative")
                self.assertEqual(row["positive_prompt"], "Explicit positive")
                self.assertEqual(row["negative_prompt"], "Explicit negative")

    def test_chinese_prompt_is_used_when_english_is_missing(self):
        self.respond({"zh_prompt": "保留主体并平滑过渡", "avoid": ["flicker"]})
        flow = self.create()
        for step_id, _kind, _generator, _keys in ROUTES:
            with self.subTest(step=step_id):
                step, _, _ = self.run_prompt(flow, step_id)
                self.assertEqual(step["settings"]["prompt"], "保留主体并平滑过渡")

    def test_request_artifact_records_actual_prompt_and_roles_without_api_credentials(self):
        flow = self.create()
        _, outputs, _ = self.run_prompt(flow, "spatial_prompt")
        request_output = next(item for item in outputs if item["key"] == "spatial_prompt_request")
        saved_text = Path(request_output["path"]).read_text(encoding="utf-8")
        saved = json.loads(saved_text)
        system, user_text, _ = self.client.chat_with_media.call_args.args
        self.assertEqual(saved["system_prompt"], system)
        self.assertEqual(saved["user_text"], user_text)
        self.assertEqual(saved["module_kind"], "video")
        self.assertTrue(saved["config_path"])
        self.assertEqual([item["kind"] for item in saved["media"]], ["video", "image"])
        self.assertEqual([item["name"] for item in saved["media"]],
                         [self.paths["source_video"].name, self.paths["reference_image"].name])
        self.assertIn("原视频", saved["media"][0]["role"])
        self.assertIn("参考图", saved["media"][1]["role"])
        self.assertNotIn("offline-placeholder", saved_text)
        self.assertNotIn("unused.invalid", saved_text)
        self.assertNotIn("api_key", saved)
        self.assertNotIn("base_url", saved)

    def test_manual_and_explicitly_edited_prompts_bypass_all_ai_configuration(self):
        for source in ("manual", "ai"):
            flow = self.create(prompt_source=source)
            for step_id, _kind, _generator, _keys in ROUTES:
                with self.subTest(source=source, step=step_id):
                    step = next(step for step in flow["steps"] if step["id"] == step_id)
                    step["settings"].update(prompt="User supplied positive", negativePrompt="User supplied negative",
                                            promptEdited=True)
                    _, outputs, row = self.run_prompt(flow, step_id)
                    self.assertEqual(row["positive_prompt"], "User supplied positive")
                    self.assertEqual(row["negative_prompt"], "User supplied negative")
                    self.assertEqual(len(outputs), 2)
                    self.assertTrue(all(item["name"] in {"prompt.txt", "prompts.csv"} for item in outputs))
        self.prompt_config.assert_not_called()
        self.api_config.assert_not_called()
        self.client_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
