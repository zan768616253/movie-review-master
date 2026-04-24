"""Render the final video with hero-clip priority and timing-aware fallbacks.

Priority when narration outlasts the requested hero scene:
1. Use the exact hero window.
2. Expand into extracted handles and any safe-boundary extension.
3. Append explicit or semantic B-roll.
4. Freeze only as the last fallback.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

from app.pipeline.common.json_io import load_json
from app.pipeline.common.script_contract import get_video_duration, load_visual_segments, timestamp_to_seconds
from app.pipeline.common.video_encoder import (
    DEFAULT_ENCODER,
    ENCODER_CHOICES,
    encoder_ffmpeg_args,
    resolve_encoder,
)


TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 30
DEFAULT_CLIP_MANIFEST = "clip_manifest.json"
TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)
ACTION_HINTS = (
    "fight",
    "attack",
    "run",
    "chase",
    "kill",
    "explosion",
    "shoot",
    "punch",
    "slash",
    "battle",
    "打",
    "杀",
    "跑",
    "追",
    "战",
    "爆",
    "砍",
    "冲",
)


def probe_duration(path: Path) -> float:
    return get_video_duration(path)


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

    ``start_s`` is passed straight to ffmpeg's ``-ss`` — the caller decides whether
    that's an offset into an already-extracted clip or an absolute time in the
    source movie. ffmpeg treats both the same.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
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
    vf = normalize_scale_filter()
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-framerate",
        str(TARGET_FPS),
        "-i",
        str(image_path),
        "-t",
        f"{target_duration:.3f}",
        "-vf",
        vf,
        *encoder_ffmpeg_args(codec),
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def default_clip_manifest_path(clips_dir: Path) -> Path:
    return clips_dir.parent / DEFAULT_CLIP_MANIFEST


def load_clip_manifest(path: Path | None) -> dict[int, dict[str, object]]:
    if path is None or not path.exists():
        return {}
    payload = load_json(path)
    return {int(entry["index"]): entry for entry in payload}


def tokenize_text(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text.lower())}


def text_similarity(left: str, right: str) -> float:
    left_tokens = tokenize_text(left)
    right_tokens = tokenize_text(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def looks_action_like(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in ACTION_HINTS)


def plan_primary_window(clip_metadata: dict[str, object], target_duration: float) -> tuple[float, float, float]:
    """Return (start_offset, clip_duration, leftover) for the hero clip.

    Splits any extra time needed between the pre- and post-roll handles, then
    spills over into whichever side still has room if the other is saturated.
    """
    requested = float(clip_metadata.get("requested_duration_s") or 0.0)
    pre_handle = float(clip_metadata.get("pre_handle_s") or 0.0)
    extracted = float(clip_metadata.get("extracted_duration_s") or 0.0)
    post_handle = max(0.0, extracted - pre_handle - requested)

    if target_duration <= requested:
        return pre_handle, target_duration, 0.0

    extra_needed = min(target_duration - requested, pre_handle + post_handle)
    pre_use = min(pre_handle, extra_needed / 2)
    post_use = min(post_handle, extra_needed - pre_use)
    pre_use = min(pre_handle, extra_needed - post_use)  # absorb whatever post could not take

    clip_duration = requested + pre_use + post_use
    leftover = max(0.0, target_duration - clip_duration)
    return pre_handle - pre_use, clip_duration, leftover


def score_visual_segment(
    segment: dict[str, object],
    narration_text: str,
    required_characters: set[str],
) -> float | None:
    segment_characters = {str(character) for character in segment.get("characters") or []}
    if required_characters and not required_characters.issubset(segment_characters):
        return None

    summary = str(segment.get("summary") or "")
    ocr_text = str(segment.get("ocr_text") or "")
    similarity = text_similarity(narration_text, f"{summary} {ocr_text}")
    character_score = 1.0 if required_characters else 0.0
    action_score = 1.0 if segment.get("is_action") and looks_action_like(narration_text) else 0.0
    confidence = float(segment.get("confidence") or 0.0)
    return (0.35 * similarity) + (0.30 * character_score) + (0.15 * action_score) + (0.20 * confidence)


def select_semantic_broll_segments(
    entry: dict[str, object],
    visual_segments: list[dict[str, object]],
    used_segment_ids: set[str],
) -> list[dict[str, object]]:
    required_characters = {str(character) for character in entry.get("scene_characters") or []}
    narration_text = str(entry.get("text") or "")
    exclude_evidence = str(entry.get("scene_evidence") or "")
    exclude_start = entry.get("scene_start")
    exclude_end = entry.get("scene_end")
    exclude_range = None
    if exclude_start and exclude_end:
        exclude_range = (timestamp_to_seconds(str(exclude_start)), timestamp_to_seconds(str(exclude_end)))

    ranked: list[tuple[float, dict[str, object]]] = []
    for index, segment in enumerate(visual_segments, 1):
        segment_id = str(segment.get("id") or f"visual:{index:03d}")
        if segment_id == exclude_evidence or segment_id in used_segment_ids:
            continue

        segment_start = timestamp_to_seconds(str(segment["start"]))
        segment_end = timestamp_to_seconds(str(segment["end"]))
        if exclude_range is not None and segment_start < exclude_range[1] and segment_end > exclude_range[0]:
            continue

        score = score_visual_segment(segment, narration_text, required_characters)
        if score is None:
            continue
        ranked.append((score, segment))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [segment for score, segment in ranked if score > 0.05]


def collect_manual_broll_paths(entry: dict[str, object], clips_dir: Path) -> list[Path]:
    broll_paths: list[Path] = []
    for i, _ in enumerate(entry.get("broll") or []):
        suffix = chr(ord("a") + i)
        broll_path = clips_dir / f"broll_{int(entry['index']):03d}_{suffix}.mp4"
        if broll_path.exists():
            broll_paths.append(broll_path)
    return broll_paths


def choose_keyframe_path(keyframes_dir: Path, index: int, last_clip_number: int | None) -> Path | None:
    direct = keyframes_dir / f"keyframe_{index:03d}.jpg"
    if direct.exists():
        return direct
    if last_clip_number is not None:
        fallback = keyframes_dir / f"keyframe_{last_clip_number:03d}.jpg"
        if fallback.exists():
            return fallback
    return None


def concat_segments(segment_paths: list[Path], out_path: Path) -> None:
    list_file = out_path.parent / f"{out_path.stem}.concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in segment_paths),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c:v",
        "copy",
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    list_file.unlink(missing_ok=True)


def mux_audio(video_path: Path, audio_path: Path, out_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render-video",
        description="Render the final video using hero clips first, then B-roll fallbacks.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--voiceover", type=Path, required=True)
    parser.add_argument(
        "--clips-dir",
        type=Path,
        required=True,
        help="Directory containing clip_NNN.mp4 files",
    )
    parser.add_argument(
        "--keyframes-dir",
        type=Path,
        required=True,
        help="Directory containing keyframe_NNN.jpg files (used for closing + short-clip fallback)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Final rendered MP4 output path",
    )
    parser.add_argument(
        "--clip-manifest",
        type=Path,
        help="Optional clip manifest from Stage 4; defaults to <clips-dir>/../clip_manifest.json when present",
    )
    parser.add_argument(
        "--video",
        type=Path,
        help="Source movie file, required for semantic B-roll fallback",
    )
    parser.add_argument(
        "--visual-segments",
        type=Path,
        help="visual_segments.json, used for semantic B-roll fallback",
    )
    parser.add_argument(
        "--freeze-threshold",
        type=float,
        default=0.5,
        help="Warn when freeze fallback exceeds this duration in seconds",
    )
    parser.add_argument(
        "--encoder",
        choices=ENCODER_CHOICES,
        default=DEFAULT_ENCODER,
        help="Video encoder. 'auto' picks h264_nvenc when available, otherwise libx264.",
    )
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
    if args.video is not None:
        args.video = args.video.expanduser().resolve()
    if args.visual_segments is not None:
        args.visual_segments = args.visual_segments.expanduser().resolve()

    if not args.manifest.exists():
        print(f"Manifest not found: {args.manifest}", file=sys.stderr)
        return 1
    if not args.voiceover.exists():
        print(f"Voiceover not found: {args.voiceover}", file=sys.stderr)
        return 1
    if args.video is not None and not args.video.exists():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1
    if args.visual_segments is not None and not args.visual_segments.exists():
        print(f"Visual segments not found: {args.visual_segments}", file=sys.stderr)
        return 1

    manifest = load_json(args.manifest)
    clip_manifest = load_clip_manifest(args.clip_manifest)
    visual_segments = load_visual_segments(args.visual_segments)
    codec = resolve_encoder(args.encoder)
    used_segment_ids: set[str] = set()
    print(f"Manifest: {len(manifest)} chunks (encoder={codec})")

    segments_dir = args.output.parent / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    segment_paths: list[Path] = []
    total_t0 = time.time()
    last_clip_number: int | None = None

    for entry in manifest:
        idx = entry["index"]
        target_dur = entry["audio_end_s"] - entry["audio_start_s"]
        if target_dur <= 0:
            print(f"  skipping chunk {idx}: zero-duration narration")
            continue

        segment_path = segments_dir / f"segment_{idx:03d}.mp4"
        t0 = time.time()

        if entry.get("scene_start") is None and entry.get("scene_source") is None:
            still = choose_keyframe_path(args.keyframes_dir, idx, last_clip_number)
            if still is None:
                print(f"  chunk {idx}: closing chunk with no usable keyframe", file=sys.stderr)
                return 1
            print(f"  chunk {idx:>3} (closing): still {still.name} x {target_dur:.2f}s", end=" ")
            render_stillframe_segment(still, target_dur, segment_path, codec)
            print(f"({time.time() - t0:.1f}s)")
            segment_paths.append(segment_path)
            continue

        part_paths: list[Path] = []
        remaining = target_dur
        part_index = 0
        clip_path = args.clips_dir / f"clip_{idx:03d}.mp4"
        clip_metadata = clip_manifest.get(idx)

        if clip_path.exists():
            if clip_metadata is not None:
                start_offset, primary_duration, remaining = plan_primary_window(clip_metadata, target_dur)
            else:
                available_duration = probe_duration(clip_path)
                primary_duration = min(target_dur, available_duration)
                start_offset = 0.0
                remaining = max(0.0, target_dur - primary_duration)
            if primary_duration > 0.01:
                part_path = segments_dir / f"segment_{idx:03d}_part{part_index:02d}_hero.mp4"
                render_excerpt(clip_path, start_offset, primary_duration, part_path, codec)
                part_paths.append(part_path)
                part_index += 1
                last_clip_number = idx

        manual_broll_paths = collect_manual_broll_paths(entry, args.clips_dir)
        for broll_path in manual_broll_paths:
            if remaining <= 0.01:
                break
            available_duration = probe_duration(broll_path)
            if available_duration <= 0.01:
                continue
            duration = min(remaining, available_duration)
            part_path = segments_dir / f"segment_{idx:03d}_part{part_index:02d}_broll.mp4"
            render_excerpt(broll_path, 0.0, duration, part_path, codec)
            part_paths.append(part_path)
            part_index += 1
            remaining -= duration

        if remaining > 0.01 and args.video is not None and visual_segments:
            for segment in select_semantic_broll_segments(entry, visual_segments, used_segment_ids):
                if remaining <= 0.01:
                    break
                segment_id = str(segment.get("id"))
                segment_start = timestamp_to_seconds(str(segment["start"]))
                segment_end = timestamp_to_seconds(str(segment["end"]))
                segment_duration = max(0.0, segment_end - segment_start)
                if segment_duration <= 0.01:
                    continue
                duration = min(remaining, segment_duration)
                part_path = segments_dir / f"segment_{idx:03d}_part{part_index:02d}_semantic.mp4"
                render_excerpt(args.video, segment_start, duration, part_path, codec)
                part_paths.append(part_path)
                part_index += 1
                remaining -= duration
                used_segment_ids.add(segment_id)

        if remaining > 0.01:
            still = choose_keyframe_path(args.keyframes_dir, idx, last_clip_number)
            if still is None:
                print(f"  chunk {idx}: no clip, semantic B-roll, or keyframe fallback available", file=sys.stderr)
                return 1
            if remaining > args.freeze_threshold:
                print(
                    f"  chunk {idx}: warning - freeze fallback {remaining:.2f}s exceeds threshold {args.freeze_threshold:.2f}s",
                    file=sys.stderr,
                )
            part_path = segments_dir / f"segment_{idx:03d}_part{part_index:02d}_freeze.mp4"
            render_stillframe_segment(still, remaining, part_path, codec)
            part_paths.append(part_path)

        if not part_paths:
            print(f"  chunk {idx}: unable to render any visual segment", file=sys.stderr)
            return 1

        if len(part_paths) == 1:
            part_paths[0].replace(segment_path)
        else:
            concat_segments(part_paths, segment_path)
            for part_path in part_paths:
                part_path.unlink(missing_ok=True)

        descriptor = []
        if clip_path.exists():
            descriptor.append(clip_path.name)
        if manual_broll_paths:
            descriptor.append(f"{len(manual_broll_paths)} manual B-roll")
        if any("semantic" in path.name for path in part_paths):
            descriptor.append("semantic B-roll")
        if any("freeze" in path.name for path in part_paths):
            descriptor.append("freeze")
        desc_text = " + ".join(descriptor) if descriptor else "fallback-only"
        print(f"  chunk {idx:>3}: {desc_text} over {target_dur:.2f}s", end=" ")

        print(f"({time.time() - t0:.1f}s)")
        segment_paths.append(segment_path)

    print(f"\nConcatenating {len(segment_paths)} segments")
    video_track = args.output.parent / "video_track.mp4"
    concat_segments(segment_paths, video_track)

    print(f"Muxing voiceover {args.voiceover.name}")
    mux_audio(video_track, args.voiceover, args.output)
    video_track.unlink(missing_ok=True)

    final_dur = probe_duration(args.output)
    print(
        f"\n[done] {args.output} ({final_dur:.1f}s = {final_dur / 60:.2f} min) "
        f"in {(time.time() - total_t0) / 60:.1f} min"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
