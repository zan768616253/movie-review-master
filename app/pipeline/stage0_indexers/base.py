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
]


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


class VisualIndexerStrategy(ABC):
    @abstractmethod
    def index_video(
        self,
        video_path: Path,
        tmp_dir: Path,
    ) -> List[Dict]:
        """Index visual segments from a video and return a merged list of JSON segments."""
