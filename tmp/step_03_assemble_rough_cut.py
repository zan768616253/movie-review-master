"""Step 3 — assemble the rough cut from selected shots.

Reads:  tmp/work/<movie_slug>/stage2/selected_shots.json
        movies/<...>/<video>.mkv
Writes: tmp/work/<movie_slug>/stage3/rough_cut.mp4
        tmp/work/<movie_slug>/stage3/rough_cut.json

This file is a skeleton — the underlying module is not implemented yet.
See plan.md Phase 2.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage3_assemble_rough_cut import main as stage3_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.video.exists():
        return fail(f"video not found: {paths.video}")
    if not paths.selected_shots.exists():
        return fail(f"selected shots not found: {paths.selected_shots}")

    banner(f"Stage 3 — assemble rough cut for {cfg['common']['movie_title']}")
    print(f"video          : {paths.video}")
    print(f"selected shots : {paths.selected_shots}")
    print(f"output dir     : {paths.stage3_dir}")

    args = [
        "--movie", str(paths.video),
        "--selected-shots", str(paths.selected_shots),
        "--out-dir", str(paths.stage3_dir),
    ]
    return stage3_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
