from abc import ABC, abstractmethod
from typing import List, Dict
from pathlib import Path
import subprocess

def get_video_duration(video_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def seconds_to_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def timestamp_to_seconds(ts: str) -> float:
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(ts)

def merge_segments(all_chunks_results: List[List[Dict]], chunk_duration_s: float) -> List[Dict]:
    merged = []
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
    def index_video(self, video_path: Path, characters: List[str], chunk_minutes: int, tmp_dir: Path) -> List[Dict]:
        """Index visual segments from a video and return a merged list of JSON segments."""
        pass
