"""Step [5] per HANDBOOK: stitch hero clips to narration and mux the voiceover.

Stage 1 (this file): minimal viable render.
  - Hard cuts, no transitions.
  - No BGM, no subtitle burn.
  - Uses keyframe freeze for the closing chunk (no [SCENE]) and as fallback when a
    clip is shorter than its narration.

Inputs expected (all produced by earlier pipeline steps):
  - manifest: {voiceover}.manifest.json from generate_audio.py
  - voiceover: .mp3 from generate_audio.py
  - clips: output/clips/clip_NNN.mp4 from video_processor.py
  - keyframes: output/keyframes/keyframe_NNN.jpg from video_processor.py

Output:
  output/final_video.mp4
  output/segments/segment_NNN.mp4  (intermediate, preserved for debug)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


TARGET_WIDTH = 1920
TARGET_HEIGHT = 1080
TARGET_FPS = 30


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(out.stdout.strip())


def normalize_scale_filter() -> str:
    return (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={TARGET_FPS}"
    )


def render_single_clip(
    clip_path: Path,
    target_duration: float,
    out_path: Path,
) -> None:
    clip_dur = probe_duration(clip_path)
    vf_parts = [normalize_scale_filter()]
    if clip_dur < target_duration:
        pad = target_duration - clip_dur + 0.05
        vf_parts.append(f"tpad=stop_mode=clone:stop_duration={pad:.3f}")
    vf = ",".join(vf_parts)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(clip_path),
        "-t",
        f"{target_duration:.3f}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def render_clip_segment(
    clip_paths: list[Path],
    target_duration: float,
    out_path: Path,
) -> None:
    """Render a chunk's segment. If multiple clip_paths are given (primary + B-roll),
    divide target_duration evenly across them, producing a concatenated segment."""
    if len(clip_paths) == 1:
        render_single_clip(clip_paths[0], target_duration, out_path)
        return
    sub_dur = target_duration / len(clip_paths)
    sub_paths: list[Path] = []
    for i, cp in enumerate(clip_paths):
        sub_path = out_path.with_name(f"{out_path.stem}_sub{i}.mp4")
        render_single_clip(cp, sub_dur, sub_path)
        sub_paths.append(sub_path)
    concat_segments(sub_paths, out_path)
    for sp in sub_paths:
        sp.unlink(missing_ok=True)


def render_stillframe_segment(
    image_path: Path,
    target_duration: float,
    out_path: Path,
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
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
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
        description="Step [5] Stage 1: stitch hero clips to voiceover manifest.",
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
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if not args.manifest.exists():
        print(f"Manifest not found: {args.manifest}", file=sys.stderr)
        return 1
    if not args.voiceover.exists():
        print(f"Voiceover not found: {args.voiceover}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(f"Manifest: {len(manifest)} chunks")

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

        if entry["scene_start"] is None:
            if last_clip_number is None:
                print(f"  chunk {idx}: closing chunk with no preceding clip — aborting", file=sys.stderr)
                return 1
            still = args.keyframes_dir / f"keyframe_{last_clip_number:03d}.jpg"
            if not still.exists():
                print(f"  chunk {idx}: keyframe not found: {still}", file=sys.stderr)
                return 1
            print(f"  chunk {idx:>3} (closing): still {still.name} x {target_dur:.2f}s", end=" ")
            render_stillframe_segment(still, target_dur, segment_path)
        else:
            clip_paths: list[Path] = [args.clips_dir / f"clip_{idx:03d}.mp4"]
            if not clip_paths[0].exists():
                print(f"  chunk {idx}: clip not found: {clip_paths[0]}", file=sys.stderr)
                return 1
            broll_ranges = entry.get("broll") or []
            for i, _ in enumerate(broll_ranges):
                suffix = chr(ord("a") + i)
                broll_path = args.clips_dir / f"broll_{idx:03d}_{suffix}.mp4"
                if not broll_path.exists():
                    print(f"  chunk {idx}: B-roll missing: {broll_path}", file=sys.stderr)
                    return 1
                clip_paths.append(broll_path)
            files_desc = (
                clip_paths[0].name
                if len(clip_paths) == 1
                else f"{clip_paths[0].name} + {len(clip_paths)-1} B-roll"
            )
            print(f"  chunk {idx:>3}: {files_desc} over {target_dur:.2f}s", end=" ")
            render_clip_segment(clip_paths, target_dur, segment_path)
            last_clip_number = idx

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
