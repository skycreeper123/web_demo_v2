"""Recipe state and handoff checks; all media/model execution is replaced locally."""
import importlib.util
import json
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
from web_demo.backend.app.services.comfyui_comm.workflow_binder import bind_workflow, resolve_template_payload


class FlowTests(unittest.TestCase):
    def test_duration_means_replacement_length_in_both_directions(self):
        for mode in ("prefix", "suffix", "mixed"):
            for duration in (2, 5, 8):
                for direction in (("prefix", "suffix") if mode == "mixed" else (mode,)):
                    flow = self.create(mode, temporalMode=direction, cutMode="duration", replacementSeconds=duration,
                                       mixedScope="region", outputShortSide=480, outputFps=24)
                    result = self.run_worker(flow)
                    self.assertEqual(result["status"], "completed")
                    saved = flows.get_flow(flow["id"])
                    self.assertEqual(saved["inputs"]["cutSeconds"], duration if direction == "prefix" else 10-duration)
                    self.assertEqual(saved["inputs"]["outputFps"], 24)
                    if mode == "mixed":
                        self.assertEqual([s["id"] for s in saved["steps"]], ["prepare_region", "spatial_prompt", "spatial_render", "assemble_region"])
                        self.assertEqual(saved["steps"][2]["settings"]["sourceKey"], "target_video")

    def test_source_and_replacement_duration_validation_happens_before_model_work(self):
        for options in ({"expectedSourceSeconds": 10}, {"cutMode": "duration", "replacementSeconds": 8}):
            flow = self.create("suffix", **options)
            calls = []
            result = self.run_worker(flow, duration=6, execute=lambda *args: calls.append(args))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(calls, [])

    def test_regional_generation_receives_only_the_selected_video_and_saved_profile(self):
        flow = self.create("mixed", mixedScope="region", cutMode="duration", replacementSeconds=2,
                           generationLongSide=768, generationFps=24, outputShortSide=480, outputFps=60)
        target = self.root / "target.mp4"
        target.write_bytes(b"target")
        flow["artifacts"]["target_video"] = flows._artifact("target_video", target, flow["id"])
        step = next(s for s in flow["steps"] if s["id"] == "spatial_render")
        with patch.object(flows, "load_comfy_config", return_value={"workflow_manifest_dir": str(ROOT / "workflow")}), \
             patch.object(flows, "probe_video", return_value={"width": 1280, "height": 720, "duration": 10}), \
             patch.object(flows, "run_comfy_job", return_value={"status": "completed", "items": [{"path": str(target)}]}) as comfy:
            flows._run_comfy(flow, step, self.root, "region", lambda _: None, lambda **_: None)
        form = comfy.call_args.kwargs["payload"]["formInputs"]
        self.assertEqual(form["video_ref"], str(target))
        self.assertEqual((form["params.width"], form["params.height"], form["params.fps"]), (768, 432, 24))
        graph = json.loads(comfy.call_args.kwargs["payload"]["workflowJsonText"])
        self.assertNotIn("audio", graph["40"]["inputs"])

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
                                  "promptSource": "manual", "generationPolicy": "legacy", **overrides})

    def test_new_flows_default_to_native_and_model_receives_target_specs(self):
        fresh = flows.build_flow({**self.media, 'mode': 'spatial'})
        self.assertEqual(fresh['inputs']['generationPolicy'], 'native')
        for mode in ('mixed', 'suffix'):
            with self.subTest(mode=mode):
                flow = self.create(mode, generationPolicy='native', mixedScope='region', spatialTarget='background',
                                   outputShortSide=480, outputFps=60)
                flow['media'] = {'replacement_duration': 2}
                flow['artifacts']['target_video'] = flow['artifacts']['source_video']
                flow['artifacts']['boundary_frame'] = flows._artifact('boundary_frame', self.media['endImagePath'], flow['id'])
                step = next(s for s in flow['steps'] if s['id'] == ('spatial_render' if mode == 'mixed' else 'motion_render'))
                out = self.root / f'{mode}.mp4'; out.write_bytes(b'output')
                def probe(path):
                    return ({'width':864, 'height':480, 'fps':60, 'frames':121, 'duration':121/60}
                            if Path(path) == out else {'width':1280,'height':720,'fps':24,'frames':240,'duration':10})
                with patch.object(flows, 'probe_video', side_effect=probe), \
                     patch.object(flows, 'prepare_native_conditioning', return_value=self.root/'conditions.mp4') as prepare, \
                     patch.object(flows, 'load_comfy_config', return_value={'workflow_manifest_dir':str(ROOT/'workflow')}), \
                     patch.object(flows.ComfyServerClient, 'get_object_info', return_value={'UGCDrawBlackMask': {'input': {}}}), \
                     patch.object(flows, 'run_comfy_job', return_value={'status':'completed','items':[{'path':str(out)}]}) as run:
                    outputs = flows._run_comfy(flow, step, self.root, 'native', lambda _:None, lambda **_:None)
                payload = run.call_args.kwargs['payload']; form=payload['formInputs']; graph=json.loads(payload['workflowJsonText'])
                if mode == 'mixed':
                    self.assertEqual((form['params.width'], form['params.height'], form['params.fps']), (864,480,60))
                    self.assertEqual(prepare.call_args.args[2]['requested_frames'],121)
                    self.assertEqual(graph['2']['inputs']['format'],'None')
                    self.assertEqual(graph['14']['class_type'], 'UGCTrackedPeopleMask')
                    self.assertEqual(graph['17']['class_type'], 'UGCDrawBlackMask')
                    reloaded = resolve_template_payload(payload, {})
                    self.assertNotIn('params.node_14.keep_model_loaded', reloaded['bindings'])
                    self.assertNotIn('params.node_17.color', reloaded['bindings'])
                    self.assertIn('params.width', reloaded['bindings'])
                else:
                    self.assertEqual(form['params.node_162.value'],121)
                    self.assertEqual(form['params.node_145.frame_rate'],60)
                    self.assertEqual(graph['145']['inputs']['images'],graph['246']['inputs']['image'])
                self.assertTrue(any(o['key'].endswith('_spec') for o in outputs))

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
        for overrides in ({"referenceImagePath": ""}, {"mode": "suffix", "endImagePath": str(self.root / "missing.png")},
                          {"mode": "prefix", "cutSeconds": float("nan")}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.create(**overrides)

    def fake_prepare(self, source, directory, direction, cut, *, extract_target_end=False):
        result = {"duration": 10, "fps": 30, "replacement_duration": cut if direction == "prefix" else 10 - cut}
        keys = ["retained_video", "boundary_frame", "original_first_frame"]
        if extract_target_end:
            keys.append("target_end")
        for key in keys:
            path = directory / (key + (".mp4" if key == "retained_video" else ".png"))
            path.write_bytes(key.encode())
            result[key] = str(path)
        return result

    def test_suffix_without_target_uses_separate_source_end_in_prompt_and_comfy(self):
        flow = self.create("suffix", endImagePath="")
        self.assertNotIn("target_end", flow["artifacts"])
        prepare_step = flows._step(flow, "prepare")
        prepare_step["attempts"] = 1
        with patch.object(flows, "prepare_temporal", side_effect=self.fake_prepare) as prepare:
            outputs = flows._execute_step(flow, prepare_step, "offline", lambda _: None, lambda **_: None)
        self.assertEqual(prepare.call_args.args[0], Path(self.media["videoPath"]))
        self.assertTrue(prepare.call_args.kwargs["extract_target_end"])
        flow["artifacts"].update({item["key"]: item for item in outputs})
        self.assertNotEqual(flow["artifacts"]["boundary_frame"]["path"], flow["artifacts"]["target_end"]["path"])
        self.assertNotIn("target_end", flow["media"])
        self.assertEqual(flows._step(flow, "motion_prompt")["settings"]["media"], ["boundary_frame", "target_end"])
        with patch.object(flows, "load_comfy_config", return_value={"workflow_manifest_dir": str(ROOT / "workflow")}), \
             patch.object(flows, "probe_video", return_value={"width": 1280, "height": 720, "fps": 24, "duration": 10}), \
             patch.object(flows, "run_comfy_job", return_value={"status": "completed", "items": [{"path": self.media["videoPath"]}]}) as comfy:
            flows._run_comfy(flow, flows._step(flow, "motion_render"), self.root, "offline", lambda _: None, lambda **_: None)
        form = comfy.call_args.kwargs["payload"]["formInputs"]
        self.assertEqual(form["start_image_ref"], flow["artifacts"]["boundary_frame"]["path"])
        self.assertEqual(form["end_image_ref"], flow["artifacts"]["target_end"]["path"])

    def test_prepare_rerun_invalidates_auto_end_but_preserves_supplied_end(self):
        for supplied in (False, True):
            with self.subTest(supplied=supplied):
                flow = self.create("suffix", endImagePath=self.media["endImagePath"] if supplied else "")
                step = flows._step(flow, "prepare")
                step["attempts"] = 1
                with patch.object(flows, "prepare_temporal", side_effect=self.fake_prepare) as prepare:
                    outputs = flows._execute_step(flow, step, "offline", lambda _: None, lambda **_: None)
                self.assertEqual(bool(prepare.call_args.kwargs.get("extract_target_end")), not supplied)
                step.update(status="completed", outputs=outputs)
                flow["artifacts"].update({item["key"]: item for item in outputs})
                flows._save(flow)
                # Redoing a later step must keep its prepared input frames.
                flows._invalidate(flow, 1)
                self.assertIn("target_end", flow["artifacts"])
                flows._save(flow)
                claimed = flows.claim_run(flow["id"], "prepare-again", "prepare")
                self.assertEqual("target_end" in claimed["artifacts"], supplied)
                if supplied:
                    self.assertEqual(claimed["artifacts"]["target_end"]["path"], self.media["endImagePath"])
                else:
                    self.assertNotIn("target_end", claimed["artifacts"])
                flows._ACTIVE.discard(flow["id"])

    def test_mixed_suffix_extracts_target_from_normalized_spatial_video(self):
        flow = self.create("mixed", temporalMode="suffix", endImagePath="")
        spatial = self.root / "edited_spatial.mp4"
        spatial.write_bytes(b"offline spatial placeholder")
        flow["artifacts"]["spatial_video"] = flows._artifact("spatial_video", spatial, flow["id"])
        step = flows._step(flow, "prepare")
        step["attempts"] = 1

        def normalize(generated, source, output, **kwargs):
            output.write_bytes(b"offline normalized placeholder")

        with patch.object(flows, "finalize_spatial", side_effect=normalize) as finalize, \
             patch.object(flows, "prepare_temporal", side_effect=self.fake_prepare) as prepare:
            outputs = flows._execute_step(flow, step, "offline", lambda _: None, lambda **_: None)
        self.assertEqual(finalize.call_args.args[:2], (spatial, Path(self.media["videoPath"])))
        self.assertEqual(prepare.call_args.args[0], finalize.call_args.args[2])
        self.assertEqual(prepare.call_args.args[0].name, "spatial_normalized.mp4")
        self.assertTrue(prepare.call_args.kwargs["extract_target_end"])
        self.assertIn("target_end", {item["key"] for item in outputs})

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
             patch.object(flows, "probe_video", return_value={"width": 1280, "height": 720, "fps": 24, "duration": 10}), \
             patch.object(flows, "run_comfy_job", side_effect=generate):
            outputs = flows._run_comfy(flow, step, self.root, "parent", lambda _: None, lambda **_: None)
        payload = captured["payload"]
        self.assertEqual(captured["job_id"], "parent_motion_render_002")
        self.assertEqual(payload["outputNodeId"], "145")
        self.assertEqual(payload["formInputs"]["start_image_ref"], self.media["startImagePath"])
        self.assertEqual(payload["formInputs"]["end_image_ref"], self.media["endImagePath"])
        self.assertEqual(payload["formInputs"]["params.node_162.value"], 121)
        self.assertEqual(payload["formInputs"]["params.node_145.frame_rate"], 30)
        self.assertEqual(payload["formInputs"]["params.node_160.value"], 1920)
        self.assertEqual(payload["formInputs"]["params.node_161.value"], 1088)
        self.assertEqual(outputs[0]["key"], "replacement_video")

    def test_recipes_use_public_full_video_for_people_and_hd_for_motion(self):
        for mode, direction in (("spatial", "prefix"), ("prefix", "prefix"),
                                ("suffix", "suffix"), ("mixed", "prefix"), ("mixed", "suffix")):
            for source_width, source_height, width, height in ((1280, 720, 1920, 1088),
                                                              (720, 1280, 1088, 1920)):
                with self.subTest(mode=mode, direction=direction, source=(source_width, source_height)):
                    flow = self.create(mode, temporalMode=direction, startImagePath=self.media["startImagePath"])
                    flow["artifacts"]["boundary_frame"] = flows._artifact("boundary_frame", self.media["endImagePath"], flow["id"])
                    flow["media"] = {"replacement_duration": 6.0}
                    for step in flow["steps"]:
                        if step["kind"] != "comfy" or step["settings"]["role"] == "first_image":
                            continue
                        with patch.object(flows, "load_comfy_config", return_value={"workflow_manifest_dir": str(ROOT / "workflow")}), \
                             patch.object(flows, "probe_video", return_value={"width": source_width, "height": source_height, "fps": 24, "duration": 10}), \
                             patch.object(flows, "run_comfy_job", return_value={"status": "completed", "items": [{"path": self.media["videoPath"]}]}) as comfy:
                            flows._run_comfy(flow, step, self.root, "hd", lambda _: None, lambda **_: None)
                        form = comfy.call_args.kwargs["payload"]["formInputs"]
                        if step["settings"]["role"] == "spatial":
                            payload = comfy.call_args.kwargs["payload"]
                            self.assertEqual(payload["templateKey"], "wan_animate_public_replace.json")
                            self.assertEqual(payload["outputNodeId"], "40")
                            expected = (512, 288) if source_width > source_height else (288, 512)
                            self.assertEqual((form["params.width"], form["params.height"]), expected)
                            self.assertEqual(form["params.fps"], 16)
                            self.assertEqual(form["params.frame_limit"], 0)
                            self.assertEqual(form["params.node_2.skip_first_frames"], 0)
                            self.assertEqual(form["params.node_2.select_every_nth"], 1)
                        else:
                            self.assertEqual((form["params.node_160.value"], form["params.node_161.value"]), (width, height))
                            self.assertEqual(form["params.node_145.frame_rate"], 30)
                            self.assertEqual(form["params.node_162.value"], 181)

    def test_background_edits_inverse_region_and_restores_original_person(self):
        flow = self.create(spatialTarget="background")
        step = next(s for s in flow["steps"] if s["id"] == "spatial_render")
        with patch.object(flows, "load_comfy_config", return_value={"workflow_manifest_dir": str(ROOT / "workflow")}), \
             patch.object(flows, "probe_video", return_value={"width": 1280, "height": 720, "duration": 10}), \
             patch.object(flows, "run_comfy_job", return_value={"status": "completed", "items": [{"path": self.media["videoPath"]}]}) as comfy:
            flows._run_comfy(flow, step, self.root, "legacy", lambda _: None, lambda **_: None)
        payload = comfy.call_args.kwargs["payload"]
        self.assertEqual(payload["templateKey"], flows.TEMPLATES["spatial"]["key"])
        self.assertEqual(payload["formInputs"]["params.frame_limit"], 0)
        graph = json.loads(payload["workflowJsonText"])
        self.assertEqual(graph["18"]["inputs"]["mask"], ["14", 0])
        self.assertEqual(graph["15"]["inputs"]["mask"], ["18", 0])
        self.assertEqual(graph["30"]["inputs"]["mask"], graph["17"]["inputs"]["mask"])
        composite = graph[graph["40"]["inputs"]["images"][0]]
        self.assertEqual(composite["class_type"], "ImageCompositeMasked")
        self.assertEqual(composite["inputs"]["source"], ["3", 0])
        self.assertEqual(composite["inputs"]["mask"], ["14", 0])
        self.assertEqual(composite["inputs"]["destination"], ["33", 0])
        self.assertNotIn("audio", graph["40"]["inputs"])

    def test_native_background_uses_bounded_composite_when_installed(self):
        flow = self.create(spatialTarget="background", generationPolicy="native",
                           outputShortSide=1080, outputFps=24)
        step = next(s for s in flow["steps"] if s["id"] == "spatial_render")
        source = {"width": 1280, "height": 720, "duration": 10, "fps": 24, "frames": 240}
        output = {"width": 1920, "height": 1088, "duration": 241/24, "fps": 24, "frames": 241}
        video = self.root / "generated.mp4"
        video.write_bytes(b"video")
        node = "UGCCompositeBackground"
        for installed in (True, False):
            with self.subTest(installed=installed), \
                 patch.object(flows, "load_comfy_config", return_value={"workflow_manifest_dir": str(ROOT / "workflow")}), \
                 patch.object(flows, "probe_video", side_effect=[source, output]), \
                 patch.object(flows, "prepare_native_conditioning", return_value=self.root / "conditions.mp4"), \
                 patch.object(flows.ComfyServerClient, "get_object_info", return_value={node: {'input': {}}} if installed else {}) as info, \
                 patch.object(flows, "run_comfy_job", return_value={"status": "completed", "items": [{"path": str(video)}]}) as comfy:
                flows._run_comfy(flow, step, self.root, "native", lambda _: None, lambda **_: None)
            self.assertEqual([call.args for call in info.call_args_list], [('UGCDrawBlackMask',), (node,)])
            graph = json.loads(comfy.call_args.kwargs["payload"]["workflowJsonText"])
            self.assertEqual(graph["40"]["inputs"]["images"], ["34", 0])
            composite = graph["34"]
            self.assertEqual(composite["class_type"], node if installed else "ImageCompositeMasked")
            self.assertEqual(composite["inputs"]["destination"], ["32", 0] if installed else ["33", 0])
            self.assertEqual(composite["inputs"]["source"], ["3", 0])
            self.assertEqual(composite["inputs"]["mask"], ["14", 0])

    def test_native_1080p60_motion_selects_supported_chunked_rope(self):
        flow = self.create('suffix', generationPolicy='native', outputShortSide=1080, outputFps=60)
        source = {'width': 1280, 'height': 720, 'duration': 10, 'fps': 24, 'frames': 240}
        output = {'width': 1920, 'height': 1088, 'duration': 301/60, 'fps': 60, 'frames': 301}
        flow['media'] = {'replacement_duration': 5}
        flow['artifacts']['boundary_frame'] = flows._artifact('boundary_frame', self.media['endImagePath'], flow['id'])
        flow['artifacts']['target_end'] = flow['artifacts']['boundary_frame']
        step = next(s for s in flow['steps'] if s['id'] == 'motion_render')
        video = self.root / 'generated.mp4'
        video.write_bytes(b'video')
        info = {'WanVideoSampler': {'input': {'optional': {'rope_function': [['comfy', 'comfy_chunked']]}}}}
        with patch.object(flows, 'load_comfy_config', return_value={'workflow_manifest_dir': str(ROOT/'workflow')}), \
             patch.object(flows, 'probe_video', side_effect=[source, output]), \
             patch.object(flows.ComfyServerClient, 'get_object_info', return_value=info), \
             patch.object(flows, 'run_comfy_job', return_value={'status': 'completed', 'items': [{'path': str(video)}]}) as comfy:
            flows._run_comfy(flow, step, self.root, 'native', lambda _: None, lambda **_: None)
        payload = comfy.call_args.kwargs['payload']
        graph = resolve_template_payload(payload, {})['workflow']
        self.assertEqual(graph['90']['inputs']['rope_function'], 'comfy_chunked')
        self.assertEqual(graph['213']['inputs']['rope_function'], 'comfy_chunked')
        self.assertEqual(payload['formInputs']['params.node_162.value'], 301)
        self.assertEqual(payload['formInputs']['params.node_145.frame_rate'], 60)

    def test_public_graph_preserves_video_frame_count_and_removes_window_padding(self):
        resolved = flows.resolve_template_payload({"templateKey": "wan_animate_public_replace.json"},
                                                   {"workflow_manifest_dir": str(ROOT / "workflow")})
        graph = bind_workflow(template_payload=resolved,
                              staged_inputs={"image_ref": "ref.png", "video_ref": "source.mp4"},
                              payload={"positivePrompt": "replace person", "outputNodeId": "40",
                                       "params": {"fps": 16, "frame_limit": 0}})
        self.assertEqual(graph["2"]["inputs"]["frame_load_cap"], 0)
        self.assertEqual(graph["2"]["inputs"]["force_rate"], graph["40"]["inputs"]["frame_rate"])
        self.assertEqual(graph["30"]["inputs"]["num_frames"], ["3", 3])
        trim = graph[graph["40"]["inputs"]["images"][0]]
        self.assertEqual(trim["class_type"], "ImageFromBatch")
        self.assertEqual(trim["inputs"], {"image": ["32", 0], "batch_index": 0, "length": ["3", 3]})


if __name__ == "__main__":
    unittest.main()
