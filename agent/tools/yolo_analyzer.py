"""YOLOResultAnalyzer — YOLO 检测结果解析器（Day 2 增强版）"""
from typing import Optional
from . import BaseTool

CLASS_MAP = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus",
    7: "truck", 9: "traffic light", 24: "backpack", 26: "handbag",
    28: "suitcase", 32: "sports ball", 39: "bottle", 41: "cup",
    56: "chair", 57: "couch", 59: "dining table", 62: "tv",
    63: "laptop", 64: "mouse", 67: "cell phone", 73: "book",
    74: "clock", 76: "vase", 77: "scissors", 78: "teddy bear",
    79: "hair drier",
}


class YOLOResultAnalyzer(BaseTool):
    """解析 YOLO 检测结果，提取目标类别、置信度、检测框，并计算统计信息"""
    name = "YOLOResultAnalyzer"; version = "2.0"
    description = "解析 YOLO 检测结果，提取目标类别、置信度、检测框，计算统计信息，识别场景特征"

    def validate_input(self, **kwargs) -> list[str]:
        missing = []
        if "detection_result" not in kwargs: missing.append("detection_result")
        return missing

    def execute(self, detection_result: Optional[dict] = None,
                class_map: Optional[dict] = None) -> dict:
        if not detection_result:
            return {"success": True, "objects_count": 0, "categories": {},
                    "avg_confidence": 0.0, "min_confidence": 0.0, "max_confidence": 0.0,
                    "detections": [], "summary": "未检测到任何目标（检测结果为空）",
                    "has_valid_detection": False, "scene_characteristics": "空画面", "error": None}

        result_map = class_map or CLASS_MAP; detections = []
        try:
            if "detections" in detection_result:
                for det in detection_result["detections"]:
                    cid = det.get("class_id", -1)
                    detections.append({
                        "class_id": cid,
                        "class_name": det.get("class_name", result_map.get(cid, f"class_{cid}")),
                        "confidence": float(det.get("confidence", 0.0)),
                        "bbox": det.get("bbox", [0, 0, 0, 0]),
                    })
            elif "boxes" in detection_result:
                boxes = detection_result.get("boxes", [])
                scores = detection_result.get("scores", [])
                class_ids = detection_result.get("class_ids", [])
                class_names = detection_result.get("class_names", [])
                for i in range(len(boxes)):
                    cid = class_ids[i] if i < len(class_ids) else -1
                    cname = class_names[i] if i < len(class_names) else result_map.get(cid, f"class_{cid}")
                    detections.append({
                        "class_id": cid, "class_name": cname,
                        "confidence": float(scores[i]) if i < len(scores) else 0.0,
                        "bbox": boxes[i],
                    })
            else:
                return {"success": False, "objects_count": 0, "categories": {},
                        "avg_confidence": 0.0, "min_confidence": 0.0, "max_confidence": 0.0,
                        "detections": [], "summary": "无法识别的检测结果格式",
                        "has_valid_detection": False, "scene_characteristics": "未知", "error": "格式错误"}
        except Exception as e:
            return {"success": False, "objects_count": 0, "categories": {},
                    "avg_confidence": 0.0, "min_confidence": 0.0, "max_confidence": 0.0,
                    "detections": [], "summary": f"解析失败：{str(e)}",
                    "has_valid_detection": False, "scene_characteristics": "未知", "error": str(e)}

        if not detections:
            return {"success": True, "objects_count": 0, "categories": {},
                    "avg_confidence": 0.0, "min_confidence": 0.0, "max_confidence": 0.0,
                    "detections": [], "summary": "未检测到任何目标",
                    "has_valid_detection": False, "scene_characteristics": "空画面", "error": None}

        confidences = [d["confidence"] for d in detections]
        categories = {}
        for d in detections:
            cat = d["class_name"]; categories[cat] = categories.get(cat, 0) + 1

        avg_conf = sum(confidences) / len(confidences)
        min_conf = min(confidences); max_conf = max(confidences)
        category_desc = "、".join([f"{k}x{v}" for k, v in sorted(categories.items(), key=lambda x: -x[1])])

        # 场景特征识别
        people_count = categories.get("person", 0)
        vehicle_types = {"car", "bus", "truck", "motorcycle", "bicycle"}
        vehicle_count = sum(categories.get(v, 0) for v in vehicle_types)
        if people_count > 0 and vehicle_count > 0:
            scene = "交通场景"
        elif people_count > 3:
            scene = "多人聚集场景"
        elif people_count > 0:
            scene = "人物场景"
        elif vehicle_count > 0:
            scene = "车辆场景"
        else:
            scene = "物体场景"

        summary = (f"共检测到 {len(detections)} 个目标，平均置信度 {avg_conf:.2f}，"
                    f"置信度范围 [{min_conf:.2f}~{max_conf:.2f}]。检测类别：{category_desc}。"
                    f"场景特征：{scene}。")

        return {"success": True, "objects_count": len(detections), "categories": categories,
                "avg_confidence": round(avg_conf, 4), "min_confidence": round(min_conf, 4),
                "max_confidence": round(max_conf, 4), "detections": detections,
                "summary": summary, "has_valid_detection": True,
                "scene_characteristics": scene, "error": None}
