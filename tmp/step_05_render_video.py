"""Step 5 — render the draft review video.

Combines:
  - Stage 3 voiceover + manifest (anchored ranges + audio timing)
  - Stage 4 clips, keyframes, clip_manifest (per-range hero clips)
  - Stage 0 visual_segments (shot boundaries for shot-aware smart-trim)

Writes: tmp/work/<movie_slug>/stage5/review.mp4
        tmp/work/<movie_slug>/stage5/segments/segment_NNN.{mp4,mp3}
        tmp/work/<movie_slug>/stage5/edit_manifest.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage5_render_video import main as stage5_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    required = [
        ("voiceover", paths.stage3_voiceover),
        ("voiceover manifest", paths.stage3_manifest),
        ("clips dir", paths.stage4_clips_dir),
        ("keyframes dir", paths.stage4_keyframes_dir),
        ("clip manifest", paths.stage4_clip_manifest),
    ]
    for label, p in required:
        if not p.exists():
            return fail(f"{label} missing: {p}")

    banner(f"Stage 5 — render draft review video for {cfg['common']['movie_title']}")
    print(f"voiceover  : {paths.stage3_voiceover}")
    print(f"clips dir  : {paths.stage4_clips_dir}")
    print(f"output     : {paths.stage5_review_video}")

    argv = [
        "--manifest", str(paths.stage3_manifest),
        "--voiceover", str(paths.stage3_voiceover),
        "--clips-dir", str(paths.stage4_clips_dir),
        "--keyframes-dir", str(paths.stage4_keyframes_dir),
        "--clip-manifest", str(paths.stage4_clip_manifest),
        "--output", str(paths.stage5_review_video),
    ]
    # visual_segments is optional — when present, smart-trim uses its shot
    # boundaries to land cuts at clean shot junctions.
    if paths.visual_segments.exists():
        argv.extend(["--visual-segments", str(paths.visual_segments)])
    return stage5_main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
