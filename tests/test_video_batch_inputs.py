"""Offline material matching and Prompt handoff checks; no generation calls."""

import base64
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

from web_demo.backend.app.services import video_batch_inputs as inputs
from web_demo.backend.app.services import video_batch_service as batches
from web_demo.backend.app.services import video_flow_service as flows
from web_demo.backend.app.services.comfyui_comm import _build_row_payload, _load_csv_rows


class VideoBatchInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="batch_inputs_offline_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.patch(flows, "FLOW_ROOT", self.root / "flows")
        self.patch(batches, "BATCH_ROOT", self.root / "batches")
        for name in ("OpenAICompatibleClient", "run_comfy_job", "prepare_temporal",
                     "assemble_video", "finalize_spatial", "probe_video"):
            self.patch(flows, name, side_effect=AssertionError(f"Unexpected external operation: {name}"))
        network = patch("urllib.request.urlopen", side_effect=AssertionError("No network in offline tests"))
        network.start()
        self.addCleanup(network.stop)

    def patch(self, target, name, *args, **kwargs):
        patcher = patch.object(target, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def file(self, role, name):
        path = self.root / role / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"offline placeholder: {role}/{name}".encode())
        return str(path)

    def metadata(self, role, names, *, paths=False):
        return [{"id": f"{role}:{index}", "name": Path(name).name,
                 "relativePath": name, "path": self.file(role, name) if paths else ""}
                for index, name in enumerate(names, 1)]

    def scan(self, mode="spatial", *, temporal="prefix", defaults=None, paths=False, **roles):
        return inputs.match_batch_inputs({
            "inputMode": "files",
            "defaults": {"mode": mode, "temporalMode": temporal, "cutSeconds": 2,
                         "promptSource": "ai", **(defaults or {})},
            "files": {role: self.metadata(role, names, paths=paths) for role, names in roles.items()},
        })

    def test_recursive_server_directories_match_main_and_supplemental_images(self):
        video_a = self.file("videos", "nested/样片 A.mp4")
        video_b = self.file("videos", "other/second.MOV")
        main = self.file("references", "other/样片 A.png")
        alt1 = self.file("references", "more/样片 A_1.jpg")
        alt2 = self.file("references", "more/样片 A_2.webp")
        self.file("references", "second.jpeg")
        self.file("videos", "ignore.txt")
        result = inputs.match_batch_inputs({
            "inputMode": "directories", "defaults": {"mode": "spatial"},
            "directories": {role: str(self.root / role) for role in ("videos", "references")},
        })
        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["ready"], 2)
        self.assertEqual(result["summary"]["needsUpload"], 0)
        by_video = {row["videoPath"]: row for row in result["rows"]}
        self.assertEqual(set(by_video), {video_a, video_b})
        self.assertEqual(by_video[video_a]["referenceImagePath"], main)
        self.assertEqual(by_video[video_a]["referenceAlt1Path"], alt1)
        self.assertEqual(by_video[video_a]["referenceAlt2Path"], alt2)
        self.assertTrue(all(Path(row["videoPath"]).is_absolute() for row in result["rows"]))
        self.assertEqual(list((self.root / "flows").glob("*/flow.json")), [])

    def test_browser_metadata_preserves_role_ids_and_requires_upload(self):
        result = self.scan(videos=["folder/clip.mp4"], references=["refs/clip.png", "refs/clip_1.jpg"])
        match = result["matches"][0]
        self.assertTrue(match["canCreate"])
        self.assertTrue(match["requiresUpload"])
        self.assertEqual(result["summary"]["needsUpload"], 1)
        self.assertEqual(match["assets"]["videoPath"]["id"], "videos:1")
        self.assertEqual(match["assets"]["referenceImagePath"]["relativePath"], "refs/clip.png")
        self.assertEqual(match["assets"]["referenceAlt1Path"]["id"], "references:2")
        self.assertEqual(match["row"]["videoPath"], "")
        self.assertEqual(match["row"]["referenceImagePath"], "")
        self.assertIn("referenceImagePath", result["requiredRoles"])

    def test_metadata_paths_are_not_replaced_with_browser_names(self):
        result = inputs.match_batch_inputs({
            "inputMode": "files", "defaults": {"mode": "suffix", "cutSeconds": 2},
            "files": {"videos": [{"id": "v", "name": "a.mp4", "path": "/srv/video/nested/a.mp4"}],
                      "references": [{"id": "r", "name": "a.png", "path": "/srv/refs/a.png"}]},
        })
        self.assertFalse(result["matches"][0]["requiresUpload"])
        self.assertEqual(result["rows"][0]["videoPath"], "/srv/video/nested/a.mp4")
        self.assertEqual(result["rows"][0]["endImagePath"], "/srv/refs/a.png")

    def test_duplicate_ids_across_roles_are_rejected_and_missing_ids_are_safe(self):
        files = {"videos": [{"id": "same", "name": "a.mp4"}],
                 "references": [{"id": "same", "name": "a.png"}]}
        payload = {"inputMode": "files", "defaults": {"mode": "spatial"}, "files": files}
        with self.assertRaises(ValueError):
            inputs.match_batch_inputs(payload)
        for assets in files.values():
            assets[0].pop("id")
        match = inputs.match_batch_inputs(payload)["matches"][0]
        ids = [asset["id"] for asset in match["assets"].values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(ids))

    def test_ambiguous_main_or_supplemental_names_block_instead_of_choosing(self):
        for refs in (["a.png", "a.jpg"], ["a.png", "a_1.jpg", "a_1.webp"]):
            with self.subTest(refs=refs):
                result = self.scan(videos=["a.mp4"], references=refs)
                self.assertEqual(result["matches"][0]["status"], "naming_conflict")
                self.assertFalse(result["matches"][0]["canCreate"])
                self.assertEqual(result["rows"], [])
                self.assertEqual(result["summary"]["blocked"], 1)

        duplicate_videos = self.scan(videos=["one/a.mp4", "two/A.mov"], references=["a.png"])
        self.assertEqual(duplicate_videos["summary"]["blocked"], 2)
        self.assertTrue(all(match["status"] == "naming_conflict" for match in duplicate_videos["matches"]))

    def test_main_reference_missing_and_unsupported_formats_do_not_create_groups(self):
        for refs in (["a_1.png", "a_2.jpg"], ["a.gif"], []):
            with self.subTest(refs=refs):
                result = self.scan(videos=["a.mp4", "ignored.txt"], references=refs)
                self.assertEqual(result["summary"]["total"], 1)
                self.assertEqual(result["matches"][0]["status"], "missing_input")
                self.assertEqual(result["rows"], [])

    def test_mode_requirements_assign_references_to_the_correct_role(self):
        cases = [("spatial", "prefix", "referenceImagePath"),
                 ("prefix", "prefix", "startImagePath"),
                 ("suffix", "prefix", "endImagePath"),
                 ("mixed", "prefix", "referenceImagePath")]
        for mode, temporal, field in cases:
            with self.subTest(mode=mode):
                result = self.scan(mode, temporal=temporal, paths=True,
                                   videos=["a.mp4"], references=["a.png", "a_1.png", "a_2.png"])
                self.assertTrue(result["matches"][0]["canCreate"])
                row = result["rows"][0]
                self.assertEqual(row[field], str(self.root / "references" / "a.png"))
                if mode in {"prefix", "suffix"}:
                    self.assertFalse(row.get("referenceAlt1Path"))
                    self.assertFalse(row.get("referenceAlt2Path"))
                if mode == "mixed":
                    self.assertFalse(row.get("startImagePath"))
        mixed_suffix = self.scan("mixed", temporal="suffix", videos=["a.mp4"], references=["a.png"])
        self.assertEqual(mixed_suffix["summary"]["blocked"], 0)
        self.assertNotIn("endImagePath", mixed_suffix["requiredRoles"])
        self.assertNotIn("endImagePath", mixed_suffix["rows"][0])

    def test_explicit_start_and_end_roles_take_precedence_over_temporal_references(self):
        for mode, role, field in (("prefix", "startImages", "startImagePath"),
                                  ("suffix", "endImages", "endImagePath")):
            with self.subTest(mode=mode):
                result = self.scan(mode, paths=True, videos=["a.mp4"], references=["a.png"], **{role: ["a.jpg"]})
                self.assertEqual(result["rows"][0][field], str(self.root / role / "a.jpg"))
                conflict = self.scan(mode, videos=["a.mp4"], references=["a.png"], **{role: ["a.jpg", "a.webp"]})
                self.assertEqual(conflict["summary"]["blocked"], 1)
        mixed = self.scan("mixed", paths=True, videos=["a.mp4"], references=["a.png"], startImages=["a.jpg"])
        self.assertEqual(mixed["rows"][0]["referenceImagePath"], str(self.root / "references" / "a.png"))
        self.assertEqual(mixed["rows"][0]["startImagePath"], str(self.root / "startImages" / "a.jpg"))

    def test_prefix_without_a_new_start_uses_qwen_but_alt_refs_are_not_start_or_end(self):
        for refs in ([], ["a_1.png", "a_2.png"]):
            with self.subTest(refs=refs):
                result = self.scan("prefix", paths=True, videos=["a.mp4"], references=refs)
                self.assertTrue(result["matches"][0]["canCreate"])
                self.assertFalse(result["rows"][0].get("startImagePath"))
                flow = flows.build_flow({"mode": "prefix", "cutSeconds": 2, **result["rows"][0]})
                self.assertIn("first_render", [step["id"] for step in flow["steps"]])
        suffix = self.scan("suffix", videos=["a.mp4"], references=["a_1.png", "a_2.png"])
        self.assertEqual(suffix["summary"]["blocked"], 0)
        self.assertNotIn("endImagePath", suffix["matches"][0]["assets"])

    def test_suffix_video_only_folders_create_batch_without_target_images(self):
        defaults = {"mode": "suffix", "promptSource": "ai", "cutMode": "percent", "replacePercent": 30}
        videos = self.metadata("videos", ["a.mp4", "b.mp4"], paths=True)
        for mode in ("files", "directories"):
            with self.subTest(input_mode=mode):
                result = inputs.match_batch_inputs({
                    "defaults": defaults, "inputMode": mode, "files": {"videos": videos},
                    "directories": {"videos": str(self.root / "videos")},
                })
                self.assertEqual(result["summary"]["ready"], 2)
                self.assertEqual(result["requiredRoles"], ["videoPath"])
                batch = batches.create_batch({"defaults": defaults, "rows": result["rows"]})
                for row in batch["rows"]:
                    flow = flows.get_flow(row["flowId"])
                    self.assertEqual(flow["inputs"]["endImagePath"], "")
                    self.assertNotIn("target_end", flow["artifacts"])
                    motion = next(step for step in flow["steps"] if step["id"] == "motion_prompt")
                    self.assertEqual(motion["settings"]["media"], ["boundary_frame", "target_end"])

    def test_missing_per_video_tail_falls_back_to_auto_without_losing_other_manual_tails(self):
        for mode in ("suffix", "mixed"):
            with self.subTest(mode=mode):
                defaults = {"mode": mode, "temporalMode": "suffix", "promptSource": "ai", "cutSeconds": 2}
                result = self.scan(mode, temporal="suffix", paths=True, videos=["a.mp4", "b.mp4"],
                                   references=["a.png", "b.png"] if mode == "mixed" else [],
                                   endImages=["a.jpg"])
                self.assertEqual(result["summary"]["ready"], 2)
                self.assertEqual(result["rows"][0]["endImagePath"], str(self.root / "endImages" / "a.jpg"))
                self.assertNotIn("endImagePath", result["rows"][1])
                batch = batches.create_batch({"defaults": defaults, "rows": result["rows"]})
                manual, automatic = [flows.get_flow(row["flowId"]) for row in batch["rows"]]
                self.assertEqual(manual["artifacts"]["target_end"]["path"], str(self.root / "endImages" / "a.jpg"))
                self.assertNotIn("target_end", automatic["artifacts"])

    def test_mixed_suffix_keeps_spatial_refs_separate_and_can_inherit_default_end(self):
        end = self.file("defaults", "shared-end.png")
        result = self.scan("mixed", temporal="suffix", paths=True, defaults={"endImagePath": end},
                           videos=["a.mp4"], references=["a.png", "a_1.png"])
        row = result["rows"][0]
        self.assertEqual(row["endImagePath"], end)
        self.assertEqual(row["referenceImagePath"], str(self.root / "references" / "a.png"))
        self.assertEqual(row["referenceAlt1Path"], str(self.root / "references" / "a_1.png"))
        explicit = self.scan("mixed", temporal="suffix", paths=True, defaults={"endImagePath": end},
                             videos=["a.mp4"], references=["a.png"], endImages=["a.webp"])
        self.assertEqual(explicit["rows"][0]["endImagePath"], str(self.root / "endImages" / "a.webp"))

    def test_shared_defaults_and_selected_rows_create_only_requested_material_groups(self):
        reference = self.file("defaults", "shared-ref.png")
        result = self.scan(paths=True, defaults={"referenceImagePath": reference}, videos=["a.mp4", "b.mp4"])
        self.assertEqual(result["summary"]["ready"], 2)
        selected = result["rows"][1]
        batch = batches.create_batch({"defaults": {"mode": "spatial", "promptSource": "ai",
                                                   "editInstruction": "shared direction"}, "rows": [selected]})
        self.assertEqual(batch["total"], 1)
        child = flows.get_flow(batch["rows"][0]["flowId"])
        self.assertEqual(child["inputs"]["videoPath"], selected["videoPath"])
        self.assertEqual(child["inputs"]["referenceImagePath"], reference)
        self.assertEqual(child["inputs"]["editInstruction"], "shared direction")

    def test_scan_previews_ready_and_blocked_rows_without_creating_or_running_anything(self):
        result = self.scan(videos=["ready.mp4", "missing.mp4"], references=["ready.png"])
        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["ready"], 1)
        self.assertEqual(result["summary"]["blocked"], 1)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(list((self.root / "flows").glob("*/flow.json")), [])
        self.assertEqual(list((self.root / "batches").glob("*/batch.json")), [])

    def test_no_supported_videos_and_invalid_supplied_directories_are_errors(self):
        for videos in ([], ["unsupported.txt"]):
            with self.subTest(videos=videos), self.assertRaises(ValueError):
                self.scan("prefix", videos=videos)
        self.file("videos", "a.mp4")
        directories = {"videos": str(self.root / "videos"), "references": str(self.root / "not-present")}
        with self.assertRaises((ValueError, FileNotFoundError)):
            inputs.match_batch_inputs({"inputMode": "directories", "defaults": {"mode": "prefix"},
                                       "directories": directories})

    def test_supplemental_refs_reach_prompt_in_order_without_overwriting_comfy_main_image(self):
        video = self.file("videos", "a.mp4")
        main, alt1, alt2 = [self.file("references", name) for name in ("a.png", "a_1.png", "a_2.png")]
        flow = flows.build_flow({"mode": "spatial", "videoPath": video, "referenceImagePath": main,
                                 "referenceAlt1Path": alt1, "referenceAlt2Path": alt2, "promptSource": "ai"})
        step = next(step for step in flow["steps"] if step["id"] == "spatial_prompt")
        factory = self.patch(flows, "OpenAICompatibleClient")
        factory.return_value.chat_with_media.return_value = SimpleNamespace(
            text=json.dumps({"positive_prompt": "Use the primary reference", "negative_prompt": "flicker"}))
        self.patch(flows, "load_api_config", return_value={"use_mock": False, "api_key": "offline-only",
                                                           "base_url": "https://unused.invalid", "model": "fake"})
        self.patch(flows, "load_prompt_config", return_value={"system_prompt": "saved system", "user_text": "saved user"})
        directory = self.root / "prompt"
        directory.mkdir()
        flows._run_prompt(flow, step, directory, lambda _: None)
        system, user, media = factory.return_value.chat_with_media.call_args.args
        self.assertEqual(system, "saved system")
        self.assertTrue(user.startswith("saved user"))
        self.assertEqual([item["kind"] for item in media], ["video", "image", "image", "image"])
        self.assertEqual([base64.b64decode(item["url"].split(",", 1)[1]) for item in media],
                         [Path(path).read_bytes() for path in (video, main, alt1, alt2)])
        rows = _load_csv_rows(str(directory / "prompts.csv"))
        self.assertEqual(len(rows), 1)
        bound = _build_row_payload(parent_job_id="offline", row_index=1, row=rows[0], payload={}, template_payload={})
        self.assertEqual(bound["imagePath"], main)
        self.assertEqual(bound["videoPath"], video)
        self.assertEqual(bound["positivePrompt"], "Use the primary reference")


if __name__ == "__main__":
    unittest.main()
