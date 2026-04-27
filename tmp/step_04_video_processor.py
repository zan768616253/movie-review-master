"""Step 4 — extract hero clips, B-roll, and keyframes from the grounded script.

Reads:  grounded_script.txt, movie video, visual_segments.json
Writes: tmp/work/<movie_slug>/stage4/{clips/, keyframes/, clip_manifest.json}
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage4_video_processor import main as stage4_main

CONFIG = "configs/jujutsu_kaisen_0.toml"


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.grounded_script.exists():
        return fail(f"grounded_script missing: {paths.grounded_script}")
    if not paths.video.exists():
        return fail(f"video missing: {paths.video}")
    if not paths.visual_segments.exists():
        return fail(f"visual_segments missing: {paths.visual_segments}")

    banner(f"Stage 4 — extract clips & keyframes for {cfg['common']['movie_title']}")
    print(f"script           : {paths.grounded_script}")
    print(f"video            : {paths.video}")
    print(f"visual_segments  : {paths.visual_segments}")
    print(f"output dir       : {paths.stage4_dir}")

    return stage4_main([
        "--script", str(paths.grounded_script),
        "--video", str(paths.video),
        "--output-dir", str(paths.stage4_dir),
        "--visual-segments", str(paths.visual_segments),
    ])


if __name__ == "__main__":
    raise SystemExit(run())
