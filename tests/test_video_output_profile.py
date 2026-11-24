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
    generation_dimensions, generation_frames, output_video_meta, person_replacement_dimensions, validate_profile,
)


class OutputProfileTests(unittest.TestCase):
    def test_native_uses_target_dimensions_and_rejects_independent_generation_overrides(self):
        for size, expected in ((480, (864,480)), (1080,(1920,1088))):
            for fps in (16,24,60):
                profile=validate_profile({'generationPolicy':'native','outputShortSide':size,'outputFps':fps})
                self.assertEqual(person_replacement_dimensions({'width':1280,'height':720},profile),expected)
        for override in ({'generationLongSide':512}, {'generationFps':16}, {'outputFps':120}):
            with self.assertRaises(ValueError):
                validate_profile({'generationPolicy':'native','outputFps':60,**override})

    def test_requested_profiles_cover_the_document_matrix_and_preserve_source(self):
        for size in (480, 1080):
            for fps in (16, 24, 60):
                meta = output_video_meta(dict(width=720, height=1280, duration=10), {"outputShortSide": size, "outputFps": fps})
                self.assertEqual(meta["width"], size)
                self.assertEqual(meta["fps"], fps)
                self.assertEqual(meta["frames"], fps * 10)
                self.assertGreaterEqual(generation_frames(2, fps)/fps, 2)
        for key, value in (("outputFps", 0), ("outputFps", 24.5), ("generationLongSide", 9000),
                           ("expectedSourceSeconds", float("nan")), ("outputShortSide", True)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_profile({key: value})

    def test_person_generation_is_bounded_and_aligned_independent_of_export(self):
        for width, height, expected in ((1280, 720, (512, 288)), (720, 1280, (288, 512)),
                                         (1000, 1000, (512, 512)), (10, 1000, (64, 512))):
            with self.subTest(source=(width, height)):
                self.assertEqual(person_replacement_dimensions(dict(width=width, height=height)), expected)
        with self.assertRaises(ValueError):
            person_replacement_dimensions(dict(width=0, height=720))

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
