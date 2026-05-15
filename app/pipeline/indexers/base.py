from __future__ import annotations

import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

from app.pipeline.common.script_contract import (
    get_video_duration,
    normalize_visual_segment_timestamps,
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
    """Shift chunk-local timestamps to absolute and concatenate.

    Each chunk emits segments with chunk-local timestamps (the VLM saw
    ``00:00:00.000`` at the chunk's own start). To produce a single
    movie-relative timeline we add ``chunk_index × chunk_duration_s`` to
    every timestamp on every segment.

    This includes ``shot_boundaries_s`` — the inner-cut annotations
    populated by ``snap_to_shot_boundaries``. They are emitted in
    chunk-local seconds and must be shifted alongside the segment's own
    ``start``/``end``, otherwise downstream consumers see boundaries
    pointing at the wrong moment in the movie. (Until 2026-04-30 this
    shift was missed, leaving 96% of inner cuts pointing one chunk
    earlier than their parent segment.)
    """
    merged: List[Dict] = []
    for i, chunk_results in enumerate(all_chunks_results):
        offset = i * chunk_duration_s
        for seg in chunk_results:
            seg = normalize_visual_segment_timestamps(seg)
            start_s = timestamp_to_seconds(seg["start"]) + offset
            end_s = timestamp_to_seconds(seg["end"]) + offset
            seg["start"] = seconds_to_timestamp(start_s)
            seg["end"] = seconds_to_timestamp(end_s)
            inner = seg.get("shot_boundaries_s")
            if isinstance(inner, list) and inner:
                shifted: List[float] = []
                for raw in inner:
                    try:
                        shifted.append(round(float(raw) + offset, 3))
                    except (TypeError, ValueError):
                        continue
                seg["shot_boundaries_s"] = shifted
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
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    cuts: List[float] = []
    for line in (result.stderr or "").splitlines():
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

    Also annotates each segment with `shot_boundaries_s`: the cut times
    that fall strictly inside the (snapped) segment. Stage 5 uses this
    list to find clean cut points for shot-aware video trimming, so it
    can absorb video-vs-audio slack without slicing mid-shot.

    If snapping would invert or zero-length a segment, the originals are
    kept. Non-snapping failures (missing fields, bad timestamps) are left
    to the downstream validator with no `shot_boundaries_s` annotation.
    """
    if not shot_boundaries:
        # Still annotate with an empty list so the schema stays consistent
        # for downstream consumers.
        return [{**seg, "shot_boundaries_s": []} for seg in segments]

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
            snapped.append({**seg, "shot_boundaries_s": []})
            continue

        # Boundaries strictly inside (new_start_s, new_end_s) — excluding
        # the segment's own start/end, which the snapper already aligned.
        inner_boundaries = [
            round(b, 3) for b in shot_boundaries if new_start_s < b < new_end_s
        ]

        new_seg = dict(seg)
        new_seg["start"] = seconds_to_timestamp(new_start_s)
        new_seg["end"] = seconds_to_timestamp(new_end_s)
        new_seg["shot_boundaries_s"] = inner_boundaries
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
