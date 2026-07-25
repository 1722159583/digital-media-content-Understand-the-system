import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "OUTPUT_DIR": Path(self.temp_dir.name) / "outputs",
            "ANALYZE_ASYNC": False,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_job(self, content=b"not-a-real-video"):
        return self.client.post(
            "/api/jobs",
            data={"file": (io.BytesIO(content), "sample.mp4"), "project_name": "接口测试"},
            content_type="multipart/form-data",
        )

    def test_health_and_job_creation(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("视频精彩片段提取系统", page.get_data(as_text=True))

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json["ok"])

        response = self.create_job()
        self.assertEqual(response.status_code, 201)
        job = response.json["job"]
        self.assertEqual(job["status"], "created")
        self.assertTrue((Path(self.app.config["OUTPUT_DIR"]) / job["job_id"] / "job.json").exists())

    def test_rejects_invalid_and_empty_uploads(self):
        invalid = self.client.post(
            "/api/jobs", data={"file": (io.BytesIO(b"data"), "sample.txt")}, content_type="multipart/form-data"
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(invalid.json["ok"])

        empty = self.create_job(b"")
        self.assertEqual(empty.status_code, 400)
        self.assertIn("空文件", empty.json["error"])

    def test_job_lifecycle_errors_and_delete(self):
        created = self.create_job().json["job"]
        missing_report = self.client.get(f"/api/jobs/{created['job_id']}/report")
        self.assertEqual(missing_report.status_code, 409)

        deleted = self.client.delete(f"/api/jobs/{created['job_id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse((Path(self.app.config["OUTPUT_DIR"]) / created["job_id"]).exists())

    def test_review_validation(self):
        created = self.create_job().json["job"]
        response = self.client.patch(
            f"/api/jobs/{created['job_id']}/review", data=json.dumps({"keyframe_id": "k1", "action": "bad"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("keep", response.json["error"])

    @patch("app.extract_highlights")
    def test_analysis_report_and_review_lifecycle(self, extract_highlights):
        extract_highlights.return_value = {
            "status": "completed",
            "video_info": {"duration": 8.0, "fps": 24.0, "total_frames": 192, "sampled_frames": 4},
            "highlights": [{"segment_id": 1, "start_time": 1.0, "end_time": 4.0, "score": 0.82, "reason": "检测到 person×2"}],
            "model": "yolo11n",
            "parameters": {},
            "processing_time": 0.3,
        }
        job = self.create_job().json["job"]

        analyzed = self.client.post(f"/api/jobs/{job['job_id']}/analyze")
        self.assertEqual(analyzed.status_code, 202)
        self.assertEqual(self.client.get(f"/api/jobs/{job['job_id']}").json["job"]["status"], "completed")

        report = self.client.get(f"/api/jobs/{job['job_id']}/report").json["report"]
        self.assertEqual(report["video"]["duration"], 8.0)
        self.assertEqual(report["keyframes"][0]["id"], "segment_1")

        reviewed = self.client.patch(
            f"/api/jobs/{job['job_id']}/review",
            data=json.dumps({"keyframe_id": "segment_1", "action": "keep"}),
            content_type="application/json",
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json["keyframe"]["review"], "keep")


if __name__ == "__main__":
    unittest.main()
