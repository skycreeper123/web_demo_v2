import json
from pathlib import Path
import unittest


WORKFLOW_DIR = Path(__file__).resolve().parents[1] / "workflow"


def load_workflow(pattern):
    return json.loads(next(WORKFLOW_DIR.glob(pattern)).read_text(encoding="utf-8"))


class VideoWorkflowDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.workflows = {
            "spatial": load_workflow("*V5*.json"),
            "scail": load_workflow("*V6.1*.json"),
            "temporal": load_workflow("wan2.2*.json"),
        }

    def test_all_video_outputs_are_exact_1080p_at_30fps(self):
        for name, workflow in self.workflows.items():
            outputs = [node for node in workflow.values()
                       if node["class_type"] == "VHS_VideoCombine"]
            self.assertTrue(outputs, name)
            for output in outputs:
                with self.subTest(workflow=name, title=output.get("_meta")):
                    frame_rate = output["inputs"]["frame_rate"]
                    if isinstance(frame_rate, list):
                        # VHS_VideoInfo output 5 is the loaded (resampled) FPS.
                        self.assertEqual(frame_rate[1], 5)
                        info = workflow[frame_rate[0]]
                        self.assertEqual(info["class_type"], "VHS_VideoInfo")
                        loader = workflow[info["inputs"]["video_info"][0]]
                        frame_rate = loader["inputs"]["force_rate"]
                    self.assertEqual(frame_rate, 30)
                    resize = workflow[output["inputs"]["images"][0]]
                    self.assertEqual(resize["class_type"], "ImageResizeKJv2")
                    self.assertEqual(resize["inputs"]["width"], 1920)
                    self.assertEqual(resize["inputs"]["height"], 1080)
                    self.assertEqual(resize["inputs"]["divisible_by"], 2)
                    self.assertIn(resize["inputs"]["keep_proportion"], ("stretch", "pad"))

    def test_generation_is_high_resolution_and_model_aligned(self):
        spatial = self.workflows["spatial"]["1420"]["inputs"]
        scail = self.workflows["scail"]["205"]["inputs"]
        temporal = self.workflows["temporal"]["223"]["inputs"]
        for name, node in (("spatial", spatial), ("scail", scail), ("temporal", temporal)):
            with self.subTest(workflow=name):
                dimensions = []
                for key in ("width", "height"):
                    value = node[key]
                    if isinstance(value, list):
                        value = self.workflows[name][value[0]]["inputs"]["value"]
                    dimensions.append(value)
                    self.assertEqual(value % node["divisible_by"], 0)
                self.assertEqual(dimensions, [1920, 1088])
                self.assertNotEqual(node["keep_proportion"], "resize")

    def test_frame_counts_preserve_clip_duration(self):
        for name in ("spatial", "scail"):
            for node in self.workflows[name].values():
                if node["class_type"] == "VHS_LoadVideo":
                    self.assertEqual(node["inputs"]["force_rate"], 30)
                    self.assertEqual(node["inputs"]["frame_load_cap"], 0)
                    self.assertEqual(node["inputs"]["select_every_nth"], 1)
        frames = self.workflows["temporal"]["162"]["inputs"]["value"]
        self.assertEqual((frames - 1) % 4, 0)
        self.assertAlmostEqual(frames / 30, 4, delta=1 / 30 + 1e-6)

    def test_links_remain_valid_and_final_resize_follows_generation(self):
        for name, workflow in self.workflows.items():
            for node_id, node in workflow.items():
                for value in node["inputs"].values():
                    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                        self.assertIn(str(value[0]), workflow, (name, node_id, value))
        self.assertEqual(self.workflows["spatial"]["1440"]["inputs"]["image"], ["1438", 0])
        self.assertEqual(self.workflows["scail"]["1113"]["inputs"]["image"], ["42", 0])
        self.assertEqual(self.workflows["temporal"]["246"]["inputs"]["image"], ["143", 0])


if __name__ == "__main__":
    unittest.main()
