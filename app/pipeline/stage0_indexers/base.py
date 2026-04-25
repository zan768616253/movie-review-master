from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

from app.pipeline.common.script_contract import (
    get_video_duration,
    seconds_to_timestamp,
    timestamp_to_seconds,
)

__all__ = [
    "VisualIndexerStrategy",
    "get_video_duration",
    "seconds_to_timestamp",
    "timestamp_to_seconds",
    "merge_segments",
    "detect_shot_boundaries",
    "snap_to_shot_boundaries",
]


_PTS_TIME_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def merge_segments(all_chunks_results: List[List[Dict]], chunk_duration_s: float) -> List[Dict]:
    merged: List[Dict] = []
    for i, chunk_results in enumerate(all_chunks_results):
        offset = i * chunk_duration_s
        for seg in chunk_results:
            start_s = timestamp_to_seconds(seg["start"]) + offset
            end_s = timestamp_to_seconds(seg["end"]) + offset
            seg["start"] = seconds_to_timestamp(start_s)
            seg["end"] = seconds_to_timestamp(end_s)
            merged.append(seg)
    return merged


def detect_shot_boundaries(video_path: Path, threshold: float = 0.3) -> List[float]:
    """Detect shot cuts via ffmpeg's scene filter and return PTS times (seconds).

    The returned timestamps are relative to the start of ``video_path``. Callers
    that pass a chunk file get chunk-local timestamps, which already line up with
    the chunk-local timestamps the VLM sees (and emits) because Gemini chunks
    are extracted with ``-ss`` and therefore start at PTS 0.
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-an",
        "-f", "null",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    cuts: List[float] = []
    for line in result.stderr.splitlines():
        match = _PTS_TIME_RE.search(line)
        if match:
            cuts.append(float(match.group(1)))
    return sorted(cuts)


def _snap_timestamp(ts_s: float, boundaries: List[float], tolerance_s: float) -> float:
    if not boundaries:
        return ts_s
    nearest = min(boundaries, key=lambda b: abs(b - ts_s))
    if abs(nearest - ts_s) <= tolerance_s:
        return nearest
    return ts_s


def snap_to_shot_boundaries(
    segments: List[Dict],
    shot_boundaries: List[float],
    tolerance_s: float = 1.5,
) -> List[Dict]:
    """Snap each segment's start/end to the nearest shot boundary within tolerance.

    If snapping would invert or zero-length a segment, the originals are kept.
    Non-snapping failures (missing fields, bad timestamps) are left to the
    downstream validator.
    """
    if not shot_boundaries:
        return segments

    snapped: List[Dict] = []
    for seg in segments:
        try:
            start_s = timestamp_to_seconds(str(seg["start"]))
            end_s = timestamp_to_seconds(str(seg["end"]))
        except (KeyError, ValueError):
            snapped.append(seg)
            continue

        new_start_s = _snap_timestamp(start_s, shot_boundaries, tolerance_s)
        new_end_s = _snap_timestamp(end_s, shot_boundaries, tolerance_s)

        if new_start_s >= new_end_s:
            snapped.append(seg)
            continue

        new_seg = dict(seg)
        new_seg["start"] = seconds_to_timestamp(new_start_s)
        new_seg["end"] = seconds_to_timestamp(new_end_s)
        snapped.append(new_seg)
    return snapped


class VisualIndexerStrategy(ABC):
    @abstractmethod
    def index_video(
        self,
        video_path: Path,
        tmp_dir: Path,
    ) -> List[Dict]:
        """Index visual segments from a video and return a merged list of JSON segments."""
