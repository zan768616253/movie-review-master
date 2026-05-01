"""Render the draft review video from pipeline manifests.

Reads the Stage 3 voice manifest (`ranges` per chunk + audio timing), the
Stage 4 subtitle manifest (short timed subtitle cues), and the Stage 5 clip
manifest (one or more pre-extracted clips per chunk),
then for each chunk:

1. Plays the per-anchor hero clips in order, **shot-aware-trimmed** to
   match the chunk's audio duration.
2. Falls back to a still keyframe for closing chunks (no anchor).

Smart-trim uses shot boundaries from Stage 0's `visual_segments.json`
to land cuts at clean shot junctions whenever possible. The default state
is video > narration (planner uses a conservative chars/sec budget), so
trim runs on most chunks. The pipeline never modifies narration text or
audio — narration is sacred.

Outputs:

    <output_dir>/review.mp4               draft review video
    <output_dir>/review_subtitles.ass     styled narration subtitles burned into review.mp4
    <output_dir>/segments/segment_NNN.mp4 per-chunk visuals (kept on disk)
    <output_dir>/segments/segment_NNN.mp3 per-chunk audio split from voiceover
    <output_dir>/edit_manifest.json       handoff manifest for manual NLE editing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from app.pipeline.common.json_io import dump_json, load_json
from app.pipeline.common.script_contract import (
    get_video_duration,
    load_visual_segments,
    probe_media_duration,
    timestamp_to_seconds,
)
from app.pipeline.common.video_encoder import (
    encoder_ffmpeg_args,
    hwaccel_decode_args,
    resolve_encoder,
)


TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 30
DEFAULT_CLIP_MANIFEST = "clip_manifest.json"
DEFAULT_SUBTITLE_STYLE_NAME = "ReviewCaption"
DEFAULT_SUBTITLE_FONT_CANDIDATES = (
    ("Noto Sans CJK SC", Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")),
    ("Noto Sans CJK JP", Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")),
    ("DejaVu Sans", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
)
DEFAULT_SUBTITLE_FONTS_DIR = Path("/usr/share/fonts")
DEFAULT_SUBTITLE_FONT_SIZE = 54
DEFAULT_SUBTITLE_MARGIN_X = 140
DEFAULT_SUBTITLE_MARGIN_V = 64
DEFAULT_SUBTITLE_MAX_LINE_CHARS = 14
# Smart-trim accepts a shot-aligned cut whose video duration is within this
# fraction of audio_duration. Larger grace = more clean cuts, more residual
# overrun absorbed by post-handle extension or still fallback; smaller = more
# mid-shot cuts.
SMART_TRIM_GRACE_PCT = 0.05
# Multi-range trim spreads the excess across every range so each range is
# represented in the final chunk. We refuse to cut a range below this floor
# — anything shorter is a flicker, not a shot. If the spread can't honor the
# floor across all ranges, we drop the last range and recurse.
MIN_KEEP_PER_RANGE_S = 1.5
# Softer pacing preference layered on top of the hard floor above: if trim
# would leave only a tiny tail fragment and removing that last switch would
# cost at most a brief still/extension fill, prefer the longer hold.
PREFERRED_MIN_KEEP_PER_RANGE_S = 2.5
MAX_TAIL_FREEZE_SHORTFALL_S = 1.25
# Post-render safety net: surgical splice fires when the rendered chunk
# contains more than this many seconds of black frames. Pre-render passes
# (source-level range splitting + extension clamp) handle most cases
# upstream — this is for residual fades that only manifest after concat.
BLACK_FRAME_THRESHOLD_S = 3.0
BLACK_FRAME_PIC_TH = 0.95
BLACK_FRAME_MIN_INTERVAL_S = 0.4
# When source-level black splitting drops sub-ranges shorter than this,
# the resulting fragment is too brief to read as a shot.
MIN_NON_BLACK_SUB_RANGE_S = 1.5
# Safety overshoot for the trailing closing-chunk still. Manifest audio
# timings are computed from raw-WAV durations (pre-loudnorm + pre-MP3
# encoding), so the actual voiceover.mp3 can run a few hundred ms longer
# than `audio_end_s` of the last chunk. We size the closing still to the
# real MP3 tail plus this pad so Stage 7's `-shortest` mux can never run
# out of video before the narration ends.
CLOSING_TAIL_PAD_S = 0.5
# Minimum length of a source-movie tail clip before we'll use it for the
# closing chunk. If the last anchor lands less than this from the end of
# the movie, the tail would be a flicker — fall back to the still.
MIN_CLOSING_TAIL_S = 1.0


# --- ffmpeg helpers -------------------------------------------------------


def normalize_scale_filter() -> str:
    # Zoom-and-crop fill (no letterbox): scale source to fully cover the
    # 1920x1080 canvas, then center-crop the overflow. Cinemascope (e.g.
    # 1920x816) loses ~16% from each side; in exchange, no black bars
    # ship in the YouTube upload.
    return (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT}:(iw-{TARGET_WIDTH})/2:(ih-{TARGET_HEIGHT})/2,"
        f"setsar=1,fps={TARGET_FPS}"
    )


def render_excerpt(
    source_path: Path,
    start_s: float,
    target_duration: float,
    out_path: Path,
    codec: str,
) -> None:
    """Re-encode a slice of a video into the project's normalized 1080p/30fps format.

    `start_s` is an offset into `source_path`; ffmpeg treats the source as
    just bytes, so this works whether source is the full movie or a
    pre-extracted clip file.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *hwaccel_decode_args(codec),
        "-ss", f"{max(0.0, start_s):.3f}",
        "-i", str(source_path),
        "-t", f"{target_duration:.3f}",
        "-vf", normalize_scale_filter(),
        *encoder_ffmpeg_args(codec),
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def render_stillframe_segment(
    image_path: Path,
    target_duration: float,
    out_path: Path,
    codec: str,
) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1",
        "-framerate", str(TARGET_FPS),
        "-i", str(image_path),
        "-t", f"{target_duration:.3f}",
        "-vf", normalize_scale_filter(),
        *encoder_ffmpeg_args(codec),
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def concat_segments(segment_paths: list[Path], out_path: Path) -> None:
    list_file = out_path.parent / f"{out_path.stem}.concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in segment_paths),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:v", "copy",
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    list_file.unlink(missing_ok=True)


def split_voiceover_to_segment(
    voiceover_path: Path,
    audio_start_s: float,
    audio_end_s: float,
    out_path: Path,
) -> None:
    """Cut a per-chunk MP3 from the concatenated voiceover for the editor handoff."""
    duration_s = max(0.0, audio_end_s - audio_start_s)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{audio_start_s:.3f}",
        "-i", str(voiceover_path),
        "-t", f"{duration_s:.3f}",
        "-c:a", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def detect_black_intervals(
    video_path: Path,
    pic_th: float = BLACK_FRAME_PIC_TH,
    min_interval_s: float = BLACK_FRAME_MIN_INTERVAL_S,
) -> list[tuple[float, float]]:
    """Run ``ffmpeg blackdetect`` and return ``(start_s, end_s)`` intervals.

    ``pic_th`` is the fraction of pixels that must fall below the (default
    0.10) luma threshold for a frame to count as black. ``min_interval_s``
    rejects single-frame transitions — anything shorter than this isn't
    flagged. blackdetect prints lines like::

        [blackdetect @ 0xff] black_start:5.0 black_end:11.0 black_duration:6.0

    on stderr; we parse the timestamps out.
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"blackdetect=d={min_interval_s}:pic_th={pic_th}",
        "-an", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    intervals: list[tuple[float, float]] = []
    for line in proc.stderr.splitlines():
        if "blackdetect" not in line or "black_start" not in line:
            continue
        start: float | None = None
        end: float | None = None
        for token in line.split():
            if token.startswith("black_start:"):
                try:
                    start = float(token.split(":", 1)[1])
                except ValueError:
                    pass
            elif token.startswith("black_end:"):
                try:
                    end = float(token.split(":", 1)[1])
                except ValueError:
                    pass
        if start is not None and end is not None and end > start:
            intervals.append((start, end))
    return intervals


def compute_clip_black_intervals(clip_path: Path) -> list[tuple[float, float]]:
    """Return clip-relative ``(start_s, end_s)`` intervals of black frames.

    Each interval is measured from the start of the clip (offset 0). Used
    to split source ranges and clamp extensions before render, so the
    pipeline never renders a fade-to-black that the source movie embeds.
    """
    return detect_black_intervals(clip_path)


def subtract_black_from_range(
    range_start_abs: float,
    range_end_abs: float,
    extracted_start_abs: float,
    clip_blacks_rel: list[tuple[float, float]],
    min_keep_s: float = MIN_NON_BLACK_SUB_RANGE_S,
) -> list[tuple[float, float]]:
    """Split ``[range_start_abs, range_end_abs]`` around any black intervals
    that intersect it.

    ``clip_blacks_rel`` are clip-relative offsets (where 0 is the clip's
    first frame, equivalent to absolute time ``extracted_start_abs``).
    Returns absolute-time non-black sub-ranges, dropping any sub-range
    shorter than ``min_keep_s`` (a flicker, not a shot).

    If the entire range is black, returns ``[]`` — caller should drop
    this range from the chunk and fall back to other ranges or a still.
    """
    if not clip_blacks_rel:
        return [(range_start_abs, range_end_abs)]

    # Convert clip-relative blacks to absolute time, intersect with [range].
    abs_blacks: list[tuple[float, float]] = []
    for b_start_rel, b_end_rel in clip_blacks_rel:
        bs = extracted_start_abs + b_start_rel
        be = extracted_start_abs + b_end_rel
        clipped_start = max(bs, range_start_abs)
        clipped_end = min(be, range_end_abs)
        if clipped_end > clipped_start:
            abs_blacks.append((clipped_start, clipped_end))
    if not abs_blacks:
        return [(range_start_abs, range_end_abs)]

    abs_blacks.sort()
    out: list[tuple[float, float]] = []
    cursor = range_start_abs
    for bs, be in abs_blacks:
        if bs - cursor >= min_keep_s:
            out.append((cursor, bs))
        cursor = max(cursor, be)
    if range_end_abs - cursor >= min_keep_s:
        out.append((cursor, range_end_abs))
    return out


def clamp_extension_against_black(
    range_end_abs: float,
    extended_end_abs: float,
    extracted_start_abs: float,
    clip_blacks_rel: list[tuple[float, float]],
) -> float:
    """Clamp an extension so it never enters a black region.

    Returns the new ``extended_end_abs``. If a black interval starts
    inside ``(range_end_abs, extended_end_abs]``, we cap the extension
    at the black's start. The shortfall is filled with a still by the
    caller.
    """
    if extended_end_abs <= range_end_abs:
        return range_end_abs
    for b_start_rel, _b_end_rel in clip_blacks_rel:
        b_start_abs = extracted_start_abs + b_start_rel
        if range_end_abs < b_start_abs <= extended_end_abs:
            return min(extended_end_abs, b_start_abs)
    return extended_end_abs


def splice_black_with_stills(
    segment_path: Path,
    black_intervals: list[tuple[float, float]],
    audio_duration_s: float,
    keyframe_path: Path,
    segments_dir: Path,
    chunk_index: int,
    codec: str,
) -> None:
    """Replace black intervals inside ``segment_path`` with keyframe stills.

    Builds a sequence of parts — alternating non-black slices extracted
    from the existing segment and stills for each black gap — then
    concatenates back over ``segment_path``. Good footage outside the
    black windows is preserved; only the black is replaced.
    """
    if not black_intervals:
        return

    parts: list[Path] = []
    cursor = 0.0
    for i, (b_start, b_end) in enumerate(black_intervals):
        if b_start > cursor + 0.01:
            keep = segments_dir / f"segment_{chunk_index:03d}_splice{i:02d}_keep.mp4"
            render_excerpt(segment_path, cursor, b_start - cursor, keep, codec)
            parts.append(keep)
        still_part = segments_dir / f"segment_{chunk_index:03d}_splice{i:02d}_still.mp4"
        render_stillframe_segment(keyframe_path, b_end - b_start, still_part, codec)
        parts.append(still_part)
        cursor = b_end
    if cursor < audio_duration_s - 0.01:
        tail = segments_dir / f"segment_{chunk_index:03d}_splice_tail.mp4"
        render_excerpt(segment_path, cursor, audio_duration_s - cursor, tail, codec)
        parts.append(tail)

    spliced = segments_dir / f"segment_{chunk_index:03d}_spliced.mp4"
    concat_segments(parts, spliced)
    spliced.replace(segment_path)
    for p in parts:
        p.unlink(missing_ok=True)


def mux_audio(video_path: Path, audio_path: Path, out_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def choose_subtitle_font_family() -> str:
    for family, font_path in DEFAULT_SUBTITLE_FONT_CANDIDATES:
        if font_path.exists():
            return family
    return "sans-serif"


def format_ass_timestamp(seconds: float) -> str:
    total_centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(total_centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def normalize_subtitle_text(text: object) -> str:
    if not isinstance(text, str):
        return ""
    collapsed = " ".join(part.strip() for part in text.splitlines() if part.strip())
    return collapsed.replace("\\", r"\\").replace("{", "(").replace("}", ")")


def break_subtitle_line(text: str, max_chars: int = DEFAULT_SUBTITLE_MAX_LINE_CHARS) -> str:
    if len(text) <= max_chars:
        return text

    midpoint = len(text) // 2
    break_candidates = [
        index + 1
        for index, ch in enumerate(text)
        if ch in "，、：:,。！？!?；; "
    ]
    if break_candidates:
        break_at = min(break_candidates, key=lambda candidate: abs(candidate - midpoint))
    else:
        break_at = max_chars
    if text[break_at - 1] == " ":
        return f"{text[:break_at - 1]}\\N{text[break_at:].lstrip()}"
    return f"{text[:break_at]}\\N{text[break_at:]}"


def subtitle_entry_times(entry: dict[str, object]) -> tuple[float, float]:
    if "start_s" in entry and "end_s" in entry:
        return (
            coerce_manifest_seconds(entry["start_s"], context="start_s"),
            coerce_manifest_seconds(entry["end_s"], context="end_s"),
        )
    return (
        coerce_manifest_seconds(entry["audio_start_s"], context="audio_start_s"),
        coerce_manifest_seconds(entry["audio_end_s"], context="audio_end_s"),
    )


def build_subtitle_dialogue_lines(entries: list[dict[str, object]]) -> list[str]:
    dialogue_lines: list[str] = []
    for entry in entries:
        text = break_subtitle_line(normalize_subtitle_text(entry.get("text", "")))
        if not text:
            continue
        try:
            start_s, end_s = subtitle_entry_times(entry)
        except (KeyError, ValueError):
            continue
        if end_s <= start_s:
            continue
        dialogue_lines.append(
            "Dialogue: 0,"
            f"{format_ass_timestamp(start_s)},"
            f"{format_ass_timestamp(end_s)},"
            f"{DEFAULT_SUBTITLE_STYLE_NAME},,0,0,0,,{text}"
        )
    return dialogue_lines


def write_subtitle_script(entries: list[dict[str, object]], out_path: Path) -> bool:
    dialogue_lines = build_subtitle_dialogue_lines(entries)
    if not dialogue_lines:
        out_path.unlink(missing_ok=True)
        return False

    font_family = choose_subtitle_font_family()
    script = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {TARGET_WIDTH}",
        f"PlayResY: {TARGET_HEIGHT}",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: "
        f"{DEFAULT_SUBTITLE_STYLE_NAME},{font_family},{DEFAULT_SUBTITLE_FONT_SIZE},"
        "&H00F4F4F4,&H00F4F4F4,&H00181818,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,3,0,2,{DEFAULT_SUBTITLE_MARGIN_X},{DEFAULT_SUBTITLE_MARGIN_X},{DEFAULT_SUBTITLE_MARGIN_V},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *dialogue_lines,
        "",
    ])
    out_path.write_text(script, encoding="utf-8")
    return True


def build_subtitle_filter(subtitle_path: Path) -> str:
    filter_expr = f"ass={subtitle_path.resolve()}"
    if DEFAULT_SUBTITLE_FONTS_DIR.exists():
        filter_expr += f":fontsdir={DEFAULT_SUBTITLE_FONTS_DIR}"
    return filter_expr


def burn_subtitles(
    video_path: Path,
    subtitle_path: Path,
    out_path: Path,
    codec: str,
) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *hwaccel_decode_args(codec),
        "-i", str(video_path),
        "-vf", build_subtitle_filter(subtitle_path),
        *encoder_ffmpeg_args(codec),
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


# --- Manifest loaders -----------------------------------------------------


def default_clip_manifest_path(clips_dir: Path) -> Path:
    return clips_dir.parent / DEFAULT_CLIP_MANIFEST


def coerce_manifest_index(value: object, *, context: str) -> int:
    if not isinstance(value, (int, str)):
        raise ValueError(f"{context} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{context} must be an integer") from exc


def coerce_manifest_seconds(value: object, *, context: str) -> float:
    if not isinstance(value, (int, float, str)):
        raise ValueError(f"{context} must be numeric")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{context} must be numeric") from exc


def load_render_manifest(path: Path) -> list[dict[str, object]]:
    """Load Stage 3's voice manifest (`ranges` + audio timing per chunk)."""
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid manifest JSON in {path}: {exc}") from exc

    if not isinstance(payload, list):
        raise ValueError(f"Manifest payload must be a JSON array: {path}")

    manifest: list[dict[str, object]] = []
    for n, entry in enumerate(payload, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest entry {n} must be a JSON object: {path}")
        missing = [f for f in ("index", "audio_start_s", "audio_end_s") if f not in entry]
        if missing:
            raise ValueError(
                f"Manifest entry {n} missing required fields {', '.join(missing)}: {path}"
            )
        try:
            coerce_manifest_index(entry["index"], context=f"Manifest entry {n} index")
            coerce_manifest_seconds(entry["audio_start_s"], context=f"Manifest entry {n} audio_start_s")
            coerce_manifest_seconds(entry["audio_end_s"], context=f"Manifest entry {n} audio_end_s")
        except ValueError as exc:
            raise ValueError(f"{exc}: {path}") from exc
        manifest.append(entry)
    return manifest


def load_clip_manifest(path: Path | None) -> dict[int, dict[str, object]]:
    """Load Stage 5's clip manifest (per-anchor list of range clips)."""
    if path is None or not path.exists():
        return {}
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid clip manifest JSON in {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"Clip manifest payload must be a JSON array: {path}")

    manifest: dict[int, dict[str, object]] = {}
    for n, entry in enumerate(payload, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Clip manifest entry {n} must be a JSON object: {path}")
        if "index" not in entry:
            raise ValueError(f"Clip manifest entry {n} missing required field index: {path}")
        manifest[coerce_manifest_index(entry["index"], context=f"Clip manifest entry {n} index")] = entry
    return manifest


def load_subtitle_manifest(path: Path | None) -> list[dict[str, object]]:
    """Load Stage 4 subtitle cues or return an empty list when absent."""
    if path is None or not path.exists():
        return []
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid subtitle manifest JSON in {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"Subtitle manifest payload must be a JSON array: {path}")
    entries: list[dict[str, object]] = []
    for n, entry in enumerate(payload, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Subtitle manifest entry {n} must be a JSON object: {path}")
        missing = [field for field in ("text", "start_s", "end_s") if field not in entry]
        if missing:
            raise ValueError(
                f"Subtitle manifest entry {n} missing required fields {', '.join(missing)}: {path}"
            )
        entries.append(entry)
    return entries


def collect_shot_boundaries_for_range(
    range_start_s: float,
    range_end_s: float,
    visual_segments: list[dict[str, object]],
) -> list[float]:
    """Return shot-boundary cut times (absolute seconds) inside [range_start_s, range_end_s].

    Visual segments may overlap the requested range; we union their
    `shot_boundaries_s` lists, then keep only boundaries that fall
    strictly inside the range. Returns sorted, deduplicated.
    """
    boundaries: set[float] = set()
    for seg in visual_segments:
        try:
            seg_start = timestamp_to_seconds(str(seg["start"]))
            seg_end = timestamp_to_seconds(str(seg["end"]))
        except (KeyError, ValueError):
            continue
        if seg_end < range_start_s or seg_start > range_end_s:
            continue
        for b in seg.get("shot_boundaries_s") or []:  # type: ignore[union-attr]
            try:
                bf = float(b)
            except (TypeError, ValueError):
                continue
            if range_start_s < bf < range_end_s:
                boundaries.add(round(bf, 3))
    return sorted(boundaries)


def _ranges_total_duration(ranges_s: list[tuple[float, float]]) -> float:
    return sum(max(0.0, end - start) for start, end in ranges_s)


# --- Smart trim -----------------------------------------------------------


def _plan_smart_trim_core(
    ranges_s: list[tuple[float, float]],
    shot_boundaries_per_range: list[list[float]],
    audio_duration_s: float,
    grace_pct: float = SMART_TRIM_GRACE_PCT,
) -> tuple[list[tuple[float, float]], str]:
    """Decide how to trim multi-range hero video to match audio duration.

    Returns ``(kept_ranges, trim_kind)`` where ``trim_kind`` is one of:
      - ``"exact"``               — total ≈ audio_duration (within grace).
      - ``"shot-aligned-tail"``   — single range trimmed at a shot boundary.
      - ``"mid-shot-tail"``       — single range trimmed mid-shot.
      - ``"shot-aligned-spread"`` — multi-range; cut distributed across
            ranges, all snaps landed on shot boundaries.
      - ``"mid-shot-spread"``     — multi-range; some snaps fell mid-shot.
      - ``"extension-needed"``    — total < audio; caller should extend
            from Stage 4 post-handles and freeze only if still short.

    For a **single range**, trim from the tail and (when possible) snap
    to a shot boundary inside the range. Latest-shot-boundary wins to
    preserve the payoff frame.

    For **multiple ranges**, the planner has chosen a chronological
    sequence ("first I show A, then B, then C"). Tail-greedy trim used
    to drop B and C entirely when total > audio, leaving narration about
    B and C playing over A's footage. Instead we now distribute the
    excess proportionally across every range (weighted by each range's
    trimmable budget), so every range is represented in the rendered
    chunk. Each per-range cut snaps to a shot boundary if one is in
    range. If even maxing out trim on every range can't absorb the
    excess (i.e. the planner picked ~3× too much footage), we fall back
    to dropping the last range and recursing.
    """
    if not ranges_s:
        return [], "exact"

    total = sum(end - start for start, end in ranges_s)
    grace = grace_pct * audio_duration_s

    if total + grace < audio_duration_s:
        return ranges_s, "extension-needed"
    if total <= audio_duration_s + grace:
        return ranges_s, "exact"

    excess = total - audio_duration_s

    # --- Single-range path: trim only from this range's tail.
    if len(ranges_s) == 1:
        rs, re_ = ranges_s[0]
        new_end = max(rs, re_ - excess)
        candidates = shot_boundaries_per_range[0] if shot_boundaries_per_range else []
        in_window = [b for b in candidates if rs < b <= new_end + grace]
        if in_window:
            return [(rs, max(in_window))], "shot-aligned-tail"
        return [(rs, new_end)], "mid-shot-tail"

    # --- Multi-range path: distribute excess across every range.
    durations = [end - start for start, end in ranges_s]
    budgets = [max(0.0, d - MIN_KEEP_PER_RANGE_S) for d in durations]
    total_budget = sum(budgets)

    # Even max trim can't fit; the planner over-anchored. Drop the last
    # range and recurse — same fallback as before, but now reached only
    # when proportional spread is provably impossible.
    if total_budget + grace < excess:
        return _plan_smart_trim_core(
            ranges_s[:-1],
            shot_boundaries_per_range[:-1],
            audio_duration_s,
            grace_pct,
        )

    new_ranges: list[tuple[float, float]] = []
    any_snapped = False
    any_mid_shot = False
    for i, ((rs, re_), budget) in enumerate(zip(ranges_s, budgets)):
        cut = excess * (budget / total_budget) if total_budget > 0 else 0.0
        if cut <= grace:
            # Negligible cut for this range — keep it intact rather than
            # snapping needlessly to a nearby shot boundary.
            new_ranges.append((rs, re_))
            continue
        new_end = re_ - cut
        candidates = shot_boundaries_per_range[i] if i < len(shot_boundaries_per_range) else []
        in_window = [b for b in candidates if rs < b <= new_end + grace]
        if in_window:
            new_ranges.append((rs, max(in_window)))
            any_snapped = True
        else:
            new_ranges.append((rs, new_end))
            any_mid_shot = True

    if any_mid_shot:
        return new_ranges, "mid-shot-spread"
    if any_snapped:
        return new_ranges, "shot-aligned-spread"
    return new_ranges, "exact"


def _maybe_reduce_twitchy_tail(
    ranges_s: list[tuple[float, float]],
    shot_boundaries_per_range: list[list[float]],
    audio_duration_s: float,
    kept_ranges: list[tuple[float, float]],
    kind: str,
    grace_pct: float = SMART_TRIM_GRACE_PCT,
) -> tuple[list[tuple[float, float]], str]:
    """Prefer fewer switches when trim leaves only a tiny tail fragment.

    This is intentionally conservative: it only fires on multi-range trim
    results (not exact-fit or extension-needed cases) and only when dropping
    the tail-most range would create at most a brief shortfall that Stage 5
    can cover with the existing extension/freeze fallback.
    """
    if kind in {"exact", "extension-needed"} or len(ranges_s) <= 1 or len(kept_ranges) <= 1:
        return kept_ranges, kind

    source_ranges = list(ranges_s)
    source_shots = list(shot_boundaries_per_range)
    best_ranges = kept_ranges
    best_kind = kind

    while len(source_ranges) > 1 and len(best_ranges) > 1:
        tail_duration_s = max(0.0, best_ranges[-1][1] - best_ranges[-1][0])
        if tail_duration_s >= PREFERRED_MIN_KEEP_PER_RANGE_S:
            break

        candidate_source_ranges = source_ranges[:-1]
        candidate_source_shots = source_shots[:-1]
        candidate_ranges, candidate_kind = _plan_smart_trim_core(
            candidate_source_ranges,
            candidate_source_shots,
            audio_duration_s,
            grace_pct,
        )
        candidate_shortfall_s = max(
            0.0,
            audio_duration_s - _ranges_total_duration(candidate_ranges),
        )
        if candidate_shortfall_s > MAX_TAIL_FREEZE_SHORTFALL_S:
            break
        if len(candidate_ranges) >= len(best_ranges):
            break

        best_ranges = candidate_ranges
        best_kind = candidate_kind
        source_ranges = candidate_source_ranges
        source_shots = candidate_source_shots

    return best_ranges, best_kind


def plan_smart_trim(
    ranges_s: list[tuple[float, float]],
    shot_boundaries_per_range: list[list[float]],
    audio_duration_s: float,
    grace_pct: float = SMART_TRIM_GRACE_PCT,
) -> tuple[list[tuple[float, float]], str]:
    kept_ranges, kind = _plan_smart_trim_core(
        ranges_s,
        shot_boundaries_per_range,
        audio_duration_s,
        grace_pct,
    )
    return _maybe_reduce_twitchy_tail(
        ranges_s,
        shot_boundaries_per_range,
        audio_duration_s,
        kept_ranges,
        kind,
        grace_pct,
    )


# --- Render loop ----------------------------------------------------------


def _entry_ranges_seconds(entry: dict[str, object]) -> list[tuple[float, float]]:
    """Extract `(start_s, end_s)` pairs from a Stage 3 manifest entry's `ranges`."""
    raw = entry.get("ranges") or []
    out: list[tuple[float, float]] = []
    for pair in raw:  # type: ignore[union-attr]
        try:
            start_ts, end_ts = pair
            out.append((timestamp_to_seconds(str(start_ts)), timestamp_to_seconds(str(end_ts))))
        except (TypeError, ValueError):
            continue
    return out


def _render_kept_ranges_from_clip_manifest(
    kept_ranges_s: list[tuple[float, float]],
    clip_meta_ranges: list[dict[str, object]],
    clips_dir: Path,
    segments_dir: Path,
    chunk_index: int,
    codec: str,
) -> list[Path]:
    """Render each kept sub-range using the matching pre-extracted clip file.

    For each kept range, find the original Stage-4 range whose extraction
    contains it, then render an offset-into-clip slice of the right length.
    Returns the list of part files produced.
    """
    part_paths: list[Path] = []
    for part_idx, (kept_start_s, kept_end_s) in enumerate(kept_ranges_s):
        if kept_end_s <= kept_start_s + 0.01:
            continue
        meta = _find_clip_meta_for_range(clip_meta_ranges, kept_start_s, kept_end_s)
        if meta is None:
            continue
        clip_path = clips_dir / str(meta["clip_path"])
        extracted_start_s = timestamp_to_seconds(str(meta["extracted_start"]))
        offset_s = max(0.0, kept_start_s - extracted_start_s)
        duration_s = kept_end_s - kept_start_s
        part_path = segments_dir / f"segment_{chunk_index:03d}_part{part_idx:02d}_hero.mp4"
        render_excerpt(clip_path, offset_s, duration_s, part_path, codec)
        part_paths.append(part_path)
    return part_paths


def _extend_ranges_to_audio_duration(
    ranges_s: list[tuple[float, float]],
    clip_meta_ranges: list[dict[str, object]],
    audio_duration_s: float,
    clip_blacks_by_path: dict[str, list[tuple[float, float]]] | None = None,
) -> tuple[list[tuple[float, float]], float]:
    """Extend the last kept range into its extracted post-handle when audio overruns.

    Returns ``(extended_ranges, remaining_shortfall_s)``. Any remaining
    shortfall must be filled with a still segment so the rendered chunk
    duration still matches narration exactly.

    When ``clip_blacks_by_path`` is supplied, the extension is clamped at
    the first black boundary encountered inside the post-handle. This
    prevents fade-to-black extensions (the original chunk-22 bug).
    """
    planned_ranges = list(ranges_s)
    shortfall_s = audio_duration_s - _ranges_total_duration(planned_ranges)
    if shortfall_s <= 0.01 or not planned_ranges:
        return planned_ranges, 0.0

    last_start_s, last_end_s = planned_ranges[-1]
    last_meta = _find_clip_meta_for_range(clip_meta_ranges, last_start_s, last_end_s)
    if last_meta is None and clip_meta_ranges:
        last_meta = clip_meta_ranges[-1]
    if last_meta is None:
        return planned_ranges, shortfall_s

    try:
        extracted_end_s = timestamp_to_seconds(str(last_meta["extracted_end"]))
    except (KeyError, ValueError):
        return planned_ranges, shortfall_s

    extended_end_s = min(extracted_end_s, last_end_s + shortfall_s)
    if clip_blacks_by_path is not None:
        try:
            extracted_start_s = timestamp_to_seconds(str(last_meta["extracted_start"]))
        except (KeyError, ValueError):
            extracted_start_s = None
        clip_path_str = str(last_meta.get("clip_path", ""))
        clip_blacks_rel = clip_blacks_by_path.get(clip_path_str, [])
        if extracted_start_s is not None and clip_blacks_rel:
            extended_end_s = clamp_extension_against_black(
                last_end_s, extended_end_s, extracted_start_s, clip_blacks_rel,
            )
    gained_s = max(0.0, extended_end_s - last_end_s)
    if gained_s > 0.0:
        planned_ranges[-1] = (last_start_s, extended_end_s)
        shortfall_s -= gained_s
    return planned_ranges, max(0.0, shortfall_s)


def _find_clip_meta_for_range(
    clip_meta_ranges: list[dict[str, object]],
    kept_start_s: float,
    kept_end_s: float,
) -> dict[str, object] | None:
    """Locate the Stage-4 range metadata whose extraction window covers this kept slice."""
    for meta in clip_meta_ranges:
        try:
            ext_start_s = timestamp_to_seconds(str(meta["extracted_start"]))
            ext_end_s = timestamp_to_seconds(str(meta["extracted_end"]))
        except (KeyError, ValueError):
            continue
        if ext_start_s <= kept_start_s and ext_end_s >= kept_end_s:
            return meta
    return None


def _choose_keyframe(
    keyframes_dir: Path,
    chunk_index: int,
    last_anchor_index: int | None,
) -> Path | None:
    direct = keyframes_dir / f"keyframe_{chunk_index:03d}.jpg"
    if direct.exists():
        return direct
    if last_anchor_index is not None:
        fallback = keyframes_dir / f"keyframe_{last_anchor_index:03d}.jpg"
        if fallback.exists():
            return fallback
    return None


def write_edit_manifest(
    out_path: Path,
    entries: list[dict[str, object]],
) -> None:
    """Write the manual-editing handoff manifest.

    Each entry: chunk index, anchor ranges (source-movie absolute time),
    narration text, audio span, and the per-chunk `segment_video` /
    `segment_audio` filenames the editor opens in their NLE.
    """
    dump_json(out_path, entries)


# --- CLI ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render-video",
        description="Render the Stage 6 draft review by playing per-anchor hero clips trimmed to match audio.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Stage 3 voice manifest (anchored ranges + audio timing).")
    parser.add_argument("--voiceover", type=Path, required=True,
                        help="Stage 3 voiceover MP3.")
    parser.add_argument("--subtitle-manifest", type=Path,
                        help="Optional Stage 4 subtitle manifest with timed subtitle cues.")
    parser.add_argument("--clips-dir", type=Path, required=True,
                        help="Directory containing clip_NNN_X.mp4 files from Stage 5.")
    parser.add_argument("--keyframes-dir", type=Path, required=True,
                        help="Directory containing keyframe_NNN.jpg files (for closing chunks).")
    parser.add_argument("--clip-manifest", type=Path,
                        help="Optional override; defaults to <clips-dir>/../clip_manifest.json.")
    parser.add_argument("--visual-segments", type=Path,
                        help="Optional Stage 0 visual_segments.json — used for shot-aware smart-trim.")
    parser.add_argument("--source-video", type=Path,
                        help="Optional source movie file. When provided, the closing chunk's "
                             "visuals continue from where the last anchor's rendered video "
                             "ended in the source — instead of freezing on a still keyframe.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Draft review.mp4 path.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    args.clips_dir = args.clips_dir.expanduser().resolve()
    args.keyframes_dir = args.keyframes_dir.expanduser().resolve()
    args.manifest = args.manifest.expanduser().resolve()
    args.voiceover = args.voiceover.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.subtitle_manifest is not None:
        args.subtitle_manifest = args.subtitle_manifest.expanduser().resolve()
    if args.source_video is not None:
        args.source_video = args.source_video.expanduser().resolve()
    if args.clip_manifest is not None:
        args.clip_manifest = args.clip_manifest.expanduser().resolve()
    elif default_clip_manifest_path(args.clips_dir).exists():
        args.clip_manifest = default_clip_manifest_path(args.clips_dir)
    if args.visual_segments is not None:
        args.visual_segments = args.visual_segments.expanduser().resolve()

    if not args.manifest.exists():
        print(f"Manifest not found: {args.manifest}", file=sys.stderr)
        return 1
    if not args.voiceover.exists():
        print(f"Voiceover not found: {args.voiceover}", file=sys.stderr)
        return 1
    if args.subtitle_manifest is not None and not args.subtitle_manifest.exists():
        print(f"Subtitle manifest not found: {args.subtitle_manifest}", file=sys.stderr)
        return 1
    if args.visual_segments is not None and not args.visual_segments.exists():
        print(f"Visual segments not found: {args.visual_segments}", file=sys.stderr)
        return 1

    try:
        manifest = load_render_manifest(args.manifest)
        clip_manifest = load_clip_manifest(args.clip_manifest)
        subtitle_manifest = load_subtitle_manifest(args.subtitle_manifest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    visual_segments = load_visual_segments(args.visual_segments)
    try:
        codec = resolve_encoder()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Manifest: {len(manifest)} chunks (encoder={codec})")
    segments_dir = args.output.parent / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    # The closing chunk renders a still keyframe sized to the manifest's
    # `audio_duration`, which is computed from raw-WAV durations in
    # Stage 3. The mastered voiceover.mp3 (loudnorm + MP3 frame alignment)
    # can run slightly longer, so we probe the real audio length once and
    # use it to size the trailing still defensively.
    voiceover_total_s = probe_media_duration(args.voiceover)
    last_manifest_pos = len(manifest) - 1

    # Probe the source movie's length so we can clamp the closing tail
    # extraction at the end of the file. Optional — we just skip the
    # tail-clip path and fall back to a still if no source-video given.
    source_video_total_s: float | None = None
    if args.source_video is not None:
        try:
            source_video_total_s = get_video_duration(args.source_video)
        except RuntimeError as exc:
            print(f"  warn: could not probe --source-video ({exc}); "
                  f"closing chunk will fall back to still keyframe", file=sys.stderr)

    segment_paths: list[Path] = []
    edit_entries: list[dict[str, object]] = []
    last_anchor_index: int | None = None
    # Source-time second at which the most recent anchor's *rendered*
    # video ended. Smart-trim cuts from the tail, so this is the end of
    # the last kept range. Used to seed closing-chunk tail extraction so
    # the visual continues naturally from where the last anchor left off.
    last_anchor_kept_end_s: float | None = None
    tally: dict[str, int] = {
        "exact": 0,
        "shot-aligned-tail": 0,
        "mid-shot-tail": 0,
        "shot-aligned-spread": 0,
        "mid-shot-spread": 0,
        "extension-needed": 0,
        "freeze": 0,
        "freeze-replaced-black": 0,
        "spliced-replaced-black": 0,
        "closing-tail": 0,
    }

    total_t0 = time.time()
    for manifest_pos, entry in enumerate(manifest):
        idx = coerce_manifest_index(entry["index"], context="Manifest index")
        audio_start_s = coerce_manifest_seconds(entry["audio_start_s"], context="audio_start_s")
        audio_end_s = coerce_manifest_seconds(entry["audio_end_s"], context="audio_end_s")
        audio_duration = audio_end_s - audio_start_s
        if audio_duration <= 0:
            print(f"  skipping chunk {idx}: zero-duration narration")
            continue

        segment_path = segments_dir / f"segment_{idx:03d}.mp4"
        ranges_s = _entry_ranges_seconds(entry)
        t0 = time.time()

        if not ranges_s:
            # Closing chunk: target duration covers the manifest audio
            # plus the actual-vs-encoded MP3 drift, with a small safety
            # pad on top. -shortest mux in stage 7 trims any overshoot.
            target_duration = audio_duration
            if (
                manifest_pos == last_manifest_pos
                and voiceover_total_s is not None
            ):
                remaining_audio = max(0.0, voiceover_total_s - audio_start_s)
                target_duration = max(audio_duration, remaining_audio) + CLOSING_TAIL_PAD_S

            # Preferred: continue playing from where the last anchor's
            # rendered video ended in the source movie. Falls through to
            # the still-keyframe path if we can't (no source video, no
            # prior anchor, or the movie ran out of footage).
            rendered_from_clip = False
            if (
                args.source_video is not None
                and source_video_total_s is not None
                and last_anchor_kept_end_s is not None
            ):
                tail_start_s = last_anchor_kept_end_s
                available_s = max(0.0, source_video_total_s - tail_start_s)
                tail_duration = min(target_duration, available_s)
                if tail_duration >= MIN_CLOSING_TAIL_S:
                    print(
                        f"  chunk {idx:>3} (closing): tail-clip from "
                        f"{tail_start_s:.2f}s x {tail_duration:.2f}s",
                        end=" ",
                    )
                    render_excerpt(args.source_video, tail_start_s, tail_duration,
                                   segment_path, codec)
                    # If the source movie ran out before target_duration,
                    # top up the tail with a still over the last keyframe
                    # so audio still has video underneath it.
                    shortfall_s = target_duration - tail_duration
                    if shortfall_s > 0.05:
                        still = _choose_keyframe(args.keyframes_dir, idx, last_anchor_index)
                        if still is not None:
                            tail_part = segments_dir / f"segment_{idx:03d}_part00_tail.mp4"
                            fill_part = segments_dir / f"segment_{idx:03d}_part01_freeze.mp4"
                            segment_path.replace(tail_part)
                            render_stillframe_segment(still, shortfall_s, fill_part, codec)
                            concat_segments([tail_part, fill_part], segment_path)
                            tail_part.unlink(missing_ok=True)
                            fill_part.unlink(missing_ok=True)
                    rendered_from_clip = True
                    actual_kind = "closing-tail"
                    tally[actual_kind] = tally.get(actual_kind, 0) + 1
                    print(f"({time.time() - t0:.1f}s)")

            if not rendered_from_clip:
                # Fallback: render still over the most recent keyframe.
                still = _choose_keyframe(args.keyframes_dir, idx, last_anchor_index)
                if still is None:
                    print(f"  chunk {idx}: closing with no usable keyframe", file=sys.stderr)
                    return 1
                print(f"  chunk {idx:>3} (closing): still {still.name} x {target_duration:.2f}s", end=" ")
                render_stillframe_segment(still, target_duration, segment_path, codec)
                actual_kind = "freeze"
                tally[actual_kind] = tally.get(actual_kind, 0) + 1
                print(f"({time.time() - t0:.1f}s)")
        else:
            clip_meta = clip_manifest.get(idx) or {}
            clip_meta_ranges = list(clip_meta.get("ranges") or [])  # type: ignore[arg-type]

            # Pre-render: compute per-clip black profiles (once per unique
            # clip) and split each source range around any black gaps.
            # This is what catches chunks like 26 where a requested range
            # straddles a fade-to-black baked into the source movie.
            clip_blacks_by_path: dict[str, list[tuple[float, float]]] = {}
            for meta in clip_meta_ranges:
                clip_path_str = str(meta.get("clip_path", ""))
                if clip_path_str and clip_path_str not in clip_blacks_by_path:
                    clip_blacks_by_path[clip_path_str] = compute_clip_black_intervals(
                        args.clips_dir / clip_path_str
                    )

            split_ranges_s = ranges_s
            if any(intervals for intervals in clip_blacks_by_path.values()):
                rebuilt: list[tuple[float, float]] = []
                for rs, re_ in ranges_s:
                    meta = _find_clip_meta_for_range(clip_meta_ranges, rs, re_)
                    if meta is None:
                        rebuilt.append((rs, re_))
                        continue
                    clip_path_str = str(meta.get("clip_path", ""))
                    try:
                        extracted_start = timestamp_to_seconds(str(meta["extracted_start"]))
                    except (KeyError, ValueError):
                        rebuilt.append((rs, re_))
                        continue
                    blacks = clip_blacks_by_path.get(clip_path_str, [])
                    sub = subtract_black_from_range(rs, re_, extracted_start, blacks)
                    if not sub:
                        # All-black range; keyframe fallback handles the gap.
                        continue
                    if sub != [(rs, re_)]:
                        print(
                            f"  chunk {idx:>3}: source-black-split "
                            f"{rs:.3f}-{re_:.3f} → "
                            + " + ".join(f"{a:.3f}-{b:.3f}" for a, b in sub)
                        )
                    rebuilt.extend(sub)
                if rebuilt:
                    split_ranges_s = rebuilt

            shot_boundaries_per_range = [
                collect_shot_boundaries_for_range(rs, re_, visual_segments)
                for rs, re_ in split_ranges_s
            ]
            kept_ranges, kind = plan_smart_trim(
                split_ranges_s, shot_boundaries_per_range, audio_duration,
            )
            actual_ranges = kept_ranges
            if kind == "extension-needed":
                actual_ranges, _ = _extend_ranges_to_audio_duration(
                    kept_ranges,
                    clip_meta_ranges,
                    audio_duration,
                    clip_blacks_by_path,
                )
            part_paths = _render_kept_ranges_from_clip_manifest(
                actual_ranges, clip_meta_ranges, args.clips_dir,
                segments_dir, idx, codec,
            )
            actual_kind = kind
            if not part_paths:
                # No matching clip metadata — fall back to the keyframe.
                still = _choose_keyframe(args.keyframes_dir, idx, last_anchor_index)
                if still is None:
                    print(f"  chunk {idx}: no clips and no keyframe fallback", file=sys.stderr)
                    return 1
                render_stillframe_segment(still, audio_duration, segment_path, codec)
                actual_kind = "freeze"
            elif len(part_paths) == 1:
                remaining_fill = max(0.0, audio_duration - _ranges_total_duration(actual_ranges))
                if remaining_fill > 0.01:
                    still = _choose_keyframe(args.keyframes_dir, idx, last_anchor_index)
                    if still is None:
                        print(f"  chunk {idx}: extension shortfall with no keyframe fallback", file=sys.stderr)
                        return 1
                    fill_path = segments_dir / f"segment_{idx:03d}_part01_freeze.mp4"
                    render_stillframe_segment(still, remaining_fill, fill_path, codec)
                    part_paths.append(fill_path)
                    concat_segments(part_paths, segment_path)
                    for p in part_paths:
                        p.unlink(missing_ok=True)
                else:
                    part_paths[0].replace(segment_path)
            else:
                remaining_fill = max(0.0, audio_duration - _ranges_total_duration(actual_ranges))
                if remaining_fill > 0.01:
                    still = _choose_keyframe(args.keyframes_dir, idx, last_anchor_index)
                    if still is None:
                        print(f"  chunk {idx}: extension shortfall with no keyframe fallback", file=sys.stderr)
                        return 1
                    fill_path = segments_dir / f"segment_{idx:03d}_part{len(part_paths):02d}_freeze.mp4"
                    render_stillframe_segment(still, remaining_fill, fill_path, codec)
                    part_paths.append(fill_path)
                concat_segments(part_paths, segment_path)
                # Note: parts are intentionally KEPT alongside segment_NNN.mp4.
                # For a clean handoff we leave only the merged segment file.
                for p in part_paths:
                    p.unlink(missing_ok=True)
            last_anchor_index = idx
            if actual_ranges:
                # Where in source-time the last kept range ends — the
                # natural "resume here" point for the closing tail clip.
                last_anchor_kept_end_s = actual_ranges[-1][1]
            tally[actual_kind] = tally.get(actual_kind, 0) + 1
            print(
                f"  chunk {idx:>3}: {actual_kind:<18} ranges={len(actual_ranges)} "
                f"audio={audio_duration:.2f}s ({time.time() - t0:.1f}s)"
            )

        # Post-render safety net: pre-render passes (source-level split +
        # extension clamp) cover most fades, but a chunk can still end up
        # with residual black at part boundaries. We surgically splice
        # those out — only the black sub-windows are replaced with a
        # still, so good footage in the rest of the chunk is preserved.
        # Closing chunks rendered from a real source-movie tail also need
        # this check (movie-end fades / credits roll), but a still-only
        # closing chunk does not.
        rendered_from_clip = bool(ranges_s) or actual_kind == "closing-tail"
        if segment_path.exists() and rendered_from_clip:
            black_intervals = detect_black_intervals(segment_path)
            black_total = sum(end - start for start, end in black_intervals)
            if black_total > BLACK_FRAME_THRESHOLD_S:
                still = _choose_keyframe(args.keyframes_dir, idx, last_anchor_index)
                if still is not None:
                    print(
                        f"  chunk {idx:>3}: blackdetect found {black_total:.2f}s "
                        f"of black ({len(black_intervals)} interval(s)) — splicing "
                        f"with keyframe {still.name}"
                    )
                    splice_black_with_stills(
                        segment_path, black_intervals, audio_duration,
                        still, segments_dir, idx, codec,
                    )
                    tally[actual_kind] = max(0, tally.get(actual_kind, 0) - 1)
                    actual_kind = "spliced-replaced-black"
                    tally[actual_kind] = tally.get(actual_kind, 0) + 1
                else:
                    print(
                        f"  chunk {idx:>3}: blackdetect found {black_total:.2f}s "
                        f"of black but no keyframe fallback available",
                        file=sys.stderr,
                    )

        # Per-chunk MP3 split for the manual-editing handoff.
        segment_audio = segments_dir / f"segment_{idx:03d}.mp3"
        split_voiceover_to_segment(args.voiceover, audio_start_s, audio_end_s, segment_audio)

        edit_entries.append({
            "index": idx,
            "ranges": entry.get("ranges") or [],
            "characters": entry.get("characters") or [],
            "narration": entry.get("text", ""),
            "audio_start_s": audio_start_s,
            "audio_end_s": audio_end_s,
            "segment_video": segment_path.name,
            "segment_audio": segment_audio.name,
        })
        segment_paths.append(segment_path)

    if not segment_paths:
        print("No segments rendered", file=sys.stderr)
        return 1

    # Concatenate per-chunk segments → silent draft, burn subtitles, then mux narration audio.
    silent_draft = args.output.with_suffix(".silent.mp4")
    subtitled_draft = args.output.with_suffix(".subtitled.mp4")
    subtitle_script = args.output.parent / "review_subtitles.ass"
    concat_segments(segment_paths, silent_draft)
    video_for_mux = silent_draft
    subtitle_entries = subtitle_manifest or manifest
    if write_subtitle_script(subtitle_entries, subtitle_script):
        burn_subtitles(silent_draft, subtitle_script, subtitled_draft, codec)
        video_for_mux = subtitled_draft
    mux_audio(video_for_mux, args.voiceover, args.output)
    silent_draft.unlink(missing_ok=True)
    subtitled_draft.unlink(missing_ok=True)

    edit_manifest_path = args.output.parent / "edit_manifest.json"
    write_edit_manifest(edit_manifest_path, edit_entries)

    elapsed = time.time() - total_t0
    print(f"\n[done] {args.output} ({elapsed:.1f}s = {elapsed / 60:.2f} min)")
    print(
        "[tally] "
        + " ".join(f"{kind}={count}" for kind, count in tally.items() if count)
    )
    print(f"[edit handoff] {edit_manifest_path} ({len(edit_entries)} segments in {segments_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
