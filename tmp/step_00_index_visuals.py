"""Step 0 — visual indexing with Gemini.

Reads:  <movie>.mkv
Writes: tmp/work/<movie_slug>/stage0/visual_segments.json

Run this file directly in VSCode (the ▶ button uses the "Current File"
launch config). To switch movies, edit tmp/configs/current_movie.toml.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage0_index_visuals import main as stage0_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.video.exists():
        return fail(f"video not found: {paths.video}")

    banner(f"Stage 0 — index visuals for {cfg['common']['movie_title']}")
    print(f"video         : {paths.video}")
    print(f"output        : {paths.visual_segments}")
    print(f"chunk tmp dir : {paths.stage0_dir / 'tmp'}")

    return stage0_main([
        "--video", str(paths.video),
        "--output", str(paths.visual_segments),
        "--tmp-dir", str(paths.stage0_dir / "tmp"),
        "--workers", "5",
    ])


if __name__ == "__main__":
    raise SystemExit(run())
