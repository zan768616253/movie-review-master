"""Step 5 — render the final review video.

Combines:
  - Stage 3 voiceover + manifest
  - Stage 4 clips, keyframes, clip_manifest
  - Stage 0 visual_segments (used for semantic B-roll fallback)

Writes: tmp/work/<movie_slug>/stage5/review.mp4
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage5_render_video import main as stage5_main

CONFIG = "configs/jujutsu_kaisen_0.toml"


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
        ("video", paths.video),
        ("visual_segments", paths.visual_segments),
    ]
    for label, p in required:
        if not p.exists():
            return fail(f"{label} missing: {p}")

    banner(f"Stage 5 — render final video for {cfg['common']['movie_title']}")
    print(f"voiceover  : {paths.stage3_voiceover}")
    print(f"clips dir  : {paths.stage4_clips_dir}")
    print(f"output     : {paths.final_video}")

    return stage5_main([
        "--manifest", str(paths.stage3_manifest),
        "--voiceover", str(paths.stage3_voiceover),
        "--clips-dir", str(paths.stage4_clips_dir),
        "--keyframes-dir", str(paths.stage4_keyframes_dir),
        "--clip-manifest", str(paths.stage4_clip_manifest),
        "--video", str(paths.video),
        "--visual-segments", str(paths.visual_segments),
        "--output", str(paths.final_video),
    ])


if __name__ == "__main__":
    raise SystemExit(run())
