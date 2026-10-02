"""Offline timeline checks: all decoding and FFmpeg execution are mocked."""

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

from web_demo.backend.app.services import video_flow_media as media


def metadata(duration, fps=30, width=1280, height=720):
    return {"duration": duration, "fps": fps, "width": width, "height": height,
            "frames": round(duration * fps)}


class VideoFlowMediaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="video_flow_media_mock_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source.mp4"
        self.retained = self.root / "retained.mp4"
        self.generated = self.root / "generated.mp4"
        for path in (self.source, self.retained, self.generated):
            path.write_bytes(b"placeholder; never decoded")
        self.source_meta = metadata(10)
        self.retained_meta = metadata(6)
        self.generated_meta = metadata(5, fps=16, width=832, height=480)
        self.commands = []
        # Guard against an accidental future escape from the mocked boundary.
        for name in ("subprocess.run", "_require_cv2"):
            guard = patch.object(media, "_require_cv2", side_effect=AssertionError("OpenCV must not run")) \
                if name == "_require_cv2" else patch("subprocess.run", side_effect=AssertionError("No real subprocesses"))
            guard.start()
            self.addCleanup(guard.stop)
        probe = patch.object(media, "probe_video", side_effect=self.probe)
        execute = patch.object(media, "_run_ffmpeg", side_effect=self.render)
        self.mock_probe = probe.start()
        self.mock_execute = execute.start()
        self.addCleanup(probe.stop)
        self.addCleanup(execute.stop)

    def probe(self, path):
        path = Path(path).resolve()
        if path == self.retained:
            return dict(self.retained_meta)
        if path == self.generated:
            return dict(self.generated_meta)
        if path == self.source or path.name.endswith(".tmp.mp4"):
            return dict(self.source_meta)
        raise AssertionError(f"Unexpected probe: {path}")

    def render(self, arguments, **_kwargs):
        self.commands.append(list(arguments))
        Path(arguments[-1]).write_bytes(b"mock output")

    def assemble(self, direction, *, keep_audio=True):
        self.retained_meta = metadata(6 if direction == "prefix" else 4)
        return media.assemble_video(
            self.retained, self.generated, self.source, self.root / "final.mp4",
            direction=direction, cut_seconds=4, keep_audio=keep_audio,
        )

    @staticmethod
    def option_values(arguments, option):
        return [arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == option]

    def test_prefix_puts_generated_before_retained_and_preserves_source_timing(self):
        result = self.assemble("prefix")
        arguments = self.commands[0]
        graph = self.option_values(arguments, "-filter_complex")[0]
        self.assertIn("[generated][retained]concat=", graph)
        self.assertIn("[1:v:0]setpts=(PTS-STARTPTS)*0.8,", graph)
        self.assertIn("fps=30", graph)
        self.assertNotIn("fps=16", graph)
        self.assertIn("scale=1280:720:force_original_aspect_ratio=decrease", graph)
        self.assertIn("pad=1280:720", graph)
        self.assertEqual(self.option_values(arguments, "-t"), ["10"])
        self.assertEqual((result["duration"], result["fps"], result["replacement_duration"]), (10, 30, 4))
        self.assertTrue(Path(result["path"]).is_file())

    def test_suffix_puts_retained_before_generated_and_uses_remaining_duration(self):
        result = self.assemble("suffix")
        graph = self.option_values(self.commands[0], "-filter_complex")[0]
        self.assertIn("[retained][generated]concat=", graph)
        self.assertIn("[1:v:0]setpts=(PTS-STARTPTS)*1.2,", graph)
        self.assertEqual(result["replacement_duration"], 6)
        self.assertEqual(result["duration"], 10)

    def test_default_audio_mapping_is_optional_and_uses_original_source(self):
        self.assemble("prefix")
        arguments = self.commands[0]
        self.assertEqual(self.option_values(arguments, "-i"),
                         [str(self.retained), str(self.generated), str(self.source)])
        self.assertEqual(self.option_values(arguments, "-map"), ["[video]", "2:a?"])
        self.assertNotIn("-an", arguments)

    def test_audio_can_be_explicitly_disabled(self):
        result = self.assemble("suffix", keep_audio=False)
        arguments = self.commands[0]
        self.assertEqual(self.option_values(arguments, "-map"), ["[video]"])
        self.assertIn("-an", arguments)
        self.assertNotIn("-c:a", arguments)
        self.assertFalse(result["keep_audio"])

    def test_spatial_finalize_restores_source_timeline_and_optional_audio(self):
        result = media.finalize_spatial(self.generated, self.source, self.root / "spatial_final.mp4")
        arguments = self.commands[0]
        graph = self.option_values(arguments, "-filter_complex")[0]
        self.assertIn("setpts=(PTS-STARTPTS)*2,", graph)
        self.assertIn("fps=30", graph)
        self.assertEqual(self.option_values(arguments, "-map"), ["[video]", "1:a?"])
        self.assertEqual(result["duration"], 10)

    def test_invalid_cut_fails_before_creating_outputs_or_invoking_ffmpeg(self):
        for direction in ("prefix", "suffix"):
            for cut in (-1, 0, 10, 11, float("nan"), float("inf"), 0.01, 9.99):
                with self.subTest(direction=direction, cut=cut), self.assertRaises(ValueError):
                    media.prepare_temporal(self.source, self.root / "prepare", direction, cut)
        self.mock_execute.assert_not_called()
        self.assertFalse((self.root / "prepare").exists())


if __name__ == "__main__":
    unittest.main()
