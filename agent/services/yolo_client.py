"""YOLOClient — 对接 YOLO 检测服务的 API 客户端

支持：
- 上传素材进行 YOLO 检测
- 查询检测结果
- 获取已完成的检测任务列表
- 错误处理和重试
"""
import json, os, time
from typing import Optional
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")


class YOLOClient:
    """YOLO 检测服务客户端"""

    def __init__(self, config_path: str = CONFIG_PATH):
        self.config = self._load_config(config_path)
        yolo_cfg = self.config.get("yolo_service", {})
        self.base_url = yolo_cfg.get("base_url", "http://127.0.0.1:8000")
        self.api_key = yolo_cfg.get("api_key", "")
        self.timeout = yolo_cfg.get("timeout", 30)
        self._session = None

    def _load_config(self, path: str) -> dict:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _get_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @property
    def is_available(self) -> bool:
        """检查 YOLO 服务是否可用"""
        try:
            import requests
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def detect_image(self, image_path: str) -> dict:
        """上传图片进行 YOLO 检测

        参数:
            image_path: 图片文件路径

        返回:
            dict: YOLO 检测结果，包含 detections 列表
                  {"detections": [...], "image_size": {...}, "model": "yolo11n"}
        """
        import requests
        url = f"{self.base_url}/api/detect/image"
        try:
            with open(image_path, "rb") as f:
                files = {"file": f}
                resp = requests.post(url, files=files,
                                     headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                                     timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
            else:
                return {
                    "error": f"YOLO 检测失败 (HTTP {resp.status_code}): {resp.text}",
                    "detections": [],
                }
        except requests.exceptions.ConnectionError:
            return {"error": f"无法连接 YOLO 服务 ({self.base_url})", "detections": []}
        except Exception as e:
            return {"error": f"YOLO 检测异常: {str(e)}", "detections": []}

    def detect_video(self, video_path: str, frame_interval: int = 30) -> dict:
        """上传视频进行 YOLO 检测

        参数:
            video_path: 视频文件路径
            frame_interval: 帧采样间隔

        返回:
            dict: 包含每帧检测结果和关键帧汇总
        """
        import requests
        url = f"{self.base_url}/api/detect/video"
        try:
            with open(video_path, "rb") as f:
                files = {"file": f}
                data = {"frame_interval": frame_interval}
                resp = requests.post(url, files=files, data=data,
                                     headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                                     timeout=self.timeout * 2)
            if resp.status_code == 200:
                return resp.json()
            else:
                return {"error": f"视频检测失败 (HTTP {resp.status_code})", "frames": []}
        except Exception as e:
            return {"error": f"视频检测异常: {str(e)}", "frames": []}

    def get_detection_result(self, task_id: str) -> Optional[dict]:
        """查询检测任务结果"""
        import requests
        try:
            resp = requests.get(f"{self.base_url}/api/detect/result/{task_id}",
                                headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            return None
        except Exception:
            return None

    def mock_detection(self) -> dict:
        """生成模拟检测结果（用于开发和测试）"""
        return {
            "detections": [
                {"class_id": 0, "class_name": "person", "confidence": 0.95,
                 "bbox": [120, 80, 280, 420]},
                {"class_id": 2, "class_name": "car", "confidence": 0.88,
                 "bbox": [350, 200, 580, 320]},
                {"class_id": 67, "class_name": "cell phone", "confidence": 0.72,
                 "bbox": [200, 250, 240, 310]},
            ],
            "image_size": {"width": 1920, "height": 1080},
            "model": "yolo11n",
            "inference_time_ms": 45.2,
            "source": "mock",
        }
