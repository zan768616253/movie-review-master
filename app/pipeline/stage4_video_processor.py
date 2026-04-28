"""Extract per-anchor hero clips and keyframes from an anchored script.

Each `[ANCHOR]` may carry one or more chronological source-movie ranges
(multi-range anchors). Stage 4 cuts one clip file per range:

    chunk index 7, single-range anchor   →  clip_007_a.mp4
    chunk index 7, three-range anchor    →  clip_007_a.mp4, clip_007_b.mp4, clip_007_c.mp4

Asymmetric pre/post handles give Stage 5 runway to absorb TTS-pacing
variance without falling to a freeze:

    pre_handle  = 2.0s   — small lead-in before the requested start
    post_handle = 4.0s   — generous tail so a slow TTS chunk can extend

Closing chunks (no anchor) are skipped entirely; Stage 5 falls back to
the most recent keyframe for them.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from app.pipeline.common.json_io import dump_json
from app.pipeline.common.script_contract import (
    AnchorMarker,
    get_video_duration,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.common.video_encoder import (
    encoder_ffmpeg_args,
    hwaccel_decode_args,
    resolve_encoder,
)
from app.pipeline.stage3_generate_audio import parse_script_chunks


PRE_HANDLE_SECONDS = 2.0
POST_HANDLE_SECONDS = 4.0


@dataclass
class RangeClipPlan:
    """One range within an anchor → one extracted clip on disk."""

    suffix: str  # 'a', 'b', 'c', ...
    range_start: str
    range_end: str
    extracted_start: str
    extracted_end: str
    requested_duration_s: float
    extracted_duration_s: float
    pre_handle_s: float
    post_handle_s: float
    clip_path: str  # filename only, e.g. "clip_007_a.mp4"


@dataclass
class AnchorClipPlan:
    """All clips and the keyframe associated with one anchored chunk."""

    index: int
    characters: list[str]
    range_plans: list[RangeClipPlan] = field(default_factory=list)
    keyframe_time: str = ""
    keyframe_path: str = ""


def _suffix_for(i: int) -> str:
    """Convert a 0-based range index into 'a', 'b', ..., 'z', 'aa', ..."""
    if i < 26:
        return chr(ord("a") + i)
    # 26+ ranges in one anchor would be absurd, but handle it cleanly anyway.
    return _suffix_for(i // 26 - 1) + chr(ord("a") + i % 26)


def plan_anchor_clips(
    index: int,
    anchor: AnchorMarker,
    video_duration_s: float,
) -> AnchorClipPlan:
    """Build a clip plan for every range in one anchor.

    Each range gets its own RangeClipPlan with absolute extraction
    timestamps clamped to [0, video_duration_s]. The keyframe is taken
    from the first range's start (≈1s in for stable framing).

    Example: an anchor with two ranges → two RangeClipPlans named
    `clip_007_a.mp4` and `clip_007_b.mp4`.
    """
    range_plans: list[RangeClipPlan] = []

    for i, (start_ts, end_ts) in enumerate(anchor.ranges):
        start_s = timestamp_to_seconds(start_ts)
        end_s = timestamp_to_seconds(end_ts)
        requested_duration_s = max(0.0, end_s - start_s)

        extracted_start_s = max(0.0, start_s - PRE_HANDLE_SECONDS)
        extracted_end_s = min(video_duration_s, end_s + POST_HANDLE_SECONDS)
        # Recompute handles after EOF clamp so the manifest reflects what
        # actually exists on disk.
        pre_handle_s = start_s - extracted_start_s
        post_handle_s = max(0.0, extracted_end_s - end_s)

        suffix = _suffix_for(i)
        range_plans.append(RangeClipPlan(
            suffix=suffix,
            range_start=start_ts,
            range_end=end_ts,
            extracted_start=seconds_to_timestamp(extracted_start_s),
            extracted_end=seconds_to_timestamp(extracted_end_s),
            requested_duration_s=requested_duration_s,
            extracted_duration_s=max(0.0, extracted_end_s - extracted_start_s),
            pre_handle_s=pre_handle_s,
            post_handle_s=post_handle_s,
            clip_path=f"clip_{index:03d}_{suffix}.mp4",
        ))

    # Keyframe: ~1s into the first range gives a stable, mid-shot frame.
    if range_plans:
        first = range_plans[0]
        first_dur = first.requested_duration_s
        first_start_s = timestamp_to_seconds(first.range_start)
        keyframe_time_s = first_start_s + min(1.0, first_dur / 2)
        keyframe_path = f"keyframe_{index:03d}.jpg"
    else:
        keyframe_time_s = 0.0
        keyframe_path = ""

    return AnchorClipPlan(
        index=index,
        characters=list(anchor.characters),
        range_plans=range_plans,
        keyframe_time=seconds_to_timestamp(keyframe_time_s),
        keyframe_path=keyframe_path,
    )


def extract_clip(video_path: Path, start_s: float, end_s: float, out_path: Path, codec: str) -> None:
    duration_s = max(0.0, end_s - start_s)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *hwaccel_decode_args(codec),
        "-ss", seconds_to_timestamp(start_s),
        "-i", str(video_path),
        "-t", f"{duration_s:.3f}",
        "-an",
        *encoder_ffmpeg_args(codec),
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def extract_keyframe(video_path: Path, at_s: float, out_path: Path, codec: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        *hwaccel_decode_args(codec),
        "-ss", seconds_to_timestamp(at_s),
        "-i", str(video_path),
        "-vframes", "1",
        "-q:v", "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def write_clip_manifest(output_dir: Path, plans: list[AnchorClipPlan]) -> Path:
    """Write `clip_manifest.json` consumed by Stage 5.

    Schema per anchor:
        {
            "index": 7,
            "characters": ["Yuta", "Rika"],
            "keyframe_path": "keyframe_007.jpg",
            "ranges": [
                {"clip_path": "clip_007_a.mp4",
                 "range_start": "...", "range_end": "...",
                 "extracted_start": "...", "extracted_end": "...",
                 "requested_duration_s": ..., "extracted_duration_s": ...,
                 "pre_handle_s": ..., "post_handle_s": ...},
                ...
            ]
        }
    """
    manifest_path = output_dir / "clip_manifest.json"
    payload = []
    for plan in plans:
        payload.append({
            "index": plan.index,
            "characters": plan.characters,
            "keyframe_path": plan.keyframe_path,
            "ranges": [
                {
                    "clip_path": rp.clip_path,
                    "range_start": rp.range_start,
                    "range_end": rp.range_end,
                    "extracted_start": rp.extracted_start,
                    "extracted_end": rp.extracted_end,
                    "requested_duration_s": rp.requested_duration_s,
                    "extracted_duration_s": rp.extracted_duration_s,
                    "pre_handle_s": rp.pre_handle_s,
                    "post_handle_s": rp.post_handle_s,
                }
                for rp in plan.range_plans
            ],
        })
    dump_json(manifest_path, payload)
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-processor",
        description="Extract per-anchor hero clips and keyframes from an anchored script.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--script",
        type=Path,
        required=True,
        help="Anchored script (Stage 2 output) containing [ANCHOR] markers.",
    )
    parser.add_argument(
        "--video",
        type=Path,
        required=True,
        help="Source movie file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where clips/, keyframes/, and clip_manifest.json land.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script_path = args.script.expanduser().resolve()
    video_path = args.video.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    for path in (script_path, video_path):
        if not path.exists():
            print(f"Input not found: {path}", file=sys.stderr)
            return 1

    chunks = parse_script_chunks(script_path.read_text(encoding="utf-8"))
    anchored_chunks = [c for c in chunks if c.anchor is not None]
    if not anchored_chunks:
        print(f"No [ANCHOR] markers found in {script_path}", file=sys.stderr)
        return 1

    video_duration_s = get_video_duration(video_path)
    try:
        codec = resolve_encoder()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    clips_dir = output_dir / "clips"
    keyframes_dir = output_dir / "keyframes"
    clips_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir.mkdir(parents=True, exist_ok=True)

    plans = [
        plan_anchor_clips(c.index, c.anchor, video_duration_s)  # type: ignore[arg-type]
        for c in anchored_chunks
    ]
    total_ranges = sum(len(p.range_plans) for p in plans)
    print(
        f"Found {len(plans)} anchored chunks ({total_ranges} ranges total) in {script_path.name} "
        f"(encoder={codec}, pre={PRE_HANDLE_SECONDS}s post={POST_HANDLE_SECONDS}s, movie={video_duration_s:.1f}s)"
    )

    failures = 0
    for plan in plans:
        for rp in plan.range_plans:
            clip_out = clips_dir / rp.clip_path
            print(
                f"[clip {plan.index:>3}{rp.suffix}] {rp.range_start}->{rp.range_end} "
                f"with handles {rp.extracted_start}->{rp.extracted_end}  {clip_out.name}"
            )
            try:
                extract_clip(
                    video_path,
                    timestamp_to_seconds(rp.extracted_start),
                    timestamp_to_seconds(rp.extracted_end),
                    clip_out,
                    codec,
                )
            except subprocess.CalledProcessError as exc:
                print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                failures += 1

        if plan.keyframe_path:
            keyframe_out = keyframes_dir / plan.keyframe_path
            try:
                extract_keyframe(
                    video_path,
                    timestamp_to_seconds(plan.keyframe_time),
                    keyframe_out,
                    codec,
                )
            except subprocess.CalledProcessError as exc:
                print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                failures += 1

    manifest_path = write_clip_manifest(output_dir, plans)
    print(f"Clip manifest -> {manifest_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
