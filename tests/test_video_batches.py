"""Batch scheduling regressions with local fake assets; no model or media calls."""

import importlib.util
import csv
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services import video_batch_service as batches
from web_demo.backend.app.services import video_flow_service as flows


class VideoBatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(flows, "FLOW_ROOT", self.root / "flows").start()
        patch.object(batches, "BATCH_ROOT", self.root / "batches").start()
        # These fail loudly if a supposedly offline scheduling test escapes its
        # mocked execution boundary into an actual model, server, or media call.
        for name in ("OpenAICompatibleClient", "run_comfy_job", "prepare_temporal",
                     "assemble_video", "finalize_spatial", "probe_video"):
            patch.object(flows, name, side_effect=AssertionError(f"Unexpected external operation: {name}")).start()
        flows._ACTIVE.clear()
        flows._BATCH_CLAIMS.clear()
        batches._ACTIVE.clear()
        self.calls = []

    def tearDown(self):
        batches._ACTIVE.clear()
        flows._ACTIVE.clear()
        flows._BATCH_CLAIMS.clear()

    def payload(self, count=3, **defaults):
        rows = []
        source_root = self.root / "sources"
        source_root.mkdir(exist_ok=True)
        for index in range(count):
            video = source_root / f"source-{index + 1:03d}.mp4"
            reference = source_root / f"reference-{index + 1:03d}.png"
            video.write_bytes(f"video-{index}".encode())
            reference.write_bytes(f"image-{index}".encode())
            rows.append({"name": f"group-{index + 1:03d}", "videoPath": str(video),
                         "referenceImagePath": str(reference), "editInstruction": f"edit group {index + 1}"})
        return {"name": "offline batch", "defaults": {"mode": "spatial", "promptSource": "ai", **defaults}, "rows": rows}

    def create(self, count=3, **defaults):
        return batches.create_batch(self.payload(count, **defaults))

    def execute(self, flow, step, *_args):
        self.calls.append((flow["id"], step["id"]))
        directory = self.root / "fake-results" / flow["id"]
        directory.mkdir(parents=True, exist_ok=True)
        final = step["id"] in {"finish", "assemble"}
        path = directory / f"{step['id']}-{step['attempts']}{'.mp4' if final else '.txt'}"
        path.write_bytes(b"offline-placeholder")
        key = "final_video" if final else step["id"] + "_result"
        return [flows._artifact(key, path, flow["id"])]

    def run_batch(self, batch, *, retry_failed=False, execute=None, job_id="offline-batch-job"):
        batches.claim_batch(batch["id"], job_id, retry_failed=retry_failed)
        with patch.object(flows, "_execute_step", side_effect=execute or self.execute):
            return batches.run_batch(batch_id=batch["id"], job_id=job_id,
                                     log=lambda _: None, progress=lambda *_: None, update_job=lambda **_: None)

    def test_create_one_hundred_distinct_groups_with_one_shared_recipe(self):
        batch = self.create(100, spatialTarget="background")
        self.assertEqual(batch["total"], 100)
        self.assertEqual(len(batch["rows"]), 100)
        self.assertEqual(len({row["flowId"] for row in batch["rows"]}), 100)
        self.assertEqual([row["index"] for row in batch["rows"]], list(range(1, 101)))
        self.assertEqual(batch["mode"], "spatial")
        self.assertEqual(batch["spatialTarget"], "background")
        sources = set()
        for row in batch["rows"]:
            flow = flows.get_flow(row["flowId"])
            self.assertEqual(flow["batchId"], batch["id"])
            self.assertEqual(flow["inputs"]["promptSource"], "ai")
            self.assertEqual(flow["inputs"]["spatialTarget"], "background")
            self.assertEqual(flow["inputs"]["editInstruction"], f"edit group {row['index']}")
            sources.add(flow["inputs"]["videoPath"])
        self.assertEqual(len(sources), 100)

    def test_one_hundred_groups_execute_in_order_with_unique_child_jobs(self):
        batch = self.create(100)
        with patch.object(flows, "claim_run", wraps=flows.claim_run) as claim:
            self.run_batch(batch)
        state = batches.get_batch(batch["id"])
        expected = [(row["flowId"], step) for row in batch["rows"]
                    for step in ("spatial_prompt", "spatial_render", "finish")]
        self.assertEqual(self.calls, expected)
        child_jobs = [call.args[1] if len(call.args) > 1 else call.kwargs["job_id"] for call in claim.call_args_list]
        self.assertEqual(len(child_jobs), 100)
        self.assertEqual(len(set(child_jobs)), 100)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["completed"], 100)
        self.assertEqual(state["failed"], 0)
        self.assertTrue(all(row["status"] == "completed" and row["finalVideo"] for row in state["rows"]))
        self.assertTrue(all(not flows.get_flow(row["flowId"])["batchLocked"] for row in batch["rows"]))
        with batches.resolve_manifest(batch["id"]).open(encoding="utf-8-sig", newline="") as handle:
            manifest = list(csv.DictReader(handle))
        self.assertEqual(len(manifest), 100)
        self.assertEqual([row["flow_id"] for row in manifest], [row["flowId"] for row in batch["rows"]])
        self.assertTrue(all(row["status"] == "completed" and row["final_video"] for row in manifest))

    def test_failure_continues_other_groups_and_retry_only_runs_failed_group(self):
        batch = self.create(4)
        failed_id = batch["rows"][1]["flowId"]

        def fail_second(flow, step, *args):
            if flow["id"] == failed_id and step["id"] == "spatial_render":
                self.calls.append((flow["id"], step["id"]))
                raise RuntimeError("offline render failure")
            return self.execute(flow, step, *args)

        self.run_batch(batch, execute=fail_second)
        failed = batches.get_batch(batch["id"])
        self.assertEqual([row["status"] for row in failed["rows"]], ["completed", "failed", "completed", "completed"])
        self.assertEqual(failed["completed"], 3)
        self.assertEqual(failed["failed"], 1)
        self.assertEqual(flows.get_flow(failed_id)["steps"][0]["attempts"], 1)
        log_path = batches.resolve_log(batch["id"])
        first_log = log_path.read_text(encoding="utf-8")
        self.assertIn("offline-batch-job", first_log)
        self.assertIn("offline render failure", first_log)
        self.calls.clear()
        self.run_batch(batch, retry_failed=True, job_id="retry-job")
        self.assertEqual(self.calls, [(failed_id, "spatial_render"), (failed_id, "finish")])
        final = batches.get_batch(batch["id"])
        self.assertEqual(final["completed"], 4)
        complete_log = log_path.read_text(encoding="utf-8")
        self.assertTrue(complete_log.startswith(first_log))
        self.assertIn("retry-job", complete_log)
        for row in final["rows"]:
            self.assertIn(row["name"], complete_log)
            self.assertIn(row["finalVideo"]["path"], complete_log)
        self.assertTrue(all(line.startswith("[") for line in complete_log.splitlines()))

    def test_stop_during_step_preserves_completed_steps_and_resumes(self):
        batch = self.create(3)
        first_id = batch["rows"][0]["flowId"]

        def stop_first(flow, step, *args):
            result = self.execute(flow, step, *args)
            batches.request_stop(batch["id"])
            return result

        self.run_batch(batch, execute=stop_first)
        stopped = batches.get_batch(batch["id"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["completed"], 0)
        self.assertEqual(stopped["rows"][0]["status"], "pending")
        self.assertEqual(self.calls, [(first_id, "spatial_prompt")])
        self.calls.clear()
        self.run_batch(batch, job_id="resume-job")
        self.assertNotIn((first_id, "spatial_prompt"), self.calls)
        self.assertEqual(self.calls[0], (first_id, "spatial_render"))
        self.assertEqual(batches.get_batch(batch["id"])["completed"], 3)

    def test_completed_group_is_skipped_when_continuing_stopped_batch(self):
        batch = self.create(3)
        first_id = batch["rows"][0]["flowId"]

        def stop_after_first(flow, step, *args):
            result = self.execute(flow, step, *args)
            if flow["id"] == first_id and step["id"] == "finish":
                batches.request_stop(batch["id"])
            return result

        self.run_batch(batch, execute=stop_after_first)
        stopped = batches.get_batch(batch["id"])
        self.assertEqual(stopped["completed"], 1)
        self.assertEqual(stopped["rows"][0]["status"], "completed")
        self.calls.clear()
        self.run_batch(batch, job_id="continue-job")
        self.assertFalse(any(flow_id == first_id for flow_id, _ in self.calls))
        self.assertEqual(batches.get_batch(batch["id"])["completed"], 3)

    def test_missing_successful_output_only_retries_that_groups_export(self):
        batch = self.create(3)
        self.run_batch(batch)
        state = batches.get_batch(batch["id"])
        missing = state["rows"][1]
        Path(missing["finalVideo"]["path"]).unlink()
        state = batches.get_batch(batch["id"])
        self.assertEqual(state["completed"], 2)
        self.assertEqual(state["failed"], 1)
        self.assertEqual(state["rows"][1]["status"], "failed")
        self.calls.clear()
        self.run_batch(batch, retry_failed=True, job_id="repair-export")
        self.assertEqual(self.calls, [(missing["flowId"], "finish")])
        self.assertEqual(batches.get_batch(batch["id"])["completed"], 3)

    def test_child_claim_error_remains_failed_after_refresh_and_can_be_retried(self):
        batch = self.create(3)
        failed_id = batch["rows"][1]["flowId"]
        original_claim = flows.claim_run

        def fail_claim(flow_id, *args, **kwargs):
            if flow_id == failed_id:
                raise ValueError("offline child dispatch failure")
            return original_claim(flow_id, *args, **kwargs)

        with patch.object(flows, "claim_run", side_effect=fail_claim):
            self.run_batch(batch)
        for _ in range(2):
            state = batches.get_batch(batch["id"])
            self.assertEqual([row["status"] for row in state["rows"]], ["completed", "failed", "completed"])
            self.assertIn("dispatch failure", state["rows"][1]["error"])
        self.calls.clear()
        self.run_batch(batch, retry_failed=True, job_id="dispatch-retry")
        self.assertEqual({flow_id for flow_id, _ in self.calls}, {failed_id})
        self.assertEqual(batches.get_batch(batch["id"])["completed"], 3)

    def test_duplicate_start_and_standalone_child_run_are_blocked(self):
        batch = self.create(3)
        batches.claim_batch(batch["id"], "first-job")
        with self.assertRaises(ValueError):
            batches.claim_batch(batch["id"], "duplicate-job")
        for row in batch["rows"]:
            self.assertTrue(flows.get_flow(row["flowId"])["batchLocked"])
            with self.assertRaises(ValueError):
                flows.claim_run(row["flowId"], "standalone-job")
            with self.assertRaises(ValueError):
                flows.update_step(row["flowId"], "spatial_prompt", {"prompt": "competing edit"})

    def test_standalone_child_blocks_batch_without_leaking_other_reservations(self):
        batch = self.create(3)
        flows.claim_run(batch["rows"][-1]["flowId"], "standalone-first")
        with self.assertRaises(ValueError):
            batches.claim_batch(batch["id"], "batch-second")
        self.assertNotIn(batch["id"], batches._ACTIVE)
        self.assertTrue(all(not flows.get_flow(row["flowId"])["batchLocked"] for row in batch["rows"][:-1]))

    def test_racing_batch_and_standalone_claim_have_exactly_one_owner(self):
        batch = self.create(3)
        barrier = threading.Barrier(2)

        def claim_batch():
            barrier.wait(timeout=3)
            try:
                batches.claim_batch(batch["id"], "batch-race")
                return "batch"
            except ValueError:
                return None

        def claim_standalone():
            barrier.wait(timeout=3)
            try:
                flows.claim_run(batch["rows"][-1]["flowId"], "standalone-race")
                return "standalone"
            except ValueError:
                return None

        owners = []
        errors = []

        def run_claim(action):
            try:
                owners.append(action())
            except BaseException as exc:
                errors.append(exc)

        workers = [threading.Thread(target=run_claim, args=(action,), daemon=True)
                   for action in (claim_batch, claim_standalone)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
        self.assertFalse(any(worker.is_alive() for worker in workers), "Flow/batch claim locks deadlocked")
        self.assertEqual(errors, [])
        self.assertEqual(sum(owner is not None for owner in owners), 1)

    def test_process_interruption_requires_explicit_failed_retry(self):
        batch = self.create(3)
        first_id = batch["rows"][0]["flowId"]

        def interrupt_comfy(flow, step, *args):
            if step["id"] == "spatial_render":
                raise KeyboardInterrupt()
            return self.execute(flow, step, *args)

        with self.assertRaises(KeyboardInterrupt):
            self.run_batch(batch, execute=interrupt_comfy)
        # A new process has no live workers or in-memory reservations.
        batches._ACTIVE.clear()
        flows._ACTIVE.clear()
        flows._BATCH_CLAIMS.clear()
        interrupted = batches.get_batch(batch["id"])
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertTrue(interrupted["requiresReview"])
        self.assertEqual(interrupted["rows"][0]["status"], "failed")
        with self.assertRaises(ValueError):
            batches.claim_batch(batch["id"], "unsafe-auto-resume")
        self.run_batch(batch, retry_failed=True, job_id="reviewed-retry")
        self.assertEqual({flow_id for flow_id, _ in self.calls}, {first_id})
        state = batches.get_batch(batch["id"])
        self.assertEqual(state["completed"], 1)
        self.assertEqual(state["pending"], 2)

    def test_restart_at_safe_dispatch_boundaries_resumes_pending_groups(self):
        for after_child in (False, True):
            with self.subTest(after_child_completed=after_child):
                batch = self.create(3)
                if after_child:
                    original_run = flows.run_flow_steps

                    def child_finishes_then_process_exits(**kwargs):
                        original_run(**kwargs)
                        raise KeyboardInterrupt()

                    with patch.object(flows, "run_flow_steps", side_effect=child_finishes_then_process_exits), \
                         self.assertRaises(KeyboardInterrupt):
                        self.run_batch(batch)
                else:
                    batches.claim_batch(batch["id"], "claimed-before-restart")
                batches._ACTIVE.clear()
                flows._ACTIVE.clear()
                flows._BATCH_CLAIMS.clear()
                restored = batches.get_batch(batch["id"])
                self.assertFalse(restored["requiresReview"])
                self.assertEqual(restored["pending"], 2 if after_child else 3)
                self.assertEqual(restored["completed"], 1 if after_child else 0)
                self.calls.clear()
                self.run_batch(batch, job_id="safe-resume-after-restart")
                if after_child:
                    self.assertFalse(any(flow_id == batch["rows"][0]["flowId"] for flow_id, _ in self.calls))
                self.assertEqual(batches.get_batch(batch["id"])["completed"], 3)

    def test_manually_resolved_unknown_child_allows_remaining_groups_to_continue(self):
        batch = self.create(3)
        first_id = batch["rows"][0]["flowId"]

        def unknown(flow, step, *args):
            if step["id"] == "spatial_render":
                raise flows.ComfyOutcomeUnknown("offline unknown server result")
            return self.execute(flow, step, *args)

        self.run_batch(batch, execute=unknown)
        self.assertTrue(batches.get_batch(batch["id"])["requiresReview"])
        flows.claim_run(first_id, "manual-reviewed-repair")
        with patch.object(flows, "_execute_step", side_effect=self.execute):
            flows.run_flow_steps(flow_id=first_id, job_id="manual-reviewed-repair", run_all=True,
                                 log=lambda _: None, progress=lambda *_: None, update_job=lambda **_: None)
        restored = batches.get_batch(batch["id"])
        self.assertFalse(restored["requiresReview"])
        self.assertEqual(restored["completed"], 1)
        self.calls.clear()
        self.run_batch(batch, job_id="remaining-after-manual-repair")
        self.assertFalse(any(flow_id == first_id for flow_id, _ in self.calls))
        self.assertEqual(batches.get_batch(batch["id"])["completed"], 3)

    def test_unknown_comfy_outcome_stops_batch_before_next_group(self):
        batch = self.create(3)
        first_id = batch["rows"][0]["flowId"]

        def unknown(flow, step, *args):
            if step["id"] == "spatial_render":
                raise flows.ComfyOutcomeUnknown("JOB_TIMEOUT: server may still be running")
            return self.execute(flow, step, *args)

        self.run_batch(batch, execute=unknown)
        state = batches.get_batch(batch["id"])
        self.assertTrue(state["requiresReview"])
        self.assertEqual(state["rows"][0]["status"], "failed")
        self.assertEqual(state["failed"], 1)
        self.assertEqual(state["pending"], 2)
        self.assertEqual({flow_id for flow_id, _ in self.calls}, {first_id})
        with self.assertRaises(ValueError):
            batches.claim_batch(batch["id"], "unsafe-timeout-resume")

    def test_invalid_last_group_leaves_no_partial_batch_or_child_flows(self):
        payload = self.payload(100)
        payload["rows"][-1]["videoPath"] = str(self.root / "missing-last-video.mp4")
        with self.assertRaises(ValueError):
            batches.create_batch(payload)
        self.assertEqual(list((self.root / "batches").glob("*/batch.json")), [])
        self.assertEqual(list((self.root / "flows").glob("*/flow.json")), [])

    def test_save_failure_rolls_back_children_created_before_it(self):
        original_save = flows._save
        calls = 0

        def fail_third_save(flow):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("offline simulated storage failure")
            return original_save(flow)

        with patch.object(flows, "_save", side_effect=fail_third_save), self.assertRaises(OSError):
            batches.create_batch(self.payload(3))
        self.assertEqual(list((self.root / "batches").glob("*/batch.json")), [])
        self.assertEqual(list((self.root / "flows").glob("*/flow.json")), [])

    def test_rejects_manual_mode_and_row_level_recipe_override(self):
        with self.assertRaises(ValueError):
            batches.create_batch(self.payload(1, promptSource="manual"))
        payload = self.payload(1)
        payload["rows"][0]["mode"] = "suffix"
        with self.assertRaises(ValueError):
            batches.create_batch(payload)

    def test_blank_row_cells_inherit_defaults_but_zero_cut_is_validated(self):
        payload = self.payload(1, mode="mixed", temporalMode="prefix", cutSeconds=4)
        source = payload["rows"][0]
        payload["defaults"].update(videoPath=source["videoPath"], referenceImagePath=source["referenceImagePath"],
                                   editInstruction="shared edit direction")
        payload["rows"] = [{"name": "inherits defaults", "videoPath": " \t", "referenceImagePath": "",
                            "cutSeconds": " ", "editInstruction": None}]
        batch = batches.create_batch(payload)
        child = flows.get_flow(batch["rows"][0]["flowId"])
        self.assertEqual(child["inputs"]["videoPath"], source["videoPath"])
        self.assertEqual(child["inputs"]["referenceImagePath"], source["referenceImagePath"])
        self.assertEqual(child["inputs"]["cutSeconds"], 4)
        self.assertEqual(child["inputs"]["editInstruction"], "shared edit direction")
        payload["rows"][0]["cutSeconds"] = 0
        with self.assertRaises(ValueError):
            batches.create_batch(payload)

    def test_row_timing_mode_precedence_and_blank_inheritance(self):
        payload = self.payload(7, mode="prefix", cutMode="percent", replacePercent=25, cutSeconds=4)
        overrides = [{}, {"replacePercent": 40}, {"cutSeconds": 3},
                     {"cutMode": "seconds", "replacePercent": 80, "cutSeconds": 5},
                     {"cutMode": "percent", "replacePercent": 20, "cutSeconds": 6},
                     {"cutMode": " ", "replacePercent": None, "cutSeconds": "\t"},
                     {"replacePercent": 30, "cutSeconds": 2}]
        for row, timing in zip(payload["rows"], overrides):
            row.update(timing)
        batch = batches.create_batch(payload)
        expected = [("percent", 25, None), ("percent", 40, None), ("seconds", None, 3),
                    ("seconds", None, 5), ("percent", 20, None), ("percent", 25, None),
                    ("percent", 30, None)]
        for row, timing in zip(batch["rows"], expected):
            inputs = flows.get_flow(row["flowId"])["inputs"]
            self.assertEqual((inputs["cutMode"], inputs["replacePercent"], inputs["cutSeconds"]), timing)
        # A percentage cell also overrides older defaults that only have seconds.
        legacy = self.payload(1, mode="prefix", cutSeconds=4)
        legacy["rows"][0]["replacePercent"] = 35
        created = batches.create_batch(legacy)
        child = flows.get_flow(created["rows"][0]["flowId"])
        self.assertEqual(child["inputs"]["cutMode"], "percent")
        self.assertEqual(child["inputs"]["replacePercent"], 35)

    def test_shared_percent_resolves_each_video_duration_independently(self):
        payload = self.payload(2, mode="prefix", cutMode="percent", replacePercent=30)
        durations = {Path(row["videoPath"]): duration for row, duration in zip(payload["rows"], (8, 20))}
        batch = batches.create_batch(payload)
        with patch.object(flows, "probe_video", side_effect=lambda path: {"duration": durations[path], "fps": 30}):
            self.run_batch(batch)
        self.assertEqual(batches.get_batch(batch["id"])["completed"], 2)
        cuts = [flows.get_flow(row["flowId"])["inputs"]["cutSeconds"] for row in batch["rows"]]
        self.assertEqual(cuts, [2.4, 6])
        logs = "\n".join(batches.read_logs(batch["id"]))
        self.assertIn("30%", logs)
        self.assertIn("切点 2.4 秒", logs)
        self.assertIn("切点 6 秒", logs)

    def test_invalid_percentage_last_row_leaves_no_partial_batch(self):
        payload = self.payload(2, mode="prefix", cutMode="percent", replacePercent=25)
        payload["rows"][-1]["replacePercent"] = 0
        with self.assertRaisesRegex(ValueError, "第 2 组.*替换比例"):
            batches.create_batch(payload)
        self.assertEqual(list((self.root / "flows").glob("*/flow.json")), [])
        self.assertEqual(list((self.root / "batches").glob("*/batch.json")), [])

    def test_failed_frame_rate_validation_retries_only_export_for_every_group(self):
        batch = self.create(2)

        def fail_export(flow, step, *args):
            if step["id"] == "finish":
                raise RuntimeError("合成视频帧率与原视频不一致：目标 30 fps，实际 29.94 fps。")
            return self.execute(flow, step, *args)

        self.run_batch(batch, execute=fail_export)
        failed = batches.get_batch(batch["id"])
        self.assertEqual(failed["failed"], 2)
        for row in failed["rows"]:
            self.assertEqual([step["status"] for step in flows.get_flow(row["flowId"])["steps"]],
                             ["completed", "completed", "failed"])
        self.calls.clear()
        self.run_batch(batch, retry_failed=True, job_id="fixed-fps-export")
        self.assertEqual(self.calls, [(row["flowId"], "finish") for row in failed["rows"]])
        self.assertEqual(batches.get_batch(batch["id"])["completed"], 2)
        for row in failed["rows"]:
            self.assertEqual([step["attempts"] for step in flows.get_flow(row["flowId"])["steps"]], [1, 1, 2])

    def test_empty_batch_is_rejected_before_creation(self):
        payload = self.payload(1)
        with self.assertRaises(ValueError):
            batches.create_batch({**payload, "rows": []})
        self.assertEqual(list((self.root / "flows").glob("*/flow.json")), [])

    def test_batch_size_follows_materials_without_five_hundred_group_limit(self):
        # Creating recipes must never start model/media execution; guards in
        # setUp keep this a local persistence check even for larger batches.
        batch = self.create(501)
        self.assertEqual(batch["total"], 501)
        self.assertEqual(batch["pending"], 501)
        self.assertEqual(batch["completed"], 0)
        self.assertEqual(len({row["flowId"] for row in batch["rows"]}), 501)
        self.assertEqual(self.calls, [])

    def test_persistent_log_tail_is_bounded_and_download_keeps_complete_history(self):
        batch = self.create(1)
        self.assertEqual(batch["logUrl"], f"/api/video-batches/{batch['id']}/logs")
        self.assertEqual(batch["logDownloadUrl"], f"/api/video-batches/{batch['id']}/logs.txt")
        path = batches.resolve_log(batch["id"])
        lines = [f"第 {index} 行：" + "离线日志" * 30 for index in range(1050)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(batches.read_logs(batch["id"]), lines[-1000:])
        self.assertEqual(batches.resolve_log(batch["id"]).read_text(encoding="utf-8").splitlines(), lines)
        for lookup in (batches.read_logs, batches.resolve_log):
            with self.subTest(lookup=lookup.__name__), self.assertRaises(FileNotFoundError):
                lookup("f" * 16)
        self.assertFalse((self.root / "batches" / ("f" * 16)).exists())


if __name__ == "__main__":
    unittest.main()
