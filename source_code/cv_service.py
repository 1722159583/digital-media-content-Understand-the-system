"""YOLO/OpenCV service for penta-kill image and video detection."""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Sequence

import cv2
import numpy as np

from .cv_config import (
    CONFIDENCE_THRESHOLD,
    INFERENCE_BATCH_SIZE,
    MODEL_DISPLAY_NAME,
    MODEL_PATH,
    MODEL_VERSION,
    MODEL_WARNINGS,
    OUTPUT_CLASS_NAME,
    PENTA_KILL_CLASS_IDS,
    SAMPLE_INTERVAL,
    SEGMENT_MAX_DURATION,
    SEGMENT_MIN_DURATION,
    TOP_N_SEGMENTS,
    WEIGHT_FRAME_CHANGE,
    WEIGHT_MOTION,
    WEIGHT_TARGET_COUNT,
)


class CVServiceError(RuntimeError):
    """Base error that can be presented safely by the API."""


class ModelNotFoundError(CVServiceError):
    pass


class InvalidMediaError(CVServiceError):
    pass


class InferenceError(CVServiceError):
    pass


def _validate_threshold(value: Any) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("confidence_threshold 必须是 0 到 1 之间的数字") from error
    if not 0.0 < threshold <= 1.0:
        raise ValueError("confidence_threshold 必须大于 0 且不超过 1")
    return threshold


def _validate_media(path: str | Path, media_type: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise InvalidMediaError(f"{media_type}文件不存在: {resolved}")
    if resolved.stat().st_size == 0:
        raise InvalidMediaError(f"{media_type}文件为空: {resolved}")
    return resolved


@lru_cache(maxsize=4)
def _load_model_cached(model_path: str):
    try:
        from ultralytics import YOLO
    except ImportError as error:
        raise ModelNotFoundError("未安装 ultralytics，无法加载 YOLO 模型") from error
    try:
        return YOLO(model_path)
    except Exception as error:
        raise InferenceError(f"YOLO 模型加载失败: {error}") from error


def load_model(model_path: str | Path | None = None):
    """Load and cache a local YOLO weight."""
    path = Path(model_path or MODEL_PATH).resolve()
    model_dir = MODEL_PATH.parent.resolve()
    if path != MODEL_PATH.resolve() and model_dir not in path.parents:
        raise ModelNotFoundError(f"自定义模型必须放在当前训练权重目录中: {model_dir}")
    if not path.is_file():
        raise ModelNotFoundError(f"YOLO 模型文件不存在: {path}")
    return _load_model_cached(str(path))


def warmup_model(model_path: str | Path | None = None):
    """Load the model and run one real inference to initialize the backend."""
    model = load_model(model_path)
    dummy = np.zeros((640, 640, 3), dtype=np.uint8)
    detect_frame(model, dummy, CONFIDENCE_THRESHOLD)
    return model


def stream_sampled_frames(
    video_path: str | Path,
    sample_interval: int | None = None,
) -> tuple[Iterator[dict[str, Any]], dict[str, Any]]:
    """Open a video and lazily yield every Nth frame with shared metadata."""
    path = _validate_media(video_path, "视频")
    interval = SAMPLE_INTERVAL if sample_interval is None else int(sample_interval)
    if interval < 1:
        raise ValueError("sample_interval 必须是正整数")

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise InvalidMediaError(f"无法打开或不支持的视频: {path}")
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not np.isfinite(fps) or fps <= 0:
        fps = 30.0
    metadata = {
        "total_frames": max(total_frames, 0),
        "fps": round(fps, 3),
        "duration": round(total_frames / fps, 3) if total_frames > 0 else 0.0,
        "sampled_count": 0,
    }

    def iterator() -> Iterator[dict[str, Any]]:
        frame_index = 0
        try:
            while True:
                if frame_index % interval == 0:
                    ok, frame = capture.read()
                    if not ok:
                        break
                    metadata["sampled_count"] += 1
                    yield {
                        "frame_index": frame_index,
                        "timestamp": round(frame_index / fps, 3),
                        "image": frame,
                    }
                else:
                    if not capture.grab():
                        break
                frame_index += 1
        finally:
            capture.release()
            if metadata["total_frames"] <= 0:
                metadata["total_frames"] = frame_index
                metadata["duration"] = round(frame_index / fps, 3)

    return iterator(), metadata


def sample_frames(video_path: str | Path, sample_interval: int | None = None) -> dict[str, Any]:
    """Read every Nth frame and retain its exact timestamp."""
    frame_stream, metadata = stream_sampled_frames(video_path, sample_interval)
    frames = list(frame_stream)
    if not frames:
        raise InvalidMediaError(f"视频中没有可解码的有效帧: {Path(video_path).resolve()}")
    return {"frames": frames, **metadata}


def _raw_name(model: Any, class_id: int) -> str:
    names = getattr(model, "names", {})
    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, (list, tuple)) and class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _parse_detections(model: Any, result: Any) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    for box in result.boxes:
        class_id = int(box.cls[0])
        if class_id not in PENTA_KILL_CLASS_IDS:
            continue
        confidence = float(box.conf[0])
        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0])
        detections.append({
            "class": OUTPUT_CLASS_NAME,
            "class_id": 0,
            "raw_class": _raw_name(model, class_id),
            "raw_class_id": class_id,
            "confidence": round(confidence, 4),
            "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
        })
    return detections


def detect_frames(
    model: Any,
    frames: Sequence[np.ndarray],
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> list[list[dict[str, Any]]]:
    """Run one batched prediction and return detections for every input frame."""
    threshold = _validate_threshold(confidence_threshold)
    if not frames:
        return []
    if any(frame is None or not isinstance(frame, np.ndarray) or frame.size == 0 for frame in frames):
        raise InvalidMediaError("输入图像批次中包含空图像")
    try:
        results = list(model.predict(
            list(frames),
            conf=threshold,
            classes=sorted(PENTA_KILL_CLASS_IDS),
            verbose=False,
        ))
    except AttributeError:
        results = list(model(list(frames), conf=threshold, verbose=False))
    except Exception as error:
        raise InferenceError(f"YOLO 推理失败: {error}") from error
    if len(results) != len(frames):
        raise InferenceError(f"YOLO 返回结果数 {len(results)} 与输入帧数 {len(frames)} 不一致")
    try:
        return [_parse_detections(model, result) for result in results]
    except (AttributeError, IndexError, TypeError, ValueError) as error:
        raise InferenceError(f"无法解析 YOLO 推理结果: {error}") from error


def detect_frame(
    model: Any,
    frame: np.ndarray,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return penta-kill detections for one frame."""
    return detect_frames(model, [frame], confidence_threshold)[0]


def calculate_visual_scores(previous: np.ndarray | None, current: np.ndarray) -> tuple[float, float]:
    """Calculate normalized frame-difference and optical-flow scores."""
    gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    if previous is None:
        return 0.0, 0.0
    if previous.shape != gray.shape:
        previous = cv2.resize(previous, (gray.shape[1], gray.shape[0]))
    frame_change = min(float(cv2.absdiff(previous, gray).mean()) / 64.0, 1.0)
    flow = cv2.calcOpticalFlowFarneback(previous, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    magnitude = cv2.magnitude(flow[..., 0], flow[..., 1])
    finite = magnitude[np.isfinite(magnitude)]
    motion = min(float(np.percentile(finite, 90)) / 8.0, 1.0) if finite.size else 0.0
    return round(frame_change, 4), round(motion, 4)


def calc_excitement_score(
    detections: list[dict[str, Any]],
    frame_change_score: float = 0.0,
    motion_score: float = 0.0,
) -> dict[str, float]:
    target_count_score = min(len(detections) / 2.0, 1.0)
    total = (
        WEIGHT_FRAME_CHANGE * max(0.0, min(frame_change_score, 1.0))
        + WEIGHT_MOTION * max(0.0, min(motion_score, 1.0))
        + WEIGHT_TARGET_COUNT * target_count_score
    )
    return {
        "frame_change": round(frame_change_score, 4),
        "motion_intensity": round(motion_score, 4),
        "target_count": round(target_count_score, 4),
        "total": round(min(total, 1.0), 4),
    }


def _iou(first: list[float], second: list[float]) -> float:
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


class IoUTracker:
    """Small deterministic tracker suitable for sparsely sampled banner boxes."""

    def __init__(self, threshold: float = 0.3):
        self.threshold = threshold
        self.next_id = 1
        self.boxes: dict[int, list[float]] = {}
        self.trajectories: dict[int, list[dict[str, Any]]] = {}

    def update(self, detections: list[dict[str, Any]], timestamp: float) -> None:
        available = set(self.boxes)
        for detection in detections:
            best_id, best_iou = None, self.threshold
            for track_id in available:
                overlap = _iou(detection["bbox"], self.boxes[track_id])
                if overlap >= best_iou:
                    best_id, best_iou = track_id, overlap
            if best_id is None:
                best_id = self.next_id
                self.next_id += 1
            else:
                available.remove(best_id)
            detection["track_id"] = best_id
            self.boxes[best_id] = detection["bbox"]
            box = detection["bbox"]
            self.trajectories.setdefault(best_id, []).append({
                "timestamp": timestamp,
                "bbox": box,
                "center": [round((box[0] + box[2]) / 2, 1), round((box[1] + box[3]) / 2, 1)],
            })

    def export(self) -> list[dict[str, Any]]:
        return [
            {"track_id": track_id, "class": OUTPUT_CLASS_NAME, "points": points}
            for track_id, points in sorted(self.trajectories.items())
        ]


def _draw_detections(frame: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
    annotated = frame.copy()
    for item in detections:
        x1, y1, x2, y2 = (int(value) for value in item["bbox"])
        label = f"penta_kill {item['confidence']:.2f}"
        if "track_id" in item:
            label += f" ID:{item['track_id']}"
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (32, 220, 90), 2)
        cv2.putText(annotated, label, (x1, max(20, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (32, 220, 90), 2)
    return annotated


def merge_segments(
    frames: list[dict[str, Any]], fps: float, min_duration: float, max_duration: float,
    sample_interval: int = SAMPLE_INTERVAL,
) -> list[dict[str, Any]]:
    detected = [item for item in frames if item["detections"]]
    if not detected:
        return []
    max_gap = max(2.0, sample_interval / fps * 2.2)
    groups: list[list[dict[str, Any]]] = [[detected[0]]]
    for item in detected[1:]:
        current = groups[-1]
        if item["timestamp"] - current[-1]["timestamp"] <= max_gap and item["timestamp"] - current[0]["timestamp"] <= max_duration:
            current.append(item)
        else:
            groups.append([item])

    highlights = []
    for group in groups:
        start = group[0]["timestamp"]
        end = min(group[-1]["timestamp"] + sample_interval / fps, start + max_duration)
        if end - start < min_duration:
            continue
        best = max(group, key=lambda item: item["scores"]["total"])
        highlights.append({
            "segment_id": 0,
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "duration": round(end - start, 3),
            "score": round(sum(item["scores"]["total"] for item in group) / len(group), 4),
            "reason": "检测到五杀画面",
            "detection_count": sum(len(item["detections"]) for item in group),
            "evidence_frame_index": best["frame_index"],
            "evidence_timestamp": best["timestamp"],
        })
    highlights.sort(key=lambda item: item["score"], reverse=True)
    for index, item in enumerate(highlights[:TOP_N_SEGMENTS], 1):
        item["segment_id"] = index
    return highlights[:TOP_N_SEGMENTS]


def analyze_image(
    image_path: str | Path,
    output_path: str | Path | None = None,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    model_path: str | Path | None = None,
) -> dict[str, Any]:
    """Detect penta-kill banners in one image and optionally save visualization."""
    started = time.perf_counter()
    path = _validate_media(image_path, "图片")
    image = cv2.imread(str(path))
    if image is None or image.size == 0:
        raise InvalidMediaError(f"无法解码图片: {path}")
    detections = detect_frame(load_model(model_path), image, confidence_threshold)
    saved_path = None
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(target), _draw_detections(image, detections)):
            raise InvalidMediaError(f"检测结果图片写入失败: {target}")
        saved_path = str(target)
    elapsed = round(time.perf_counter() - started, 3)
    return {
        "status": "completed",
        "detections": detections,
        "detection_count": len(detections),
        "annotated_image": saved_path,
        "low_confidence_or_no_detection": not detections,
        "processing_time": elapsed,
        "performance_target_met": elapsed <= 10.0,
        "model": _model_metadata(model_path),
    }


def _model_metadata(model_path: str | Path | None = None) -> dict[str, Any]:
    return {
        "name": MODEL_DISPLAY_NAME,
        "version": MODEL_VERSION,
        "path": str(Path(model_path or MODEL_PATH).resolve()),
        "task": "penta_kill_detection",
        "output_classes": [OUTPUT_CLASS_NAME],
        "warnings": list(MODEL_WARNINGS),
    }


def _process_frame_batch(
    model: Any,
    batch: list[dict[str, Any]],
    confidence: float,
    tracker: IoUTracker,
    tracking: bool,
    frame_results: list[dict[str, Any]],
    frame_images: dict[int, np.ndarray],
    previous_gray: np.ndarray | None,
) -> np.ndarray | None:
    batch_detections = detect_frames(model, [entry["image"] for entry in batch], confidence)
    for entry, detections in zip(batch, batch_detections):
        image = entry["image"]
        frame_change, motion = calculate_visual_scores(previous_gray, image)
        previous_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if tracking:
            tracker.update(detections, entry["timestamp"])
        scores = calc_excitement_score(detections, frame_change, motion)
        frame_results.append({
            "frame_index": entry["frame_index"],
            "timestamp": entry["timestamp"],
            "detections": detections,
            "scores": scores,
        })
        if detections:
            frame_images[entry["frame_index"]] = image
    return previous_gray


def extract_highlights(
    video_path: str | Path,
    output_dir: str | Path | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect penta-kill frames and return scores, keyframes and trajectories."""
    started = time.perf_counter()
    options = dict(settings or {})
    confidence = _validate_threshold(options.get("confidence_threshold", CONFIDENCE_THRESHOLD))
    sample_interval = int(options.get("sample_interval", SAMPLE_INTERVAL))
    if sample_interval < 1:
        raise ValueError("sample_interval 必须是正整数")
    batch_size = int(options.get("batch_size", INFERENCE_BATCH_SIZE))
    if batch_size < 1:
        raise ValueError("batch_size 必须是正整数")
    tracking = bool(options.get("tracking", True))
    save_keyframes = bool(options.get("keyframes", True))
    model_path = options.get("model_path") or MODEL_PATH
    requested_version = options.get("model_version", MODEL_VERSION)
    if requested_version != MODEL_VERSION:
        raise ValueError(f"不支持的模型版本: {requested_version}，当前版本为 {MODEL_VERSION}")

    model = load_model(model_path)
    frame_stream, sampled = stream_sampled_frames(video_path, sample_interval)
    tracker = IoUTracker()
    frame_results: list[dict[str, Any]] = []
    frame_images: dict[int, np.ndarray] = {}
    previous_gray = None

    batch: list[dict[str, Any]] = []
    try:
        for item in frame_stream:
            batch.append(item)
            if len(batch) < batch_size:
                continue
            previous_gray = _process_frame_batch(
                model, batch, confidence, tracker, tracking,
                frame_results, frame_images, previous_gray,
            )
            batch.clear()

        if batch:
            previous_gray = _process_frame_batch(
                model, batch, confidence, tracker, tracking,
                frame_results, frame_images, previous_gray,
            )
    finally:
        close_stream = getattr(frame_stream, "close", None)
        if close_stream:
            close_stream()

    if not frame_results:
        raise InvalidMediaError(f"视频中没有可解码的有效帧: {Path(video_path).resolve()}")

    highlights = merge_segments(
        frame_results, sampled["fps"], SEGMENT_MIN_DURATION, SEGMENT_MAX_DURATION, sample_interval
    )
    evidence_files: dict[int, str] = {}
    if output_dir and save_keyframes:
        evidence_dir = Path(output_dir) / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        records_by_index = {item["frame_index"]: item for item in frame_results}
        for highlight in highlights:
            frame_index = highlight["evidence_frame_index"]
            target = evidence_dir / f"evidence_{highlight['segment_id']}.jpg"
            record = records_by_index[frame_index]
            if cv2.imwrite(str(target), _draw_detections(frame_images[frame_index], record["detections"])):
                evidence_files[highlight["segment_id"]] = str(target)

    warnings = list(MODEL_WARNINGS)
    detection_count = sum(len(item["detections"]) for item in frame_results)
    if detection_count == 0:
        warnings.append(f"未发现置信度不低于 {confidence:.2f} 的五杀画面，请人工复核或降低阈值。")
    elapsed = round(time.perf_counter() - started, 3)
    return {
        "status": "completed",
        "video_info": {
            "fps": sampled["fps"],
            "total_frames": sampled["total_frames"],
            "duration": sampled["duration"],
            "sampled_frames": sampled["sampled_count"],
        },
        "detections": frame_results,
        "detection_count": detection_count,
        "highlights": highlights,
        "trajectories": tracker.export() if tracking else [],
        "evidence_files": evidence_files,
        "score_summary": {
            "frame_change": round(sum(item["scores"]["frame_change"] for item in frame_results) / len(frame_results), 4),
            "motion_intensity": round(sum(item["scores"]["motion_intensity"] for item in frame_results) / len(frame_results), 4),
            "target_count": round(sum(item["scores"]["target_count"] for item in frame_results) / len(frame_results), 4),
        },
        "low_confidence_or_no_detection": detection_count == 0,
        "model": _model_metadata(model_path),
        "model_warnings": warnings,
        "parameters": {
            "confidence_threshold": confidence,
            "sample_interval": sample_interval,
            "batch_size": batch_size,
            "tracking": tracking,
            "keyframes": save_keyframes,
            "top_n_segments": TOP_N_SEGMENTS,
        },
        "processing_time": elapsed,
        "performance_target_met": elapsed <= 30.0 if sampled["duration"] <= 60.0 else None,
    }
