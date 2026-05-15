"""Shared time, shot-boundary, and visual-segment helpers.

This module is the trust boundary between Stage 1 (VLM output) and the rest
of the pipeline:

- timestamp parse/format helpers (used everywhere timestamps cross module
  boundaries),
- ffprobe-based media duration probing,
- ``validate_visual_segments`` — clamps and filters Stage 1 output against
  the real video length so downstream stages can rely on every entry being
  in-range,
- ``build_shot_boundary_set`` — derives the canonical shot-cut universe
  from validated visual segments. Future pipeline stages assemble cuts
  from this set; the new "video-drives-audio" pipeline depends on it.

Anchor parsing, anchor validation, and per-style budget math used to live
here too. They were tied to the old `[ANCHOR]` script contract and were
removed when the audio-driven pipeline was retired in May 2026.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.common.json_io import load_json


_TIMESTAMP_TOKEN_PATTERN = r"(?:\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?|\d{1,2}:\d{2}(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_SIMPLE_TIMESTAMP_RE = re.compile(rf"^\s*{_TIMESTAMP_TOKEN_PATTERN}\s*$")
_TIMESTAMP_RANGE_RE = re.compile(
    rf"^\s*(?P<start>{_TIMESTAMP_TOKEN_PATTERN})\s*-\s*(?P<end>{_TIMESTAMP_TOKEN_PATTERN})\s*$"
)


def normalize_timestamp(ts: str | None) -> str | None:
    if ts is None:
        return None
    return ts.replace(",", ".")


def _is_simple_timestamp(value: object) -> bool:
    return isinstance(value, str) and _SIMPLE_TIMESTAMP_RE.match(value) is not None


def _split_timestamp_range(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = _TIMESTAMP_RANGE_RE.match(value)
    if match is None:
        return None
    start = normalize_timestamp(match.group("start"))
    end = normalize_timestamp(match.group("end"))
    if start is None or end is None:
        return None
    return start, end


def normalize_visual_segment_timestamps(segment: dict[str, object]) -> dict[str, object]:
    """Repair common VLM range formatting errors in Stage 1 segments.

    Gemini occasionally emits a full ``start - end`` range in one field
    (usually ``start``) while still populating the other field normally.
    Downstream stages expect separate timestamp fields, so normalize the
    segment before merge/validation consume it.
    """
    normalized = segment
    start_range = _split_timestamp_range(segment.get("start"))
    end_range = _split_timestamp_range(segment.get("end"))

    if start_range is not None:
        if normalized is segment:
            normalized = dict(segment)
        normalized["start"] = start_range[0]
        if not _is_simple_timestamp(segment.get("end")):
            normalized["end"] = start_range[1]

    if end_range is not None:
        if normalized is segment:
            normalized = dict(segment)
        if not _is_simple_timestamp(segment.get("start")):
            normalized["start"] = end_range[0]
        normalized["end"] = end_range[1]

    return normalized


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


# Real measured TTS speech rate for the pipeline's target voice
# (Qwen3-TTS Voice Clone on the niu-shu base voice). Mean across 57 chunks
# of real JJK0 niu-shu output: 6.74 ± 0.58 cps. Kept here because the new
# video-drives-audio pipeline still needs to estimate "how many chars of
# narration produce N seconds of audio" when scripting per rough-cut beat.
REAL_TTS_CPS = 6.74


# Sub-shots produced by Stage 1's scene-detect that are shorter than this
# threshold are treated as "false granularity" — micro-cuts inside what
# was editorially one continuous beat (rapid action, motion changes,
# camera shake). When ANY sub-shot of a Stage 1 segment falls below this
# bar after flicker-drop, the whole segment's inner cuts are collapsed.
COLLAPSE_INNER_CUTS_BELOW_S = 3.0


def should_collapse_segment_inner_cuts(
    segment: dict[str, object], min_subshot_s: float = 0.5
) -> bool:
    """Decide whether to merge a segment's inner shot boundaries.

    Returns True iff, after dropping flickers (sub-shots shorter than
    ``min_subshot_s``), any remaining sub-shot is still shorter than
    ``COLLAPSE_INNER_CUTS_BELOW_S``. In that case the segment is
    treated as one editorial beat throughout the pipeline.
    """
    try:
        seg_start = timestamp_to_seconds(str(segment["start"]))
        seg_end = timestamp_to_seconds(str(segment["end"]))
    except (KeyError, ValueError):
        return False
    if seg_end <= seg_start:
        return False

    inner: list[float] = []
    for raw in segment.get("shot_boundaries_s") or ():  # type: ignore[union-attr]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if seg_start < value < seg_end:
            inner.append(value)
    if not inner:
        return False
    inner.sort()

    cut_points = [seg_start, *inner, seg_end]
    surviving: list[tuple[float, float]] = []
    for i in range(len(cut_points) - 1):
        a, b = cut_points[i], cut_points[i + 1]
        if b - a >= min_subshot_s:
            surviving.append((a, b))
    if not surviving:
        return False
    return any((b - a) < COLLAPSE_INNER_CUTS_BELOW_S for a, b in surviving)


def build_shot_boundary_set(
    visual_segments: list[dict[str, object]] | None,
) -> list[float]:
    """Collect every shot-boundary timestamp from Stage 1's visual segments.

    The full set of "places where a shot cut happens" is:

    - every visual segment's start timestamp (excluding the very first one
      at t=0, which is the movie start, not a cut)
    - every visual segment's end timestamp
    - every entry in any segment's `shot_boundaries_s` list — UNLESS the
      segment qualifies for inner-cut collapse (see
      ``should_collapse_segment_inner_cuts``); in that case the inner
      cuts are omitted so consumers see one effective shot for the segment.

    Returns sorted, deduplicated absolute seconds.
    """
    if not visual_segments:
        return []

    boundaries: set[float] = set()
    for segment in visual_segments:
        try:
            start_s = timestamp_to_seconds(str(segment["start"]))
            end_s = timestamp_to_seconds(str(segment["end"]))
        except (KeyError, ValueError):
            continue
        if start_s > 0.001:
            boundaries.add(round(start_s, 3))
        boundaries.add(round(end_s, 3))
        if should_collapse_segment_inner_cuts(segment):
            continue
        for raw in segment.get("shot_boundaries_s") or ():  # type: ignore[union-attr]
            try:
                boundaries.add(round(float(raw), 3))
            except (TypeError, ValueError):
                continue
    return sorted(boundaries)


def load_visual_segments(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    segments: list[dict[str, object]] = load_json(path)
    for index, segment in enumerate(segments, 1):
        segment.setdefault("id", f"visual:{index:03d}")
    return segments


# Upper bound for a single visual segment. The VLM is instructed to emit
# event-based segments capped at 12s; anything beyond this safety margin is
# almost always a hallucinated end timestamp (we have seen Gemini return
# 9-hour segments on a 2-hour movie).
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
) -> tuple[list[dict[str, object]], VisualSegmentDiagnostics]:
    """Clamp and filter visual segments against the real video duration.

    VLMs routinely return timestamps that exceed the video length or span
    implausible ranges. This function is the single gate every downstream
    stage trusts: anything it returns is guaranteed to be inside
    [0, video_duration_s] and no longer than ``MAX_VISUAL_SEGMENT_DURATION_S``.
    """
    diagnostics = VisualSegmentDiagnostics()
    validated: list[dict[str, object]] = []

    for segment in segments:
        segment = normalize_visual_segment_timestamps(segment)
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

        if (end_s - start_s) > MAX_VISUAL_SEGMENT_DURATION_S:
            diagnostics.dropped_too_long += 1
            continue

        diagnostics.kept += 1
        validated.append(segment)

    return validated, diagnostics


def probe_media_duration(media_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Unable to determine media duration for {media_path}: ffprobe was not found on PATH. "
            "If you just installed FFmpeg with winget, restart your terminal or VS Code and try again."
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or "ffprobe did not provide an error message"
        raise RuntimeError(
            f"Unable to determine media duration for {media_path}: ffprobe exited with code {exc.returncode}. {details}"
        ) from exc

    output = result.stdout.strip()
    if not output:
        raise RuntimeError(
            f"Unable to determine media duration for {media_path}: ffprobe returned no duration."
        )

    try:
        return float(output)
    except ValueError as exc:
        raise RuntimeError(
            f"Unable to determine media duration for {media_path}: ffprobe returned a non-numeric duration: {output!r}."
        ) from exc


def get_video_duration(video_path: Path) -> float:
    return probe_media_duration(video_path)
