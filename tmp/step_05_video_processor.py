"""Step 5 — extract per-anchor hero clips and keyframes from the anchored script.

Reads:  anchored_script.txt, movie video
Writes: tmp/work/<movie_slug>/stage5/{clips/, keyframes/, clip_manifest.json}

Multi-range anchors produce one clip per range (clip_007_a.mp4,
clip_007_b.mp4, ...). Single-range anchors produce one clip per chunk.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    DEFAULT_CONFIG,
    PLACEHOLDER_ANCHORED,
    banner,
    build_paths,
    ensure_stage_dirs,
    fail,
    is_filled,
    load_config,
)

from app.pipeline.stage5_video_processor import main as stage5_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not is_filled(paths.anchored_script, PLACEHOLDER_ANCHORED):
        return fail(
            f"anchored_script is missing or still contains the placeholder: {paths.anchored_script}\n"
            f"Run step_02_generate_script.py, paste the planner output, then re-run this step."
        )
    if not paths.video.exists():
        return fail(f"video missing: {paths.video}")

    banner(f"Stage 5 — extract clips & keyframes for {cfg['common']['movie_title']}")
    print(f"script     : {paths.anchored_script}")
    print(f"video      : {paths.video}")
    print(f"output dir : {paths.stage5_dir}")

    return stage5_main([
        "--script", str(paths.anchored_script),
        "--video", str(paths.video),
        "--output-dir", str(paths.stage5_dir),
    ])


if __name__ == "__main__":
    raise SystemExit(run())
