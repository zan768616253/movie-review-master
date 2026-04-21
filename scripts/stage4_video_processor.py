"""Extract silent video clips and keyframe JPGs at [SCENE] and [BROLL] timestamps.

Pipeline step [4] per the current handbook structure. Consumes a script with two marker types:
  - `[SCENE: HH:MM:SS-HH:MM:SS]` — one per narration chunk (primary visual).
  - `[BROLL: HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS, ...]` — optional cross-cuts
    that appear between `[SCENE]` and narration text; extracted as short B-roll
    clips that `render_video.py` rotates over the narration to hit genre-priority
    visual budgets (see styles/niu-shu.md §5.5b).

Outputs:
  {output_dir}/clips/clip_NNN.mp4                  # primary, per [SCENE]
  {output_dir}/clips/broll_NNN_a.mp4, _b.mp4 ...   # B-roll for chunk NNN
  {output_dir}/keyframes/keyframe_NNN.jpg          # primary only

No audio in clips (-an). Stream-copy video (-c:v copy) — fast, no re-encode.

Example:
  python -m scripts.stage4_video_processor \\
      --script movies/呪術回戦0/script_niu-shu_draft.txt \\
      --video movies/呪術回戦0/呪術回戦0.mkv \\
      --output-dir movies/呪術回戦0/output
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


SCENE_RE = re.compile(
    r"\[SCENE:\s*(\d{2}:\d{2}:\d{2})\s*-\s*(\d{2}:\d{2}:\d{2})\s*\]"
)
BROLL_LINE_RE = re.compile(r"\[BROLL:\s*([^\]]+?)\s*\]")
RANGE_RE = re.compile(r"(\d{2}:\d{2}:\d{2})\s*-\s*(\d{2}:\d{2}:\d{2})")


@dataclass
class Scene:
    index: int
    primary_start: str
    primary_end: str
    broll: list[tuple[str, str]] = field(default_factory=list)
    line_no: int = 0


def parse_scene_markers(script_path: Path) -> list[Scene]:
    """Walk the script, pairing each [SCENE] with any following [BROLL] lines
    that appear before the next [SCENE] or before narration text.
    """
    scenes: list[Scene] = []
    current: Scene | None = None
    for line_no, raw in enumerate(script_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        scene_match = SCENE_RE.search(line)
        if scene_match:
            current = Scene(
                index=len(scenes) + 1,
                primary_start=scene_match.group(1),
                primary_end=scene_match.group(2),
                line_no=line_no,
            )
            scenes.append(current)
            continue
        broll_match = BROLL_LINE_RE.search(line)
        if broll_match and current is not None:
            for m in RANGE_RE.finditer(broll_match.group(1)):
                current.broll.append((m.group(1), m.group(2)))
    return scenes


def timestamp_to_seconds(ts: str) -> int:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def extract_clip(video_path: Path, start: str, end: str, out_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        start,
        "-to",
        end,
        "-i",
        str(video_path),
        "-an",
        "-c:v",
        "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def extract_keyframe(video_path: Path, start: str, out_path: Path) -> None:
    offset = timestamp_to_seconds(start) + 1
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        str(offset),
        "-i",
        str(video_path),
        "-vframes",
        "1",
        "-q:v",
        "2",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="video-processor",
        description="Extract silent primary clips, B-roll, and keyframes at [SCENE]/[BROLL] markers.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--skip-clips", action="store_true")
    parser.add_argument("--skip-keyframes", action="store_true")
    parser.add_argument("--skip-broll", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    script_path = args.script.expanduser().resolve()
    video_path = args.video.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if not script_path.exists():
        print(f"Script not found: {script_path}", file=sys.stderr)
        return 1
    if not video_path.exists():
        print(f"Video not found: {video_path}", file=sys.stderr)
        return 1

    scenes = parse_scene_markers(script_path)
    if not scenes:
        print(f"No [SCENE: ...] markers found in {script_path}", file=sys.stderr)
        return 1

    clips_dir = output_dir / "clips"
    keyframes_dir = output_dir / "keyframes"
    if not args.skip_clips:
        clips_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_keyframes:
        keyframes_dir.mkdir(parents=True, exist_ok=True)

    broll_total = sum(len(s.broll) for s in scenes)
    print(f"Found {len(scenes)} [SCENE] markers and {broll_total} [BROLL] ranges in {script_path.name}")

    failures = 0
    for scene in scenes:
        if not args.skip_clips:
            clip_path = clips_dir / f"clip_{scene.index:03d}.mp4"
            print(f"[clip {scene.index:>3}] {scene.primary_start}->{scene.primary_end}  {clip_path.name}")
            try:
                extract_clip(video_path, scene.primary_start, scene.primary_end, clip_path)
            except subprocess.CalledProcessError as exc:
                print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                failures += 1

        if not args.skip_broll and scene.broll:
            for i, (bs, be) in enumerate(scene.broll):
                suffix = chr(ord("a") + i)
                broll_path = clips_dir / f"broll_{scene.index:03d}_{suffix}.mp4"
                print(f"[brll {scene.index:>3}{suffix}] {bs}->{be}  {broll_path.name}")
                try:
                    extract_clip(video_path, bs, be, broll_path)
                except subprocess.CalledProcessError as exc:
                    print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                    failures += 1

        if not args.skip_keyframes:
            keyframe_path = keyframes_dir / f"keyframe_{scene.index:03d}.jpg"
            try:
                extract_keyframe(video_path, scene.primary_start, keyframe_path)
            except subprocess.CalledProcessError as exc:
                print(f"  ffmpeg failed: {exc}", file=sys.stderr)
                failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
