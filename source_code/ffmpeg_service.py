"""FFmpeg-based video clipping and concatenation helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class FFmpegError(RuntimeError):
    """An FFmpeg failure that is safe to expose through the API."""


def find_ffmpeg(executable: str | None = None) -> str | None:
    return shutil.which(executable or "ffmpeg")


def ffmpeg_available(executable: str | None = None) -> bool:
    ffmpeg = find_ffmpeg(executable)
    if not ffmpeg:
        return False
    try:
        completed = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _run(command: list[str]) -> None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FFmpegError(f"FFmpeg 执行失败：{exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "未知错误").strip().splitlines()
        raise FFmpegError(f"FFmpeg 处理失败：{detail[-1] if detail else '未知错误'}")


def _normalized_segments(
    highlights: list[dict[str, Any]],
    clip_duration: float | None,
    video_duration: float | None,
) -> list[dict[str, float | int]]:
    if not highlights:
        raise FFmpegError("分析报告中没有可剪辑的高光片段")
    if clip_duration is not None and not 1 <= clip_duration <= 60:
        raise FFmpegError("clip_duration 必须在 1 到 60 秒之间")

    duration_limit = max(float(video_duration or 0), 0)
    segments: list[dict[str, float | int]] = []
    for index, item in enumerate(highlights[:20], 1):
        try:
            source_start = max(float(item.get("start_time", 0)), 0)
            source_end = max(float(item.get("end_time", source_start)), source_start)
        except (TypeError, ValueError) as exc:
            raise FFmpegError("高光片段时间格式无效") from exc

        if clip_duration is not None:
            center = (source_start + source_end) / 2
            start = max(center - clip_duration / 2, 0)
            end = start + clip_duration
            if duration_limit and end > duration_limit:
                end = duration_limit
                start = max(0, end - clip_duration)
        else:
            start, end = source_start, source_end
            if duration_limit:
                end = min(end, duration_limit)
        if end - start < 0.1:
            continue
        segments.append({
            "segment_id": item.get("segment_id", index),
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "duration": round(end - start, 3),
        })
    if not segments:
        raise FFmpegError("高光片段时长无效，无法生成视频")
    return segments


def create_rough_cut(
    input_path: str | Path,
    output_path: str | Path,
    highlights: list[dict[str, Any]],
    *,
    clip_duration: float | None = None,
    video_duration: float | None = None,
    executable: str | None = None,
) -> dict[str, Any]:
    """Encode highlight segments to H.264/AAC and concatenate them into one MP4."""
    source = Path(input_path).resolve()
    target = Path(output_path).resolve()
    if not source.is_file() or source.stat().st_size == 0:
        raise FFmpegError("待处理的视频不存在或为空")
    ffmpeg = find_ffmpeg(executable)
    if not ffmpeg:
        raise FFmpegError("未找到 FFmpeg，请安装 FFmpeg 并将其加入 PATH")

    segments = _normalized_segments(highlights, clip_duration, video_duration)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rough_cut_", dir=target.parent) as temp_name:
        temp_dir = Path(temp_name)
        clips: list[Path] = []
        for index, segment in enumerate(segments, 1):
            clip = temp_dir / f"clip_{index:03d}.mp4"
            _run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", str(segment["start_time"]), "-i", str(source),
                "-t", str(segment["duration"]),
                "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                str(clip),
            ])
            clips.append(clip)

        concat_file = temp_dir / "concat.txt"
        concat_file.write_text(
            "".join(f"file '{clip.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for clip in clips),
            encoding="utf-8",
        )
        temporary_target = temp_dir / "rough_cut.mp4"
        _run([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-c", "copy", "-movflags", "+faststart", str(temporary_target),
        ])
        if not temporary_target.is_file() or temporary_target.stat().st_size == 0:
            raise FFmpegError("FFmpeg 未生成有效的粗剪视频")
        shutil.copy2(temporary_target, target)

    manifest = {
        "filename": target.name,
        "segment_count": len(segments),
        "duration": round(sum(float(item["duration"]) for item in segments), 3),
        "size": target.stat().st_size,
        "segments": segments,
    }
    target.with_suffix(".json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
