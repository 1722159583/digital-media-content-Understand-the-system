# cv_service.py - CV算法服务：视频采样 + YOLO推理 + 精彩度评分

import json
import os
from pathlib import Path

import cv2
import numpy as np


from .cv_config import (
    MODEL_PATH, CONFIDENCE_THRESHOLD, SAMPLE_INTERVAL,
    TOP_N_SEGMENTS, SEGMENT_MIN_DURATION, SEGMENT_MAX_DURATION,
    WEIGHT_OBJECT_COUNT, WEIGHT_OBJECT_TYPE, WEIGHT_MOTION,
    HIGH_VALUE_CLASSES,
)


def load_model(model_path=None):
    """加载YOLO模型"""
    from ultralytics import YOLO
    if model_path is None:
        model_path = MODEL_PATH
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"YOLO模型文件不存在: {model_path}")
    return YOLO(model_path)


def sample_frames(video_path, sample_interval=None):
    """用OpenCV从视频中均匀采样帧"""
    if sample_interval is None:
        sample_interval = SAMPLE_INTERVAL

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    duration = total_frames / fps if total_frames else 0

    frames = []
    frame_index = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_index % sample_interval == 0:
            timestamp = frame_index / fps
            frames.append({
                "frame_index": frame_index,
                "timestamp": round(timestamp, 2),
                "image": frame,
            })
        frame_index += 1
    cap.release()

    return {
        "frames": frames,
        "total_frames": total_frames,
        "fps": round(fps, 2),
        "duration": round(duration, 2),
        "sampled_count": len(frames),
    }


def detect_frame(model, frame):
    """对单帧进行YOLO推理，返回检测结果列表"""
    results = model(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
    detections = []
    for result in results:
        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(float, box.xyxy[0])
            class_name = model.names[cls_id]
            detections.append({
                "class": class_name,
                "class_id": cls_id,
                "confidence": round(conf, 4),
                "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
            })
    return detections


def calc_excitement_score(detections, prev_detections=None):
    """根据检测结果计算单帧精彩度分数(0~1)"""
    if not detections:
        return 0.0

    # 1. 目标数量得分：目标越多越精彩
    count_score = min(len(detections) / 5.0, 1.0)

    # 2. 目标类型得分：高价值目标加分
    type_score = 0.0
    for d in detections:
        cls_name = d["class"]
        if cls_name in HIGH_VALUE_CLASSES:
            type_score = max(type_score, HIGH_VALUE_CLASSES[cls_name])
    # 多高价值目标叠加，上限1.0
    high_value_count = sum(1 for d in detections if d["class"] in HIGH_VALUE_CLASSES)
    type_score = min(type_score + 0.1 * (high_value_count - 1), 1.0)

    # 3. 帧间变化得分：与上一帧相比目标数量变化大说明有动作
    motion_score = 0.0
    if prev_detections is not None:
        diff = abs(len(detections) - len(prev_detections))
        motion_score = min(diff * 0.15, 1.0)

    # 加权总分
    total = (
        WEIGHT_OBJECT_COUNT * count_score
        + WEIGHT_OBJECT_TYPE * type_score
        + WEIGHT_MOTION * motion_score
    )
    return round(min(total, 1.0), 4)


def merge_segments(segments, fps, min_duration, max_duration):
    """合并相邻的高分帧为连续片段"""
    if not segments:
        return []

    merged = []
    current = {
        "start_frame": segments[0]["frame_index"],
        "end_frame": segments[0]["frame_index"],
        "scores": [segments[0]["score"]],
        "detections": segments[0]["detections"],
    }

    for seg in segments[1:]:
        gap_frames = seg["frame_index"] - current["end_frame"]
        gap_seconds = gap_frames / fps
        if gap_seconds <= 2.0 and (current["end_frame"] - current["start_frame"]) / fps < max_duration:
            current["end_frame"] = seg["frame_index"]
            current["scores"].append(seg["score"])
            current["detections"].extend(seg["detections"])
        else:
            merged.append(current)
            current = {
                "start_frame": seg["frame_index"],
                "end_frame": seg["frame_index"],
                "scores": [seg["score"]],
                "detections": seg["detections"],
            }
    merged.append(current)

    # 过滤太短的片段，格式化输出
    highlights = []
    for idx, m in enumerate(merged):
        duration = (m["end_frame"] - m["start_frame"]) / fps
        if duration < min_duration and len(merged) > 1:
            continue
        avg_score = round(sum(m["scores"]) / len(m["scores"]), 4)
        # 生成原因描述
        top_classes = {}
        for d in m["detections"]:
            cls = d["class"]
            top_classes[cls] = top_classes.get(cls, 0) + 1
        top_reason = "、".join([f"{c}×{n}" for c, n in
                               sorted(top_classes.items(), key=lambda x: -x[1])[:3]])
        reason = f"检测到{top_reason}" if top_reason else "画面变化"

        highlights.append({
            "segment_id": idx + 1,
            "start_time": round(m["start_frame"] / fps, 2),
            "end_time": round(m["end_frame"] / fps, 2),
            "duration": round(duration, 2),
            "score": avg_score,
            "reason": reason,
        })

    return sorted(highlights, key=lambda x: -x["score"])[:TOP_N_SEGMENTS]


def extract_highlights(video_path, output_dir=None):
    """主函数：提取视频精彩片段"""
    import time
    start_time = time.time()

    # 1. 加载模型
    model = load_model()

    # 2. 采样帧
    sample_result = sample_frames(video_path)
    frames = sample_result["frames"]
    if not frames:
        return {"status": "failed", "error": "视频采样失败，无有效帧"}

    # 3. 逐帧检测 + 评分
    scored_segments = []
    prev_detections = None
    evidence_dir = None

    for frame_data in frames:
        detections = detect_frame(model, frame_data["image"])
        score = calc_excitement_score(detections, prev_detections)

        if score > 0.15:
            scored_segments.append({
                "frame_index": frame_data["frame_index"],
                "timestamp": frame_data["timestamp"],
                "score": score,
                "detections": detections,
            })
        prev_detections = detections

    # 4. 合并为连续片段
    highlights = merge_segments(
        scored_segments, sample_result["fps"],
        SEGMENT_MIN_DURATION, SEGMENT_MAX_DURATION
    )

    # 5. 保存证据帧
    if output_dir and highlights:
        evidence_dir = os.path.join(output_dir, "evidence")
        os.makedirs(evidence_dir, exist_ok=True)
        for h in highlights[:3]:  # 最多保存3个证据帧
            mid_time = (h["start_time"] + h["end_time"]) / 2
            cap = cv2.VideoCapture(video_path)
            cap.set(cv2.CAP_PROP_POS_MSEC, mid_time * 1000)
            ret, frame = cap.read()
            if ret:
                evidence_path = os.path.join(evidence_dir, f"evidence_{h['segment_id']}.jpg")
                cv2.imwrite(evidence_path, frame)
            cap.release()

    elapsed = round(time.time() - start_time, 2)

    return {
        "status": "completed",
        "video_info": {
            "fps": sample_result["fps"],
            "total_frames": sample_result["total_frames"],
            "duration": sample_result["duration"],
            "sampled_frames": sample_result["sampled_count"],
        },
        "highlights": highlights,
        "model": "yolo11n",
        "parameters": {
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "sample_interval": SAMPLE_INTERVAL,
            "top_n_segments": TOP_N_SEGMENTS,
        },
        "processing_time": elapsed,
    }

