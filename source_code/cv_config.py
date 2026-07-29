"""CV inference defaults for the penta-kill detector."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TRAIN_RUN_PATH = BASE_DIR / "runs" / "detect" / "train"
MODEL_PATH = TRAIN_RUN_PATH / "weights" / "best.pt"
MODEL_VERSION = "train-best"
MODEL_DISPLAY_NAME = "YOLO11n game highlight detector"

# The current training run uses class 0 for penta-kill, class 1 for triple-kill
# and class 2 for quadra-kill. This service only exposes penta-kill detections.
PENTA_KILL_CLASS_IDS = {0}
OUTPUT_CLASS_NAME = "penta_kill"

CONFIDENCE_THRESHOLD = 0.35
SAMPLE_INTERVAL = 15
INFERENCE_BATCH_SIZE = 16
TOP_N_SEGMENTS = 5
SEGMENT_MIN_DURATION = 0.0
SEGMENT_MAX_DURATION = 10.0

# Requirement document scoring dimensions: visual change, motion and targets.
WEIGHT_FRAME_CHANGE = 0.30
WEIGHT_MOTION = 0.30
WEIGHT_TARGET_COUNT = 0.40

MODEL_WARNINGS = [
    "当前接口仅输出 penta_kill；模型中的 triple_kill 和 quadra_kill 类别会被过滤。",
]
