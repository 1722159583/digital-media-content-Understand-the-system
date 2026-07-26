"""CV inference defaults for the penta-kill detector."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "game_highlight_train4_best.pt"
TRAIN_RUN_PATH = BASE_DIR / "runs" / "detect" / "train-4"
MODEL_VERSION = "train-4-penta-only"
MODEL_DISPLAY_NAME = "YOLO11n penta-kill detector"

# train-4 was annotated inconsistently: most penta-kill banners were stored as
# class 1 (multi_kill). Both learned penta-kill IDs are normalized at the API.
PENTA_KILL_CLASS_IDS = {0, 1}
OUTPUT_CLASS_NAME = "penta_kill"

CONFIDENCE_THRESHOLD = 0.35
SAMPLE_INTERVAL = 15
TOP_N_SEGMENTS = 5
SEGMENT_MIN_DURATION = 0.0
SEGMENT_MAX_DURATION = 10.0

# Requirement document scoring dimensions: visual change, motion and targets.
WEIGHT_FRAME_CHANGE = 0.30
WEIGHT_MOTION = 0.30
WEIGHT_TARGET_COUNT = 0.40

MODEL_WARNINGS = [
    "train-4 当前仅用于五杀检测，不支持 multi_kill 或 kill_feed 的可靠识别。",
    "训练集中五杀样本主要被标为原始 class 1；接口已统一显示为 penta_kill，并保留 raw_class 供追溯。",
]
