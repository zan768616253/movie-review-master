from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.pipeline.common.json_io import load_json


LEGACY_SCENE_RE = re.compile(
    r"\[SCENE:\s*(\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)\s*-\s*(\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)\s*\]"
)
BROLL_LINE_RE = re.compile(r"\[BROLL:\s*([^\]]+?)\s*\]")
RANGE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)\s*-\s*(\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)"
)
STRUCTURAL_MARKER_RE = re.compile(r"^\s*\[(TITLE|HOOK|ACT\s*\d+[^\]]*|CLOSING)\]")


@dataclass
class SceneMarker:
    start: str | None
    end: str | None
    source: str | None = None
    confidence: float | None = None
    evidence: str | None = None
    characters: list[str] = field(default_factory=list)
    raw: str | None = None

    @property
    def is_ungrounded(self) -> bool:
        return (self.source or "").lower() == "ungrounded"


def normalize_timestamp(ts: str | None) -> str | None:
    if ts is None:
        return None
    return ts.replace(",", ".")


def timestamp_to_seconds(ts: str) -> float:
    normalized_ts = normalize_timestamp(ts)
    if normalized_ts is None:
        raise ValueError("Timestamp cannot be None")
    parts = normalized_ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(normalized_ts)


def seconds_to_timestamp(seconds: float) -> str:
    safe_seconds = max(0.0, seconds)
    hours = int(safe_seconds // 3600)
    minutes = int((safe_seconds % 3600) // 60)
    secs = safe_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def parse_broll_ranges(text: str) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    for match in RANGE_RE.finditer(text):
        start = normalize_timestamp(match.group(1))
        end = normalize_timestamp(match.group(2))
        if start is None or end is None:
            continue
        ranges.append((start, end))
    return ranges


def parse_scene_marker(line: str) -> SceneMarker | None:
    legacy_match = LEGACY_SCENE_RE.search(line)
    if legacy_match:
        return SceneMarker(
            start=normalize_timestamp(legacy_match.group(1)),
            end=normalize_timestamp(legacy_match.group(2)),
            source="legacy",
            raw=line.strip(),
        )

    stripped = line.strip()
    if not stripped.startswith("[SCENE ") or not stripped.endswith("]"):
        return None

    inner = stripped[len("[SCENE ") : -1].strip()
    if not inner:
        return None

    tokens = shlex.split(inner)
    attributes: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        attributes[key.strip().lower()] = value.strip()

    start = normalize_timestamp(attributes.get("start"))
    end = normalize_timestamp(attributes.get("end"))
    confidence_raw = attributes.get("confidence")
    confidence = float(confidence_raw) if confidence_raw is not None else None
    characters = split_packed_list(attributes.get("characters"))
    return SceneMarker(
        start=start,
        end=end,
        source=attributes.get("source"),
        confidence=confidence,
        evidence=attributes.get("evidence"),
        characters=characters,
        raw=stripped,
    )


def format_scene_marker(marker: SceneMarker) -> str:
    if marker.source in {None, "legacy"} and marker.start and marker.end:
        return f"[SCENE: {marker.start} - {marker.end}]"

    parts: list[str] = []
    if marker.start:
        parts.append(f"start={marker.start}")
    if marker.end:
        parts.append(f"end={marker.end}")
    if marker.source:
        parts.append(f"source={marker.source}")
    if marker.confidence is not None:
        parts.append(f"confidence={marker.confidence:.2f}")
    if marker.evidence:
        parts.append(f"evidence={quote_attr(marker.evidence)}")
    if marker.characters:
        parts.append(f"characters={quote_attr('|'.join(marker.characters))}")
    return f"[SCENE {' '.join(parts)}]"


def split_packed_list(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return []
    return [item.strip() for item in raw.split("|") if item.strip()]


def quote_attr(value: str) -> str:
    if any(ch.isspace() for ch in value) or '"' in value:
        escaped = value.replace('"', r'\"')
        return f'"{escaped}"'
    return value


def estimate_scene_duration(marker: SceneMarker) -> float | None:
    if marker.start is None or marker.end is None:
        return None
    return max(0.0, timestamp_to_seconds(marker.end) - timestamp_to_seconds(marker.start))


def overlapping_visual_segments(
    segments: Iterable[dict[str, object]],
    start: float,
    end: float,
) -> list[dict[str, object]]:
    overlaps: list[dict[str, object]] = []
    for segment in segments:
        segment_start = timestamp_to_seconds(str(segment["start"]))
        segment_end = timestamp_to_seconds(str(segment["end"]))
        if segment_start < end and segment_end > start:
            overlaps.append(segment)
    return overlaps


def load_visual_segments(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    segments: list[dict[str, object]] = load_json(path)
    for index, segment in enumerate(segments, 1):
        segment.setdefault("id", f"visual:{index:03d}")
    return segments


# Upper bound for a single visual segment. The VLM is instructed to emit 3-15s
# shot-level segments; anything longer is almost always a hallucinated end
# timestamp (we have seen Gemini return 9-hour segments on a 2-hour movie).
MAX_VISUAL_SEGMENT_DURATION_S = 30.0


@dataclass
class VisualSegmentDiagnostics:
    kept: int = 0
    dropped_bad_range: int = 0
    dropped_past_eof: int = 0
    dropped_too_long: int = 0
    clamped_to_eof: int = 0

    def as_summary(self) -> str:
        return (
            f"kept={self.kept} "
            f"clamped_to_eof={self.clamped_to_eof} "
            f"dropped_bad_range={self.dropped_bad_range} "
            f"dropped_past_eof={self.dropped_past_eof} "
            f"dropped_too_long={self.dropped_too_long}"
        )


def validate_visual_segments(
    segments: list[dict[str, object]],
    video_duration_s: float,
    max_segment_duration_s: float = MAX_VISUAL_SEGMENT_DURATION_S,
) -> tuple[list[dict[str, object]], VisualSegmentDiagnostics]:
    """Clamp and filter visual segments against the real video duration.

    VLMs routinely return timestamps that exceed the video length or span
    implausible ranges. This function is the single gate every downstream
    stage trusts: anything it returns is guaranteed to be inside
    [0, video_duration_s] and no longer than max_segment_duration_s.
    """
    diagnostics = VisualSegmentDiagnostics()
    validated: list[dict[str, object]] = []

    for segment in segments:
        try:
            start_s = timestamp_to_seconds(str(segment["start"]))
            end_s = timestamp_to_seconds(str(segment["end"]))
        except (KeyError, ValueError):
            diagnostics.dropped_bad_range += 1
            continue

        if end_s <= start_s:
            diagnostics.dropped_bad_range += 1
            continue

        if start_s >= video_duration_s:
            diagnostics.dropped_past_eof += 1
            continue

        if end_s > video_duration_s:
            end_s = video_duration_s
            segment = dict(segment)
            segment["end"] = seconds_to_timestamp(end_s)
            diagnostics.clamped_to_eof += 1

        if (end_s - start_s) > max_segment_duration_s:
            diagnostics.dropped_too_long += 1
            continue

        diagnostics.kept += 1
        validated.append(segment)

    return validated, diagnostics


def probe_media_duration(media_path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    output = result.stdout.strip()
    if not output:
        return None

    try:
        return float(output)
    except ValueError:
        return None


def get_video_duration(video_path: Path) -> float:
    duration = probe_media_duration(video_path)
    if duration is None:
        raise RuntimeError(f"Unable to determine media duration for {video_path}")
    return duration