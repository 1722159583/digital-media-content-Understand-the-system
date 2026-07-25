# cv_config.py - CV算法参数配置
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "yolo11n.pt"
CONFIDENCE_THRESHOLD = 0.35
SAMPLE_INTERVAL = 15
TOP_N_SEGMENTS = 5
SEGMENT_MIN_DURATION = 2.0
SEGMENT_MAX_DURATION = 10.0

# 精彩度评分权重
WEIGHT_OBJECT_COUNT = 0.3
WEIGHT_OBJECT_TYPE = 0.4
WEIGHT_MOTION = 0.3

# 高价值目标类别（游戏战斗/动作相关）
HIGH_VALUE_CLASSES = {
    "person": 0.4, "car": 0.3, "motorcycle": 0.3, "bus": 0.3,
    "truck": 0.3, "boat": 0.3, "dog": 0.2, "cat": 0.2,
    "sports ball": 0.3, "baseball bat": 0.4, "baseball glove": 0.3,
    "skateboard": 0.3, "surfboard": 0.3, "tennis racket": 0.3,
    "knife": 0.5, "cell phone": 0.3, "book": 0.2, "clock": 0.1
}
