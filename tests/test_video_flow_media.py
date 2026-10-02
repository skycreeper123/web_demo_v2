"""Offline timeline checks: all decoding and FFmpeg execution are mocked."""

import importlib.util
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
        self.result_meta = None
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
        if path == self.source:
            return dict(self.source_meta)
        if path.name.endswith(".tmp.mp4"):
            return dict(self.result_meta if self.result_meta is not None else self.source_meta)
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
        self.assertIn("scale=1280:720:force_original_aspect_ratio=decrease", graph)
        self.assertIn("pad=1280:720", graph)
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

    def test_spatial_square_output_reverses_v5_resize_for_landscape_and_portrait_sources(self):
        self.generated_meta = metadata(5, fps=16, width=832, height=832)
        for width, height in ((1920, 1080), (1080, 1920)):
            with self.subTest(source_geometry=(width, height)):
                self.source_meta = metadata(10, width=width, height=height)
                output = self.root / f"spatial_{width}_{height}.mp4"
                media.finalize_spatial(self.generated, self.source, output)
                graph = self.option_values(self.commands[-1], "-filter_complex")[0]
                self.assertIn(f"scale={width}:{height},setsar=1,", graph)
                self.assertNotIn("force_original_aspect_ratio", graph)
                self.assertNotIn(",pad=", graph)
                self.assertIn("setpts=(PTS-STARTPTS)*2,", graph)
                self.assertIn("fps=30", graph)

    def test_filter_and_encoder_preserve_integer_ntsc_and_unusual_source_frame_rates(self):
        # These rates include the actual local a/d/f sample headers. In
        # particular, 29.925 is a real constant rate and must not round to 30.
        cases = ((30, "30", "1/30", "10020"),
                 (30000 / 1001, "30000/1001", "1001/30000", "30000"),
                 (29.925, "1197/40", "40/1197", "10773"),
                 (7525 / 251, "7525/251", "251/7525", "15050"))
        for index, (fps, rate, time_base, timescale) in enumerate(cases):
            with self.subTest(source_fps=fps):
                self.source_meta = metadata(300 / fps, fps=fps)
                media.finalize_spatial(self.generated, self.source, self.root / f"rate_{index}.mp4")
                arguments = self.commands[-1]
                graph = self.option_values(arguments, "-filter_complex")[0]
                self.assertIn(f"fps={rate},", graph)
                self.assertEqual(self.option_values(arguments, "-r:v"), [rate])
                self.assertEqual(self.option_values(arguments, "-fps_mode:v"), ["cfr"])
                self.assertEqual(self.option_values(arguments, "-enc_time_base:v"), [time_base])
                self.assertEqual(self.option_values(arguments, "-video_track_timescale"), [timescale])

    def test_small_average_fps_variance_with_at_most_one_frame_difference_is_accepted(self):
        # The first case differs by more than the old 0.1% FPS threshold but
        # stays within half a frame on the source timeline. The second lands
        # exactly at the new one-frame cadence/count boundary.
        cases = ((metadata(10), {**metadata(300 / 29.95, fps=29.95), "frames": 300}),
                 (metadata(4), metadata(4, fps=29.75)))
        for index, (source_meta, result_meta) in enumerate(cases):
            with self.subTest(case=index):
                self.source_meta, self.result_meta = source_meta, result_meta
                output = self.root / f"accepted_fps_{index}.mp4"
                result = media.finalize_spatial(self.generated, self.source, output)
                self.assertEqual(result["fps"], result_meta["fps"])
                self.assertTrue(output.is_file())

    def test_real_fps_mismatch_is_rejected_with_diagnostic_metadata(self):
        for actual_fps in (16, 25):
            with self.subTest(actual_fps=actual_fps):
                self.result_meta = metadata(10, fps=actual_fps)
                output = self.root / f"wrong_fps_{actual_fps}.mp4"
                with self.assertRaises(RuntimeError) as raised:
                    media.finalize_spatial(self.generated, self.source, output)
                message = str(raised.exception)
                self.assertIn("帧率", message)
                for value in ("30", str(actual_fps), "300", str(actual_fps * 10), "10"):
                    self.assertIn(value, message)
                self.assertFalse(output.exists())

    def test_long_clip_drift_over_one_frame_and_excess_frame_count_are_rejected(self):
        # 60 s at 29.965 reported FPS remains within the independent 75 ms
        # duration tolerance, yet accumulates > 2 frames of cadence drift.
        cases = ((metadata(60), {**metadata(1800 / 29.965, fps=29.965), "frames": 1800}),
                 (metadata(300 / 29.925, fps=29.925), metadata(302 / 30, fps=30)))
        for index, (source_meta, result_meta) in enumerate(cases):
            with self.subTest(case=index):
                self.source_meta, self.result_meta = source_meta, result_meta
                with self.assertRaisesRegex(RuntimeError, "帧率"):
                    media.finalize_spatial(self.generated, self.source, self.root / f"drift_{index}.mp4")

    def test_duration_and_geometry_mismatches_still_fail_when_reported_fps_matches(self):
        cases = ((metadata(9.5), "时长"), (metadata(10, width=640, height=360), "尺寸"))
        for index, (result_meta, error) in enumerate(cases):
            with self.subTest(error=error):
                self.result_meta = result_meta
                output = self.root / f"bad_output_{index}.mp4"
                with self.assertRaisesRegex(RuntimeError, error):
                    media.finalize_spatial(self.generated, self.source, output)
                self.assertFalse(output.exists())

    def test_invalid_cut_fails_before_creating_outputs_or_invoking_ffmpeg(self):
        for direction in ("prefix", "suffix"):
            for cut in (-1, 0, 10, 11, float("nan"), float("inf"), 0.01, 9.99):
                with self.subTest(direction=direction, cut=cut), self.assertRaises(ValueError):
                    media.prepare_temporal(self.source, self.root / "prepare", direction, cut)
        self.mock_execute.assert_not_called()
        self.assertFalse((self.root / "prepare").exists())


class FFmpegFrameRateCompatibilityTests(unittest.TestCase):
    def test_unsupported_fps_mode_retries_with_legacy_cfr_before_encoding(self):
        arguments = ["-i", "generated.mp4", "-r:v", "30000/1001", "-fps_mode:v", "cfr", "final.mp4"]
        with patch.object(media, "_get_ffmpeg_executable", return_value="ffmpeg"), \
             patch.object(media.subprocess, "run", side_effect=[
                 SimpleNamespace(returncode=1, stderr="Unrecognized option 'fps_mode:v'.\nError splitting the argument list: Option not found"),
                 SimpleNamespace(returncode=0, stderr=""),
             ]) as execute:
            media._run_ffmpeg(arguments, duration=10, action="离线检查")
        self.assertEqual(execute.call_count, 2)
        original = execute.call_args_list[0].args[0]
        fallback = execute.call_args_list[1].args[0]
        self.assertEqual(fallback, ["-vsync" if value == "-fps_mode:v" else value for value in original])
        self.assertEqual(arguments[-3:], ["-fps_mode:v", "cfr", "final.mp4"])

    def test_other_encoding_errors_are_not_retried_or_hidden(self):
        with patch.object(media, "_get_ffmpeg_executable", return_value="ffmpeg"), \
             patch.object(media.subprocess, "run", return_value=SimpleNamespace(returncode=1, stderr="Encoder failed")) as execute:
            with self.assertRaisesRegex(RuntimeError, "Encoder failed"):
                media._run_ffmpeg(["-fps_mode:v", "cfr", "final.mp4"], duration=10, action="离线检查")
        execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
