"""HD sizing and timeline coverage independent of ComfyUI or FFmpeg."""

import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services.video_output_profile import (
    generation_dimensions, generation_frames, output_video_meta,
)


class OutputProfileTests(unittest.TestCase):
    def test_hd_profile_preserves_orientation_and_does_not_mutate_source(self):
        cases = ((1280, 720, 1920, 1080, 1920, 1088),
                 (720, 1280, 1080, 1920, 1088, 1920),
                 (512, 512, 1080, 1080, 1088, 1088),
                 (640, 480, 1440, 1080, 1440, 1088),
                 (3840, 2160, 1920, 1080, 1920, 1088))
        for width, height, final_width, final_height, model_width, model_height in cases:
            with self.subTest(source=(width, height)):
                original = dict(width=width, height=height, fps=24, duration=4.25, frames=102)
                actual = output_video_meta(original)
                self.assertEqual((actual["width"], actual["height"], actual["fps"]), (final_width, final_height, 30))
                self.assertEqual(actual["duration"], 4.25)
                self.assertEqual(generation_dimensions(original), (model_width, model_height))
                self.assertEqual(original, dict(width=width, height=height, fps=24, duration=4.25, frames=102))

    def test_frame_count_covers_duration_without_more_than_one_model_block_extra(self):
        for duration in (0.04, 1, 4, 5, 6, 10.125):
            with self.subTest(duration=duration):
                frames = generation_frames(duration)
                self.assertEqual(frames % 4, 1)
                self.assertGreaterEqual(frames / 30, duration)
                self.assertLess(frames / 30 - duration, 4 / 30 + 1e-9)
        self.assertEqual(generation_frames(4), 121)

    def test_invalid_generation_duration_is_rejected(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(duration=value), self.assertRaises(ValueError):
                generation_frames(value)


if __name__ == "__main__":
    unittest.main()
