"""Extract high-precision hero clips, B-roll clips, and keyframes from a grounded script.

Primary clips are re-encoded instead of stream-copied so timestamp alignment is stable.
Each hero clip is extracted with configurable pre/post handles and, when a visual index is
available, extended to the nearest safe visual boundary.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence

from app.pipeline.common.script_contract import (
    BROLL_LINE_RE,
    get_video_duration,
    load_visual_segments,
    overlapping_visual_segments,
    parse_broll_ranges,
    parse_scene_marker,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.common.video_encoder import (
    DEFAULT_ENCODER,
    ENCODER_CHOICES,
    encoder_ffmpeg_args,
    resolve_encoder,
)


DEFAULT_HANDLE_SECONDS = 1.5
DEFAULT_MAX_EXTENSION_SECONDS = 30.0
DEFAULT_CLIP_MANIFEST = "clip_manifest.json"


@dataclass
class Scene:
    index: int
    marker_start: str | None
    marker_end: str | None
    marker_source: str | None
    marker_confidence: float | None
    marker_evidence: str | None
    marker_characters: list[str] = field(default_factory=list)
    broll: list[tuple[str, str]] = field(default_factory=list)
    line_no: int = 0

    @property
    def is_ungrounded(self) -> bool:
        return (self.marker_source or "").lower() == "ungrounded"


@dataclass
class ClipPlan:
    index: int
    scene_start: str
    scene_end: str
    scene_source: str | None
    scene_confidence: float | None
    scene_evidence: str | None
    scene_characters: list[str]
    extracted_start: str
    extracted_end: str
    requested_duration_s: float
    extracted_duration_s: float
    pre_handle_s: float
    post_handle_s: float
    clip_path: str
    keyframe_time: str


def parse_scene_markers(script_path: Path) -> list[Scene]:
    scenes: list[Scene] = []
    current: Scene | None = None
    for line_no, raw in enumerate(script_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        marker = parse_scene_marker(line)
        if marker is not None:
            current = Scene(
                index=len(scenes) + 1,
                marker_start=marker.start,
                marker_end=marker.end,
                marker_source=marker.source,
                marker_confidence=marker.confidence,
                marker_evidence=marker.evidence,
                marker_characters=list(marker.characters),
                line_no=line_no,
            )
            scenes.append(current)
            continue
        broll_match = BROLL_LINE_RE.search(line)
        if broll_match and current is not None:
            current.broll.extend(parse_broll_ranges(broll_match.group(1)))
    return scenes


def find_supporting_visual_segment(
    scene: Scene,
    visual_segments: list[dict[str, object]],
) -> dict[str, object] | None:
    if not visual_segments or scene.marker_start is None or scene.marker_end is None:
        return None

    evidence = scene.marker_evidence
    if evidence is not None:
        for segment in visual_segments:
            if str(segment.get("id")) == evidence:
                return segment

    overlaps = overlapping_visual_segments(
        visual_segments,
        timestamp_to_seconds(scene.marker_start),
        timestamp_to_seconds(scene.marker_end),
    )
    if not overlaps:
        return None
    return max(overlaps, key=lambda segment: timestamp_to_seconds(str(segment["end"])))


def build_scene_clip_plan(
    scene: Scene,
    handle_seconds: float,
    visual_segments: list[dict[str, object]] | None = None,
    max_extension_seconds: float = DEFAULT_MAX_EXTENSION_SECONDS,
    video_duration_s: float | None = None,
) -> ClipPlan | None:
    if scene.marker_start is None or scene.marker_end is None:
        return None

    requested_start_s = timestamp_to_seconds(scene.marker_start)
    requested_end_s = timestamp_to_seconds(scene.marker_end)
    requested_duration_s = max(0.0, requested_end_s - requested_start_s)
    extracted_start_s = max(0.0, requested_start_s - handle_seconds)
    extracted_end_s = requested_end_s + handle_seconds

    supporting_segment = find_supporting_visual_segment(scene, visual_segments or [])
    if supporting_segment is not None:
        supporting_end_s = timestamp_to_seconds(str(supporting_segment["end"]))
        # Cap the "safe boundary extension": never run past the scene end by
        # more than max_extension_seconds even if a visual segment claims to
        # continue. This is the bound that stops a hallucinated 9-hour
        # segment from turning one clip into a full re-encode of the movie.
        extension_cap_s = requested_end_s + handle_seconds + max_extension_seconds
        extracted_end_s = min(max(extracted_end_s, supporting_end_s), extension_cap_s)

    if video_duration_s is not None:
        extracted_end_s = min(extracted_end_s, video_duration_s)
        extracted_start_s = min(extracted_start_s, extracted_end_s)

    pre_handle_s = requested_start_s - extracted_start_s
    post_handle_s = extracted_end_s - requested_end_s
    keyframe_time_s = requested_start_s + min(1.0, requested_duration_s / 2)

    return ClipPlan(
        index=scene.index,
        scene_start=scene.marker_start,
        scene_end=scene.marker_end,
        scene_source=scene.marker_source,
        scene_confidence=scene.marker_confidence,
        scene_evidence=scene.marker_evidence,
        scene_characters=list(scene.marker_characters),
        extracted_start=seconds_to_timestamp(extracted_start_s),
        extracted_end=seconds_to_timestamp(extracted_end_s),
        requested_duration_s=requested_duration_s,
        extracted_duration_s=max(0.0, extracted_end_s - extracted_start_s),
        pre_handle_s=pre_handle_s,
        post_handle_s=post_handle_s,
        clip_path=f"clip_{scene.index:03d}.mp4",
        keyframe_time=seconds_to_timestamp(keyframe_time_s),
    )


def extract_clip(video_path: Path, start_s: float, end_s: float, out_path: Path, codec: str) -> None:
    duration_s = max(0.0, end_s - start_s)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        seconds_to_timestamp(start_s),
        "-i",
        str(video_path),
        "-t",
        f"{duration_s:.3f}",
        "-an",
        *encoder_ffmpeg_args(codec),
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def extract_keyframe(video_path: Path, at_s: float, out_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        seconds_to_timestamp(at_s),
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def write_clip_manifest(output_dir: Path, clip_plans: list[ClipPlan], file_name: str) -> Path:
    manifest_path = output_dir / file_name
    manifest_path.write_text(
        json.dumps([asdict(plan) for plan in clip_plans], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-processor",
        description="Extract re-encoded hero clips, B-roll, and keyframes from grounded SCENE markers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--visual-segments", type=Path, help="Optional visual_segments.json for safe-boundary extension")
    parser.add_argument("--handle-seconds", type=float, default=DEFAULT_HANDLE_SECONDS)
    parser.add_argument(
        "--max-extension-seconds",
        type=float,
        default=DEFAULT_MAX_EXTENSION_SECONDS,
        help="Cap on safe-boundary extension beyond scene end. Prevents hallucinated visual segments from producing multi-minute clips.",
    )
    parser.add_argument(
        "--encoder",
        choices=ENCODER_CHOICES,
        default=DEFAULT_ENCODER,
        help="Video encoder. 'auto' picks h264_nvenc when available, otherwise libx264.",
    )
    parser.add_argument("--clip-manifest-name", default=DEFAULT_CLIP_MANIFEST)
    parser.add_argument("--skip-clips", action="store_true")
    parser.add_argument("--skip-keyframes", action="store_true")
    parser.add_argument("--skip-broll", action="store_true")
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
    if args.visual_segments is not None and not args.visual_segments.exists():
        print(f"Input not found: {args.visual_segments}", file=sys.stderr)
        return 1

    scenes = parse_scene_markers(script_path)
    if not scenes:
        print(f"No [SCENE ...] markers found in {script_path}", file=sys.stderr)
        return 1

    visual_segments = load_visual_segments(args.visual_segments)
    video_duration_s = get_video_duration(video_path)
    codec = resolve_encoder(args.encoder)
    clips_dir = output_dir / "clips"
    keyframes_dir = output_dir / "keyframes"
    if not args.skip_clips or not args.skip_broll:
        clips_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_keyframes:
        keyframes_dir.mkdir(parents=True, exist_ok=True)

    clip_plans: list[ClipPlan] = []
    for scene in scenes:
        plan = build_scene_clip_plan(
            scene,
            args.handle_seconds,
            visual_segments,
            max_extension_seconds=args.max_extension_seconds,
            video_duration_s=video_duration_s,
        )
        if plan is not None:
            clip_plans.append(plan)
    plan_by_index = {plan.index: plan for plan in clip_plans}
    broll_total = sum(len(s.broll) for s in scenes)
    print(
        f"Found {len(scenes)} [SCENE] markers and {broll_total} explicit [BROLL] ranges in {script_path.name}"
        f" (encoder={codec}, max-extension={args.max_extension_seconds:.1f}s, movie={video_duration_s:.1f}s)"
    )

    failures = 0
    for scene in scenes:
        clip_plan = plan_by_index.get(scene.index)

        if not args.skip_clips:
            if clip_plan is None:
                print(f"[clip {scene.index:>3}] no timed scene marker, skipping primary extraction")
            else:
                clip_path = clips_dir / clip_plan.clip_path
                print(
                    f"[clip {scene.index:>3}] {clip_plan.scene_start}->{clip_plan.scene_end} "
                    f"with handles {clip_plan.extracted_start}->{clip_plan.extracted_end}  {clip_path.name}"
                )
                try:
                    extract_clip(
                        video_path,
                        timestamp_to_seconds(clip_plan.extracted_start),
                        timestamp_to_seconds(clip_plan.extracted_end),
                        clip_path,
                        codec,
                    )
                except subprocess.CalledProcessError as exc:
                    print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                    failures += 1

        if not args.skip_broll and scene.broll:
            for i, (bs, be) in enumerate(scene.broll):
                suffix = chr(ord("a") + i)
                broll_path = clips_dir / f"broll_{scene.index:03d}_{suffix}.mp4"
                print(f"[brll {scene.index:>3}{suffix}] {bs}->{be}  {broll_path.name}")
                try:
                    extract_clip(
                        video_path,
                        timestamp_to_seconds(bs),
                        timestamp_to_seconds(be),
                        broll_path,
                        codec,
                    )
                except subprocess.CalledProcessError as exc:
                    print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                    failures += 1

        if not args.skip_keyframes and clip_plan is not None:
            keyframe_path = keyframes_dir / f"keyframe_{scene.index:03d}.jpg"
            try:
                extract_keyframe(video_path, timestamp_to_seconds(clip_plan.keyframe_time), keyframe_path)
            except subprocess.CalledProcessError as exc:
                print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                failures += 1

    if clip_plans:
        manifest_path = write_clip_manifest(output_dir, clip_plans, args.clip_manifest_name)
        print(f"Clip manifest -> {manifest_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
