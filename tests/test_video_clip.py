import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if "web_demo" not in sys.modules:
    spec = importlib.util.spec_from_file_location("web_demo", ROOT / "__init__.py")
    package = importlib.util.module_from_spec(spec)
    sys.modules["web_demo"] = package
    spec.loader.exec_module(package)

from web_demo.backend.app.services import video_clip_service as clips

if clips.cv2 is not None:
    import numpy as np


@unittest.skipIf(clips.cv2 is None, "OpenCV is required for video clip integration tests")
class VideoClipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="video_clip_test_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "input"
        self.source.mkdir()
        self.output = self.root / "output"
        self.progress = []

    def make_video(self, name="sample.mp4", colors=None):
        colors = colors if colors is not None else [(0, 0, 240), (0, 240, 0), (240, 0, 0)]
        path = self.source / name
        writer = clips.cv2.VideoWriter(str(path), clips.cv2.VideoWriter_fourcc(*"mp4v"), 12, (64, 48))
        self.assertTrue(writer.isOpened(), "Test video encoder unavailable")
        try:
            for color in colors:
                writer.write(np.full((48, 64, 3), color, dtype=np.uint8))
        finally:
            writer.release()
        capture = clips.cv2.VideoCapture(str(path))
        frames = []
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                frames.append(frame)
        finally:
            capture.release()
        self.assertEqual(len(frames), len(colors))
        return path, frames

    def run_job(self, preset="extract_first_last_frames", **overrides):
        return clips.run_video_clip_job(
            job_id="clip-test",
            payload={"preset": preset, "inputDir": str(self.source), "outputDir": str(self.output), **overrides},
            log=lambda message: None,
            progress=lambda current, total: self.progress.append((current, total)),
        )

    def assert_image(self, path, expected):
        content = Path(path).read_bytes()
        self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
        image = clips.cv2.imdecode(np.frombuffer(content, dtype=np.uint8), clips.cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(image, expected)

    def test_each_extraction_mode_exports_exact_boundary_frames(self):
        video, frames = self.make_video()
        original = video.read_bytes()
        for preset, include_first, include_last in [
            ("extract_first_frame", True, False),
            ("extract_last_frame", False, True),
            ("extract_first_last_frames", True, True),
        ]:
            with self.subTest(preset=preset):
                result = self.run_job(preset)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["failures"], [])
                item = result["items"][0]
                self.assertEqual(item["output_video"], "")
                self.assertEqual(bool(item["first_frame_image"]), include_first)
                self.assertEqual(bool(item["last_frame_image"]), include_last)
                if include_first:
                    self.assert_image(item["first_frame_image"], frames[0])
                if include_last:
                    self.assert_image(item["last_frame_image"], frames[-1])
                outputs = list(Path(result["output_dir"]).rglob("*.png"))
                self.assertEqual(len(outputs), int(include_first) + int(include_last))
                self.assertFalse(list(Path(result["output_dir"]).rglob("*.mp4")))
                self.assertFalse((Path(result["output_dir"]) / "output_frames/trimmed").exists())
                self.assertEqual(video.read_bytes(), original)
                manifest = json.loads((Path(result["output_dir"]) / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["items"], result["items"])
                with Path(result["summary_file"]).open(encoding="utf-8", newline="") as handle:
                    row = next(csv.DictReader(handle))
                self.assertEqual(row["first_frame_image"], item["first_frame_image"])
                self.assertEqual(row["last_frame_image"], item["last_frame_image"])
        self.assertEqual(self.progress[-1], (1, 1))

    def test_single_frame_video_exports_both_images(self):
        _, frames = self.make_video(colors=[(10, 80, 190)])
        item = self.run_job()["items"][0]
        self.assertNotEqual(item["first_frame_image"], item["last_frame_image"])
        self.assert_image(item["first_frame_image"], frames[0])
        self.assert_image(item["last_frame_image"], frames[0])

    def test_unicode_paths_and_same_stem_different_formats(self):
        self.source = self.source / "中文 素材"
        self.source.mkdir()
        self.output = self.output / "中文 输出"
        self.make_video("视频.mp4")
        self.make_video("视频.avi", colors=[(25, 130, 210)])
        result = self.run_job()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["items"]), 2)
        paths = [item[key] for item in result["items"] for key in ("first_frame_image", "last_frame_image")]
        self.assertEqual(len(set(paths)), 4)
        self.assertTrue(all(Path(path).is_file() for path in paths))

    def test_corrupt_video_does_not_stop_batch(self):
        (self.source / "a_bad.mp4").write_bytes(b"invalid video")
        self.make_video("b_good.mp4")
        result = self.run_job()
        self.assertEqual(result["status"], "partial")
        self.assertEqual([item["status"] for item in result["items"]], ["failed", "done"])
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(self.progress, [(0, 2), (1, 2), (2, 2)])

    def test_all_corrupt_videos_fail_job(self):
        (self.source / "bad.mp4").write_bytes(b"invalid video")
        result = self.run_job()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["items"][0]["status"], "failed")

    def test_image_encoding_failure_is_reported(self):
        self.make_video()
        with patch.object(clips.cv2, "imencode", return_value=(False, None)):
            result = self.run_job()
        self.assertEqual(result["status"], "failed")
        self.assertIn("无法编码图片", result["failures"][0]["error"])

    def test_image_write_failure_is_reported(self):
        self.make_video()
        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            result = self.run_job()
        self.assertEqual(result["status"], "failed")
        self.assertIn("disk full", result["failures"][0]["error"])

    def test_unreadable_video_releases_capture(self):
        (self.source / "bad.mp4").touch()
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.read.return_value = (False, None)
        with patch.object(clips.cv2, "VideoCapture", return_value=capture):
            result = self.run_job()
        self.assertEqual(result["status"], "failed")
        self.assertIn("没有成功读取画面", result["failures"][0]["error"])
        capture.release.assert_called_once()

    def test_empty_and_missing_input_are_rejected(self):
        for path, error in [(str(self.source), "没有找到视频"), ("", "请输入输入目录"),
                            (str(self.root / "missing"), "找不到输入目录")]:
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, error):
                self.run_job(inputDir=path)

    def test_frame_presets_are_listed(self):
        presets = [p for p in clips.list_clip_presets() if p["mode"] == "extract_frames"]
        self.assertEqual({p["key"] for p in presets}, {
            "extract_first_frame", "extract_last_frame", "extract_first_last_frames",
        })

    def test_existing_trim_still_exports_video_and_preview(self):
        self.make_video(colors=[(10, 80, 190)] * 12)
        result = self.run_job("first_half_opencv")
        self.assertEqual(result["status"], "completed")
        item = result["items"][0]
        self.assertTrue(Path(item["output_video"]).is_file())
        self.assertTrue(Path(item["preview_image"]).is_file())
        capture = clips.cv2.VideoCapture(item["output_video"])
        try:
            self.assertEqual(int(capture.get(clips.cv2.CAP_PROP_FRAME_COUNT)), 6)
        finally:
            capture.release()

    def test_existing_merge_still_exports_video(self):
        self.make_video()
        result = self.run_job("merge_pairwise", inputDirA=str(self.source), inputDirB=str(self.source))
        self.assertEqual(result["failures"], [])
        capture = clips.cv2.VideoCapture(result["items"][0]["output_video"])
        try:
            self.assertEqual(int(capture.get(clips.cv2.CAP_PROP_FRAME_COUNT)), 6)
        finally:
            capture.release()


if __name__ == "__main__":
    unittest.main()
