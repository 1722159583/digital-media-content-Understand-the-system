# test_cv.py - 本地测试CV算法（不需要Flask后端）

import json
import sys
from .cv_service import extract_highlights, load_model, sample_frames

def test_model_loading():
    """测试1: 模型加载"""
    print("[测试] 加载YOLO模型...")
    model = load_model()
    print(f"  ✅ 模型加载成功: {model.model_name}")
    return model

def test_sample_frames(video_path):
    """测试2: 视频帧采样"""
    print(f"[测试] 采样帧: {video_path}")
    result = sample_frames(video_path)
    print(f"  总帧数: {result['total_frames']}")
    print(f"  FPS: {result['fps']}")
    print(f"  时长: {result['duration']}s")
    print(f"  采样帧数: {result['sampled_count']}")
    return result

def test_extract_highlights(video_path):
    """测试3: 完整提取流程"""
    print(f"[测试] 提取精彩片段: {video_path}")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        result = extract_highlights(video_path, tmp)
    
    if result["status"] == "completed":
        print(f"  ✅ 处理成功")
        print(f"  耗时: {result['processing_time']}s")
        print(f"  视频信息: {result['video_info']}")
        print(f"  找到 {len(result['highlights'])} 个精彩片段:")
        for h in result["highlights"]:
            print(f"    片段{h['segment_id']}: {h['start_time']}s-{h['end_time']}s "
                  f"(时长{h['duration']}s) 评分:{h['score']} 原因:{h['reason']}")
    else:
        print(f"  ❌ 处理失败: {result.get('error', '未知错误')}")
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python test_cv.py <视频路径>")
        sys.exit(1)
    
    video = sys.argv[1]
    test_model_loading()
    print()
    test_extract_highlights(video)
