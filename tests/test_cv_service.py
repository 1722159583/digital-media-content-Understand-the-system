import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from source_code.cv_service import (
    IoUTracker,
    InvalidMediaError,
    ModelNotFoundError,
    calc_excitement_score,
    calculate_visual_scores,
    detect_frame,
    detect_frames,
    extract_highlights,
    load_model,
    sample_frames,
    stream_sampled_frames,
)


class FakeBox:
    def __init__(self, class_id, confidence, bbox):
        self.cls = np.array([class_id])
        self.conf = np.array([confidence])
        self.xyxy = np.array([bbox])


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeModel:
    names = {0: "penta_kill", 1: "triple_kill", 2: "quadra_kill"}

    def __init__(self):
        self.predict_calls = 0

    def predict(self, frames, conf, verbose, **_kwargs):
        self.predict_calls += 1
        count = len(frames) if isinstance(frames, list) else 1
        return [FakeResult([
            FakeBox(0, 0.91, [10, 20, 100, 80]),
            FakeBox(1, 0.88, [1, 2, 3, 4]),
        ]) for _ in range(count)]


class CVServiceTestCase(unittest.TestCase):
    def test_missing_model_and_invalid_video(self):
        with self.assertRaises(ModelNotFoundError):
            load_model("definitely-missing.pt")
        with self.assertRaises(InvalidMediaError):
            sample_frames("definitely-missing.mp4")

    def test_empty_and_corrupt_video(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.mp4"
            empty.touch()
            corrupt = Path(directory) / "corrupt.mp4"
            corrupt.write_bytes(b"not a video")
            with self.assertRaises(InvalidMediaError):
                sample_frames(empty)
            with self.assertRaises(InvalidMediaError):
                sample_frames(corrupt)

    def test_detection_normalizes_penta_kill_and_filters_other_classes(self):
        detections = detect_frame(FakeModel(), np.zeros((120, 160, 3), dtype=np.uint8), 0.35)
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["class"], "penta_kill")
        self.assertEqual(detections[0]["raw_class"], "penta_kill")
        self.assertEqual(detections[0]["bbox"], [10.0, 20.0, 100.0, 80.0])

    def test_batch_detection_uses_one_predict_call(self):
        model = FakeModel()
        frames = [np.zeros((120, 160, 3), dtype=np.uint8) for _ in range(4)]
        detections = detect_frames(model, frames, 0.35)
        self.assertEqual(model.predict_calls, 1)
        self.assertEqual(len(detections), 4)
        self.assertTrue(all(len(items) == 1 for items in detections))

    @patch("source_code.cv_service.cv2.VideoCapture")
    def test_stream_sampling_is_lazy_and_releases_capture(self, mocked_video_capture):
        class FakeCapture:
            def __init__(self):
                self.position = 0
                self.read_calls = 0
                self.released = False

            def isOpened(self):
                return True

            def get(self, prop):
                if prop == cv2.CAP_PROP_FRAME_COUNT:
                    return 6
                if prop == cv2.CAP_PROP_FPS:
                    return 3
                return 0

            def read(self):
                self.read_calls += 1
                if self.position >= 6:
                    return False, None
                frame = np.full((4, 4, 3), self.position, dtype=np.uint8)
                self.position += 1
                return True, frame

            def grab(self):
                if self.position >= 6:
                    return False
                self.position += 1
                return True

            def release(self):
                self.released = True

        capture = FakeCapture()
        mocked_video_capture.return_value = capture
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"video")
            stream, metadata = stream_sampled_frames(video, sample_interval=2)
            self.assertEqual(capture.read_calls, 0)
            frames = list(stream)

        self.assertEqual([item["frame_index"] for item in frames], [0, 2, 4])
        self.assertEqual(metadata["sampled_count"], 3)
        self.assertTrue(capture.released)

    def test_threshold_validation(self):
        with self.assertRaises(ValueError):
            detect_frame(FakeModel(), np.zeros((10, 10, 3), dtype=np.uint8), 1.5)

    @patch("source_code.cv_service.load_model", return_value=FakeModel())
    def test_rejects_unknown_model_version(self, _mocked_model):
        with self.assertRaises(ValueError):
            extract_highlights("ignored.mp4", settings={"model_version": "unknown"})

    def test_visual_and_excitement_scores(self):
        first = np.zeros((80, 80), dtype=np.uint8)
        second = np.zeros((80, 80, 3), dtype=np.uint8)
        cv2.rectangle(second, (20, 20), (60, 60), (255, 255, 255), -1)
        frame_change, motion = calculate_visual_scores(first, second)
        self.assertGreater(frame_change, 0)
        scores = calc_excitement_score([{"class": "penta_kill"}], frame_change, motion)
        self.assertGreater(scores["total"], 0)
        self.assertIn("motion_intensity", scores)

    def test_tracking_generates_time_series(self):
        tracker = IoUTracker()
        first = {"bbox": [10, 10, 50, 50]}
        second = {"bbox": [12, 12, 52, 52]}
        tracker.update([first], 0.0)
        tracker.update([second], 0.5)
        self.assertEqual(first["track_id"], second["track_id"])
        self.assertEqual(len(tracker.export()[0]["points"]), 2)

    @patch("source_code.cv_service.load_model", return_value=FakeModel())
    @patch("source_code.cv_service.stream_sampled_frames")
    def test_extract_contract_and_settings(self, mocked_stream, _mocked_model):
        image = np.zeros((120, 160, 3), dtype=np.uint8)
        metadata = {
            "total_frames": 30,
            "fps": 30.0,
            "duration": 1.0,
            "sampled_count": 1,
        }
        mocked_stream.return_value = (iter([
            {"frame_index": 0, "timestamp": 0.0, "image": image},
        ]), metadata)
        result = extract_highlights("ignored.mp4", settings={
            "confidence_threshold": 0.5,
            "sample_interval": 10,
            "batch_size": 8,
            "tracking": True,
        })
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["detection_count"], 1)
        self.assertEqual(result["detections"][0]["detections"][0]["class"], "penta_kill")
        self.assertEqual(result["parameters"]["confidence_threshold"], 0.5)
        self.assertEqual(result["parameters"]["batch_size"], 8)
        self.assertEqual(result["model"]["task"], "penta_kill_detection")
        self.assertTrue(result["trajectories"])

    @patch("source_code.cv_service.stream_sampled_frames")
    @patch("source_code.cv_service.load_model")
    def test_extract_batches_streamed_frames(self, mocked_load_model, mocked_stream):
        model = FakeModel()
        mocked_load_model.return_value = model
        image = np.zeros((12, 16, 3), dtype=np.uint8)
        frames = [
            {"frame_index": index, "timestamp": index / 30, "image": image}
            for index in range(5)
        ]
        mocked_stream.return_value = (iter(frames), {
            "total_frames": 5,
            "fps": 30.0,
            "duration": 0.167,
            "sampled_count": 5,
        })

        result = extract_highlights("ignored.mp4", settings={
            "batch_size": 2,
            "tracking": False,
            "keyframes": False,
        })

        self.assertEqual(model.predict_calls, 3)
        self.assertEqual(len(result["detections"]), 5)


if __name__ == "__main__":
    unittest.main()
