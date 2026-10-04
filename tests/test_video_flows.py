"""Recipe state and handoff checks; all media/model execution is replaced locally."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services import video_flow_service as flows


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root_patch = patch.object(flows, "FLOW_ROOT", self.root / "flows")
        self.root_patch.start()
        self.media = {}
        for key, name in (("videoPath", "source.mp4"), ("referenceImagePath", "ref.png"),
                          ("endImagePath", "end.png"), ("startImagePath", "start.png")):
            path = self.root / name
            path.write_bytes(key.encode())
            self.media[key] = str(path)

    def tearDown(self):
        flows._ACTIVE.clear()
        self.root_patch.stop()
        self.temporary.cleanup()

    def create(self, mode="spatial", **overrides):
        return flows.create_flow({**self.media, "startImagePath": "", "mode": mode, "cutSeconds": 4,
                                  "promptSource": "manual", **overrides})

    def execute(self, flow, step, *_args):
        path = self.root / f"{step['id']}-{step['attempts']}.txt"
        path.write_text("output", encoding="utf-8")
        return [flows._artifact(step["id"] + "_result", path, flow["id"])]

    def run_worker(self, flow, *, all_steps=True, execute=None, step="", duration=10, logs=None):
        flows.claim_run(flow["id"], "offline-job", step)
        with patch.object(flows, "probe_video", return_value={"duration": duration, "fps": 30}), \
             patch.object(flows, "_execute_step", side_effect=execute or self.execute):
            return flows.run_flow_steps(flow_id=flow["id"], job_id="offline-job", run_all=all_steps,
                                        log=logs.append if logs is not None else lambda _: None,
                                        progress=lambda *_: None, update_job=lambda **_: None)

    def test_percent_creation_validates_without_reading_video(self):
        with patch.object(flows, "probe_video", side_effect=AssertionError("Creation must not inspect media")):
            flow = self.create("prefix", cutMode="percent", replacePercent="25")
            self.assertIsNone(flow["inputs"]["cutSeconds"])
            self.assertEqual(flow["inputs"]["replacePercent"], 25)
            for value in (None, "", "bad", 0, -1, 100, 101, float("nan"), float("inf"), True):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "替换比例"):
                    self.create("prefix", cutMode="percent", replacePercent=value)
            with self.assertRaisesRegex(ValueError, "按比例或按秒数"):
                self.create("prefix", cutMode="unknown")

    def test_percent_cut_uses_original_duration_and_replacement_direction_before_first_step(self):
        for mode, direction in (("prefix", "prefix"), ("suffix", "suffix"),
                                ("mixed", "prefix"), ("mixed", "suffix")):
            for duration in (10, 24):
                with self.subTest(mode=mode, direction=direction, duration=duration):
                    flow = self.create(mode, temporalMode=direction, cutMode="percent", replacePercent=25)
                    expected = duration * (0.25 if direction == "prefix" else 0.75)
                    calls, logs = [], []

                    def observe(current, step, *args):
                        self.assertEqual(current["inputs"]["cutSeconds"], expected)
                        self.assertEqual(flows.get_flow(current["id"])["inputs"]["cutSeconds"], expected)
                        calls.append(step["id"])
                        return self.execute(current, step, *args)

                    result = self.run_worker(flow, execute=observe, duration=duration, logs=logs)
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual(calls[0], "spatial_prompt" if mode == "mixed" else "prepare")
                    self.assertIn("25%", logs[0])
                    self.assertIn(f"切点 {expected:g} 秒", logs[0])

    def test_percent_under_one_frame_fails_before_any_prompt_or_media(self):
        for mode in ("prefix", "suffix", "mixed"):
            for percent in (0.1, 99.9):
                with self.subTest(mode=mode, percent=percent):
                    flow = self.create(mode, cutMode="percent", replacePercent=percent)
                    calls = []
                    result = self.run_worker(flow, execute=lambda *_: calls.append("called"))
                    self.assertEqual(result["status"], "failed")
                    self.assertIn("至少保留一帧", result["error"])
                    self.assertEqual(calls, [])
                    self.assertIsNone(flows.get_flow(flow["id"])["inputs"]["cutSeconds"])

    def test_legacy_seconds_record_and_spatial_timing_remain_compatible(self):
        flow = self.create("suffix")
        with flows._LOCK:
            legacy = flows._load(flow["id"])
            legacy["inputs"].pop("cutMode")
            legacy["inputs"].pop("replacePercent")
            flows._save(legacy)
        self.assertEqual(self.run_worker(flow)["status"], "completed")
        self.assertEqual(flows.get_flow(flow["id"])["inputs"]["cutSeconds"], 4)
        spatial = self.create(cutMode="unused", replacePercent="invalid", cutSeconds="invalid")
        self.assertEqual(spatial["inputs"]["cutSeconds"], 0)
        self.assertIsNone(spatial["inputs"]["replacePercent"])

    def test_resolved_percent_cut_is_persisted_and_reused_on_failed_step_retry(self):
        flow = self.create("prefix", cutMode="percent", replacePercent=50)

        def fail_motion(current, step, *args):
            if step["id"] == "motion_render":
                raise RuntimeError("offline motion failure")
            return self.execute(current, step, *args)

        self.assertEqual(self.run_worker(flow, execute=fail_motion)["status"], "failed")
        failed = flows.get_flow(flow["id"])
        self.assertEqual(failed["inputs"]["cutSeconds"], 5)
        self.assertEqual(failed["inputs"]["replacePercent"], 50)
        calls = []

        def retry(current, step, *args):
            self.assertEqual(current["inputs"]["cutSeconds"], 5)
            calls.append(step["id"])
            return self.execute(current, step, *args)

        # A later metadata read must not shift the cut used by retained artifacts.
        self.assertEqual(self.run_worker(failed, execute=retry, duration=10.001)["status"], "completed")
        self.assertEqual(calls, ["motion_render", "assemble"])
        self.assertEqual(flows.get_flow(flow["id"])["inputs"]["cutSeconds"], 5)

    def test_recipe_orders_and_optional_uploaded_start(self):
        prefix = self.create("prefix")
        self.assertEqual([s["id"] for s in prefix["steps"]],
                         ["prepare", "first_prompt", "first_render", "motion_prompt", "motion_render", "assemble"])
        self.assertEqual(prefix["steps"][3]["settings"]["media"], ["start_image", "boundary_frame"])
        suffix = self.create("suffix")
        self.assertEqual(suffix["steps"][1]["settings"]["media"], ["boundary_frame", "target_end"])
        supplied = self.create("prefix", startImagePath=self.media["startImagePath"])
        self.assertNotIn("first_render", [s["id"] for s in supplied["steps"]])
        mixed = self.create("mixed", temporalMode="suffix")
        self.assertEqual(mixed["steps"][2]["settings"]["sourceKey"], "spatial_video")

    def test_background_recipe_preserves_foreground_instruction(self):
        flow = self.create(spatialTarget="background")
        instruction = flow["steps"][0]["settings"]["instruction"]
        self.assertIn("仅重建背景", instruction)
        self.assertIn("保留原视频的前景主体", instruction)

    def test_missing_required_images_and_invalid_cut_are_rejected(self):
        for overrides in ({"referenceImagePath": ""}, {"mode": "suffix", "endImagePath": ""},
                          {"mode": "prefix", "cutSeconds": float("nan")}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.create(**overrides)

    def test_out_of_bounds_cut_does_not_submit_any_stage(self):
        flow = self.create("mixed", cutSeconds=40)
        calls = []
        result = self.run_worker(flow, execute=lambda *_: calls.append("called"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(calls, [])

    def test_editing_completed_prompt_invalidates_dependent_outputs(self):
        flow = self.create()
        self.assertEqual(self.run_worker(flow)["status"], "completed")
        old = flows.get_flow(flow["id"])
        self.assertEqual(old["status"], "completed")
        changed = flows.update_step(flow["id"], "spatial_prompt", {"prompt": "New edit"})
        self.assertTrue(all(s["status"] == "pending" for s in changed["steps"]))
        self.assertEqual(changed["outputs"], [])
        self.assertEqual(changed["steps"][0]["settings"]["prompt"], "New edit")
        with self.assertRaises(FileNotFoundError):
            flows.resolve_flow_file(flow["id"], "spatial_render_result")

    def test_failure_retry_preserves_completed_ancestor(self):
        flow = self.create()
        def fail_render(current, step, *args):
            if step["id"] == "spatial_render":
                raise RuntimeError("simulated failure")
            return self.execute(current, step, *args)
        self.assertEqual(self.run_worker(flow, execute=fail_render)["status"], "failed")
        failed = flows.get_flow(flow["id"])
        self.assertEqual([s["status"] for s in failed["steps"]], ["completed", "failed", "pending"])
        self.assertEqual(self.run_worker(failed)["status"], "completed")
        done = flows.get_flow(flow["id"])
        self.assertEqual([s["attempts"] for s in done["steps"]], [1, 2, 1])

    def test_stop_received_during_step_survives_worker_save(self):
        flow = self.create()
        def stop_after(current, step, *args):
            flows.request_stop(current["id"])
            return self.execute(current, step, *args)
        self.run_worker(flow, execute=stop_after)
        stopped = flows.get_flow(flow["id"])
        self.assertEqual(stopped["status"], "ready")
        self.assertEqual([s["status"] for s in stopped["steps"]], ["completed", "pending", "pending"])

    def test_double_submission_blocked_and_restart_recovered(self):
        flow = self.create()
        flows.claim_run(flow["id"], "first")
        with self.assertRaises(ValueError):
            flows.claim_run(flow["id"], "second")
        flows._ACTIVE.clear()
        recovered = flows.get_flow(flow["id"])
        self.assertEqual(recovered["status"], "failed")
        self.assertIn("重启", recovered["error"])

    def test_future_steps_cannot_run_before_dependencies(self):
        flow = self.create("prefix")
        with self.assertRaises(ValueError):
            flows.claim_run(flow["id"], "out-of-order", "motion_render")

    def test_ai_prompt_never_silently_uses_mock_output(self):
        flow = self.create(promptSource="ai")
        with patch.object(flows, "load_api_config", return_value={"use_mock": True}), \
             patch.object(flows, "OpenAICompatibleClient") as client:
            with self.assertRaisesRegex(ValueError, "Mock"):
                flows._run_prompt(flow, flow["steps"][0], self.root, lambda _: None)
            client.assert_not_called()


    def test_edit_instruction_regenerates_ai_but_negative_edit_preserves_positive(self):
        flow = self.create(promptSource="ai")
        with flows._LOCK:
            saved = flows._load(flow["id"])
            saved["steps"][0]["settings"]["prompt"] = "generated positive"
            saved["steps"][0]["status"] = "completed"
            flows._save(saved)
        changed = flows.update_step(flow["id"], "spatial_prompt", {"negativePrompt": "new negative"})
        self.assertEqual(changed["steps"][0]["settings"]["prompt"], "generated positive")
        regenerated = flows.update_step(flow["id"], "spatial_prompt", {"instruction": "new instruction"})
        self.assertEqual(regenerated["steps"][0]["settings"]["prompt"], "")

    def test_motion_handoff_uses_distinct_images_exact_output_and_stage_id(self):
        flow = self.create("prefix", startImagePath=self.media["startImagePath"])
        flow["artifacts"]["boundary_frame"] = flows._artifact("boundary_frame", self.media["endImagePath"], flow["id"])
        flow["media"] = {"replacement_duration": 4.0}
        step = next(s for s in flow["steps"] if s["id"] == "motion_render")
        step["attempts"] = 2
        captured = {}
        def generate(**kwargs):
            captured.update(kwargs)
            return {"status": "completed", "items": [{"path": self.media["videoPath"]}]}
        with patch.object(flows, "load_comfy_config", return_value={"workflow_manifest_dir": str(ROOT / "workflow")}), \
             patch.object(flows, "run_comfy_job", side_effect=generate):
            outputs = flows._run_comfy(flow, step, self.root, "parent", lambda _: None, lambda **_: None)
        payload = captured["payload"]
        self.assertEqual(captured["job_id"], "parent_motion_render_002")
        self.assertEqual(payload["outputNodeId"], "145")
        self.assertEqual(payload["formInputs"]["start_image_ref"], self.media["startImagePath"])
        self.assertEqual(payload["formInputs"]["end_image_ref"], self.media["endImagePath"])
        self.assertEqual(payload["formInputs"]["params.node_162.value"] % 4, 1)
        self.assertEqual(outputs[0]["key"], "replacement_video")


if __name__ == "__main__":
    unittest.main()
