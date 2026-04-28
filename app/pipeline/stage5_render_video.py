"""Render the final review video from anchored manifests.

Reads the Stage 3 voice manifest (`ranges` per chunk + audio timing) and
the Stage 4 clip manifest (one or more pre-extracted clips per chunk),
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

    <output_dir>/review.mp4               final video
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
    load_visual_segments,
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
# Smart-trim accepts a shot-aligned cut whose video duration is within this
# fraction of audio_duration. Larger grace = more clean cuts, more residual
# overrun absorbed by post-handle extension or still fallback; smaller = more
# mid-shot cuts.
SMART_TRIM_GRACE_PCT = 0.05


# --- ffmpeg helpers -------------------------------------------------------


def normalize_scale_filter() -> str:
    return (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
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
    """Load Stage 4's clip manifest (per-anchor list of range clips)."""
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


def plan_smart_trim(
    ranges_s: list[tuple[float, float]],
    shot_boundaries_per_range: list[list[float]],
    audio_duration_s: float,
    grace_pct: float = SMART_TRIM_GRACE_PCT,
) -> tuple[list[tuple[float, float]], str]:
    """Decide how to trim multi-range hero video to match audio duration.

    Returns ``(kept_ranges, trim_kind)`` where ``trim_kind`` is one of:
      - ``"exact"``           — total ≈ audio_duration (within grace).
      - ``"shot-aligned-tail"`` — last range trimmed at a shot boundary.
      - ``"mid-shot-tail"``   — last range trimmed mid-shot to exact target.
            - ``"extension-needed"`` — total < audio; caller should extend from
                Stage 4 post-handles and freeze only if that still is not enough.

    Strategy: trim from the tail of the last range. When shot boundaries
    are available inside that range, snap to the latest one within
    ``grace`` of the target end. Shot boundaries land on clean cut points,
    so this preserves narrative flow without slicing mid-action.

    Ranges are absolute source-movie seconds (start_s, end_s).

    Example::

        ranges_s = [(10.0, 14.0), (20.0, 30.0)]   # total 14s
        shots    = [[], [22.0, 25.0, 28.0]]
        audio    = 11s
        excess   = 3s → trim last range from end → new_end = 27 → snap to 28? No,
                   28 is past new_end. Snap to 25? 14-(30-25)=9s video, 2s under,
                   within 5% grace of 11s → "shot-aligned-tail", new last = (20,25).
    """
    if not ranges_s:
        return [], "exact"

    total = sum(end - start for start, end in ranges_s)
    grace = grace_pct * audio_duration_s

    if total + grace < audio_duration_s:
        return ranges_s, "extension-needed"
    if total <= audio_duration_s + grace:
        return ranges_s, "exact"

    # total > audio + grace: trim from the tail of the last range.
    excess = total - audio_duration_s
    last_idx = len(ranges_s) - 1
    last_start, last_end = ranges_s[last_idx]
    last_dur = last_end - last_start

    # If excess >= last range duration, drop the whole last range and
    # recurse on the shorter list. This usually means the planner picked
    # one too many ranges; downstream still gets earlier ranges intact.
    if excess >= last_dur - grace:
        if len(ranges_s) == 1:
            # Only one range and audio is effectively near-zero. Keep a
            # tiny tail slice; the caller will still freeze-fill any
            # remaining shortfall to preserve sync.
            return [(last_start, last_start + max(0.0, last_dur - excess))], "mid-shot-tail"
        return plan_smart_trim(
            ranges_s[:-1],
            shot_boundaries_per_range[:-1],
            audio_duration_s,
            grace_pct,
        )

    # Trim within the last range. new_end gives an exact target match.
    new_end = last_end - excess
    candidates = shot_boundaries_per_range[last_idx] if last_idx < len(shot_boundaries_per_range) else []
    in_window = [b for b in candidates if last_start < b <= new_end + grace]
    if in_window:
        # Pick the latest candidate — preserves the most of the original
        # shot, which usually contains the payoff frame.
        snapped = max(in_window)
        new_ranges = list(ranges_s)
        new_ranges[last_idx] = (last_start, snapped)
        return new_ranges, "shot-aligned-tail"

    new_ranges = list(ranges_s)
    new_ranges[last_idx] = (last_start, new_end)
    return new_ranges, "mid-shot-tail"


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
) -> tuple[list[tuple[float, float]], float]:
    """Extend the last kept range into its extracted post-handle when audio overruns.

    Returns ``(extended_ranges, remaining_shortfall_s)``. Any remaining
    shortfall must be filled with a still segment so the rendered chunk
    duration still matches narration exactly.
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
        description="Render the final review by playing per-anchor hero clips trimmed to match audio.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Stage 3 voice manifest (anchored ranges + audio timing).")
    parser.add_argument("--voiceover", type=Path, required=True,
                        help="Stage 3 voiceover MP3.")
    parser.add_argument("--clips-dir", type=Path, required=True,
                        help="Directory containing clip_NNN_X.mp4 files from Stage 4.")
    parser.add_argument("--keyframes-dir", type=Path, required=True,
                        help="Directory containing keyframe_NNN.jpg files (for closing chunks).")
    parser.add_argument("--clip-manifest", type=Path,
                        help="Optional override; defaults to <clips-dir>/../clip_manifest.json.")
    parser.add_argument("--visual-segments", type=Path,
                        help="Optional Stage 0 visual_segments.json — used for shot-aware smart-trim.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Final review.mp4 path.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    args.clips_dir = args.clips_dir.expanduser().resolve()
    args.keyframes_dir = args.keyframes_dir.expanduser().resolve()
    args.manifest = args.manifest.expanduser().resolve()
    args.voiceover = args.voiceover.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
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
    if args.visual_segments is not None and not args.visual_segments.exists():
        print(f"Visual segments not found: {args.visual_segments}", file=sys.stderr)
        return 1

    try:
        manifest = load_render_manifest(args.manifest)
        clip_manifest = load_clip_manifest(args.clip_manifest)
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

    segment_paths: list[Path] = []
    edit_entries: list[dict[str, object]] = []
    last_anchor_index: int | None = None
    tally = {"exact": 0, "shot-aligned-tail": 0, "mid-shot-tail": 0,
             "extension-needed": 0, "freeze": 0}

    total_t0 = time.time()
    for entry in manifest:
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
            # Closing chunk: render still over the most recent keyframe.
            still = _choose_keyframe(args.keyframes_dir, idx, last_anchor_index)
            if still is None:
                print(f"  chunk {idx}: closing with no usable keyframe", file=sys.stderr)
                return 1
            print(f"  chunk {idx:>3} (closing): still {still.name} x {audio_duration:.2f}s", end=" ")
            render_stillframe_segment(still, audio_duration, segment_path, codec)
            tally["freeze"] += 1
            print(f"({time.time() - t0:.1f}s)")
        else:
            shot_boundaries_per_range = [
                collect_shot_boundaries_for_range(rs, re_, visual_segments)
                for rs, re_ in ranges_s
            ]
            kept_ranges, kind = plan_smart_trim(
                ranges_s, shot_boundaries_per_range, audio_duration,
            )
            clip_meta = clip_manifest.get(idx) or {}
            clip_meta_ranges = list(clip_meta.get("ranges") or [])  # type: ignore[arg-type]
            actual_ranges = kept_ranges
            if kind == "extension-needed":
                actual_ranges, _ = _extend_ranges_to_audio_duration(
                    kept_ranges,
                    clip_meta_ranges,
                    audio_duration,
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
            tally[actual_kind] = tally.get(actual_kind, 0) + 1
            print(
                f"  chunk {idx:>3}: {actual_kind:<18} ranges={len(actual_ranges)} "
                f"audio={audio_duration:.2f}s ({time.time() - t0:.1f}s)"
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

    # Concatenate per-chunk segments → silent draft, then mux narration audio.
    silent_draft = args.output.with_suffix(".silent.mp4")
    concat_segments(segment_paths, silent_draft)
    mux_audio(silent_draft, args.voiceover, args.output)
    silent_draft.unlink(missing_ok=True)

    edit_manifest_path = args.output.parent / "edit_manifest.json"
    write_edit_manifest(edit_manifest_path, edit_entries)

    elapsed = time.time() - total_t0
    print(f"\n[done] {args.output} ({elapsed:.1f}s = {elapsed / 60:.2f} min)")
    print(
        f"[tally] exact={tally['exact']} shot-aligned-tail={tally['shot-aligned-tail']} "
        f"mid-shot-tail={tally['mid-shot-tail']} extension-needed={tally['extension-needed']} "
        f"freeze={tally['freeze']}"
    )
    print(f"[edit handoff] {edit_manifest_path} ({len(edit_entries)} segments in {segments_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
