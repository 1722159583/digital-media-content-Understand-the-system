import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from source_code.ffmpeg_service import FFmpegError, _normalized_segments, create_rough_cut


class FFmpegServiceTestCase(unittest.TestCase):
    def test_fixed_duration_segments_are_clamped_to_video(self):
        segments = _normalized_segments(
            [
                {"segment_id": 1, "start_time": 0.2, "end_time": 0.8},
                {"segment_id": 2, "start_time": 9.5, "end_time": 10.0},
            ],
            clip_duration=4,
            video_duration=10,
        )
        self.assertEqual(segments[0]["start_time"], 0)
        self.assertEqual(segments[0]["duration"], 4)
        self.assertEqual(segments[1]["start_time"], 6)
        self.assertEqual(segments[1]["end_time"], 10)

    def test_rejects_invalid_segments_and_duration(self):
        with self.assertRaises(FFmpegError):
            _normalized_segments([], 6, 10)
        with self.assertRaises(FFmpegError):
            _normalized_segments([{"start_time": 1, "end_time": 2}], 100, 10)

    @patch("source_code.ffmpeg_service.find_ffmpeg", return_value=None)
    def test_reports_missing_ffmpeg(self, _find_ffmpeg):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mp4"
            source.write_bytes(b"video")
            with self.assertRaisesRegex(FFmpegError, "未找到 FFmpeg"):
                create_rough_cut(
                    source,
                    Path(directory) / "out.mp4",
                    [{"start_time": 0, "end_time": 1}],
                )


if __name__ == "__main__":
    unittest.main()
