import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from routes.analysis import _normalize_result
from utils.auth import generate_jwt


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "OUTPUT_DIR": Path(self.temp_dir.name) / "outputs",
            "ANALYZE_ASYNC": False,
            "AUTH_REQUIRED": False,
            "JOB_DB_SYNC": False,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_job(self, content=b"not-a-real-video", settings=None):
        data = {"file": (io.BytesIO(content), "sample.mp4"), "project_name": "接口测试"}
        if settings is not None:
            data["settings"] = json.dumps(settings)
        return self.client.post(
            "/api/jobs",
            data=data,
            content_type="multipart/form-data",
        )

    def test_health_and_job_creation(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("游戏高光自动剪辑", page.get_data(as_text=True))

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["data"]["status"], "ok")

        response = self.create_job()
        self.assertEqual(response.status_code, 201)
        job = response.json["data"]["job"]
        self.assertEqual(job["status"], "created")
        self.assertTrue((Path(self.app.config["OUTPUT_DIR"]) / job["job_id"] / "job.json").exists())

    def test_rejects_invalid_and_empty_uploads(self):
        invalid = self.client.post(
            "/api/jobs", data={"file": (io.BytesIO(b"data"), "sample.txt")}, content_type="multipart/form-data"
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.json["code"], 400)

        empty = self.create_job(b"")
        self.assertEqual(empty.status_code, 400)
        self.assertIn("空文件", empty.json["msg"])

    def test_job_lifecycle_errors_and_delete(self):
        created = self.create_job().json["data"]["job"]
        missing_report = self.client.get(f"/api/jobs/{created['job_id']}/report")
        self.assertEqual(missing_report.status_code, 409)

        deleted = self.client.delete(f"/api/jobs/{created['job_id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse((Path(self.app.config["OUTPUT_DIR"]) / created["job_id"]).exists())

    def test_review_validation(self):
        created = self.create_job().json["data"]["job"]
        response = self.client.patch(
            f"/api/jobs/{created['job_id']}/review", data=json.dumps({"keyframe_id": "k1", "action": "bad"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("keep", response.json["msg"])

    def test_frontend_pages_are_registered(self):
        for path in ("/kb/manage", "/kb/search", "/agent/analysis", "/visualization", "/stats", "/model/compare"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        source = self.client.get("/source/c47a07e29f04c6b4c1fdd4722953cc9d.jpg")
        self.assertEqual(source.status_code, 200)
        self.assertEqual(source.mimetype, "image/jpeg")
        source.close()

    def test_agent_routes_use_coze_and_require_authentication(self):
        health = self.client.get("/api/agent/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["data"]["engine"], "coze")

        protected_app = create_app({
            "TESTING": True,
            "OUTPUT_DIR": Path(self.temp_dir.name) / "agent-outputs",
            "JOB_DB_SYNC": False,
        })
        response = protected_app.test_client().post("/api/agent/run", json={"detect_task_id": "missing"})
        self.assertEqual(response.status_code, 401)

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
        settings = {"confidence_threshold": 0.5, "tracking": False}
        job = self.create_job(settings=settings).json["data"]["job"]

        analyzed = self.client.post(f"/api/jobs/{job['job_id']}/analyze")
        self.assertEqual(analyzed.status_code, 202)
        self.assertEqual(self.client.get(f"/api/jobs/{job['job_id']}").json["data"]["job"]["status"], "completed")
        extract_highlights.assert_called_once()
        self.assertEqual(extract_highlights.call_args.kwargs["settings"], settings)

        report = self.client.get(f"/api/jobs/{job['job_id']}/report").json["data"]["report"]
        self.assertEqual(report["video"]["duration"], 8.0)
        self.assertEqual(report["keyframes"][0]["id"], "segment_1")

        reviewed = self.client.patch(
            f"/api/jobs/{job['job_id']}/review",
            data=json.dumps({"keyframe_id": "segment_1", "action": "keep"}),
            content_type="application/json",
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json["data"]["keyframe"]["review"], "keep")

        reviewed = self.client.patch(
            f"/api/jobs/{job['job_id']}/review",
            data=json.dumps({"keyframe_id": "segment_1", "action": "pass", "note": "人工确认五杀"}),
            content_type="application/json",
        )
        self.assertEqual(reviewed.status_code, 200)
        keyframe = reviewed.json["data"]["keyframe"]
        self.assertEqual(keyframe["review"], "pass")
        self.assertEqual(keyframe["auditRecords"][-1]["note"], "人工确认五杀")
        current_job = self.client.get(f"/api/jobs/{job['job_id']}").json["data"]["job"]
        self.assertEqual(current_job["audit_status"], "pass")

    def test_jobs_require_authentication_by_default(self):
        protected_app = create_app({
            "TESTING": True,
            "OUTPUT_DIR": Path(self.temp_dir.name) / "protected-outputs",
            "JOB_DB_SYNC": False,
        })
        response = protected_app.test_client().get("/api/jobs")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["code"], 401)

    @patch("app.create_rough_cut")
    @patch("app.FFMPEG_AVAILABLE", True)
    def test_rough_cut_uses_report_highlights(self, create_rough_cut):
        create_rough_cut.return_value = {
            "filename": "rough_cut.mp4",
            "segment_count": 1,
            "duration": 6.0,
            "size": 1234,
            "segments": [{"segment_id": 1, "start_time": 0, "end_time": 6, "duration": 6}],
        }
        job = self.create_job(settings={"clip_duration": 6}).json["data"]["job"]
        directory = Path(self.app.config["OUTPUT_DIR"]) / job["job_id"]
        job.update(status="completed", result_file="analysis_report.json")
        (directory / "job.json").write_text(json.dumps(job), encoding="utf-8")
        report = {
            "video": {"duration": 12.0},
            "highlights": [{"segment_id": 1, "start_time": 2.0, "end_time": 3.0}],
        }
        (directory / "analysis_report.json").write_text(json.dumps(report), encoding="utf-8")

        response = self.client.post(
            f"/api/jobs/{job['job_id']}/rough-cut",
            json={"clip_duration": 6},
        )
        self.assertEqual(response.status_code, 200)
        rough_cut = response.json["data"]["rough_cut"]
        self.assertEqual(rough_cut["video_url"], f"/outputs/{job['job_id']}/rough_cut.mp4")
        self.assertEqual(create_rough_cut.call_args.kwargs["clip_duration"], 6.0)
        saved_report = json.loads((directory / "analysis_report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved_report["rough_cut"]["segment_count"], 1)

    def test_agent_result_normalization_keeps_extra_fields(self):
        result = _normalize_result({
            "output": json.dumps({
                "内容摘要": "**检测完成**\n- 发现五杀",
                "标签": "五杀，高光",
                "审核结论": "建议通过",
                "置信度": 0.93,
            }, ensure_ascii=False)
        })
        self.assertIn("检测完成", result["summary"])
        self.assertEqual(result["tags"], ["五杀", "高光"])
        self.assertEqual(result["suggestion"], "建议通过")
        self.assertEqual(result["details"]["置信度"], 0.93)

    def test_jobs_are_isolated_by_authenticated_user(self):
        protected_app = create_app({
            "TESTING": True,
            "OUTPUT_DIR": Path(self.temp_dir.name) / "isolated-outputs",
            "ANALYZE_ASYNC": False,
            "JOB_DB_SYNC": False,
        })
        client = protected_app.test_client()
        first_headers = {"Authorization": f"Bearer {generate_jwt('user-1', 'first')}"}
        second_headers = {"Authorization": f"Bearer {generate_jwt('user-2', 'second')}"}
        created = client.post(
            "/api/jobs",
            headers=first_headers,
            data={"file": (io.BytesIO(b"video"), "sample.mp4")},
            content_type="multipart/form-data",
        ).json["data"]["job"]
        self.assertEqual(client.get("/api/jobs", headers=second_headers).json["data"]["jobs"], [])
        self.assertEqual(client.get(f"/api/jobs/{created['job_id']}", headers=second_headers).status_code, 404)

    @patch("app.get_db")
    def test_job_state_is_synchronized_to_mongodb(self, get_db):
        collection = get_db.return_value.__getitem__.return_value
        sync_app = create_app({
            "TESTING": True,
            "OUTPUT_DIR": Path(self.temp_dir.name) / "sync-outputs",
            "AUTH_REQUIRED": False,
            "JOB_DB_SYNC": True,
        })
        response = sync_app.test_client().post(
            "/api/jobs",
            data={"file": (io.BytesIO(b"video"), "sample.mp4")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 201)
        collection.replace_one.assert_called_once()
        self.assertTrue(collection.replace_one.call_args.kwargs["upsert"])


if __name__ == "__main__":
    unittest.main()
