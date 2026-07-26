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
    extract_highlights,
    load_model,
    sample_frames,
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
    names = {0: "penta_kill", 1: "multi_kill", 2: "kill_feed"}

    def predict(self, frame, conf, verbose):
        return [FakeResult([
            FakeBox(1, 0.91, [10, 20, 100, 80]),
            FakeBox(2, 0.88, [1, 2, 3, 4]),
        ])]


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
        self.assertEqual(detections[0]["raw_class"], "multi_kill")
        self.assertEqual(detections[0]["bbox"], [10.0, 20.0, 100.0, 80.0])

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
    @patch("source_code.cv_service.sample_frames")
    def test_extract_contract_and_settings(self, mocked_sample, _mocked_model):
        image = np.zeros((120, 160, 3), dtype=np.uint8)
        mocked_sample.return_value = {
            "frames": [{"frame_index": 0, "timestamp": 0.0, "image": image}],
            "total_frames": 30,
            "fps": 30.0,
            "duration": 1.0,
            "sampled_count": 1,
        }
        result = extract_highlights("ignored.mp4", settings={
            "confidence_threshold": 0.5,
            "sample_interval": 10,
            "tracking": True,
        })
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["detection_count"], 1)
        self.assertEqual(result["detections"][0]["detections"][0]["class"], "penta_kill")
        self.assertEqual(result["parameters"]["confidence_threshold"], 0.5)
        self.assertEqual(result["model"]["task"], "penta_kill_detection")
        self.assertTrue(result["trajectories"])


if __name__ == "__main__":
    unittest.main()
