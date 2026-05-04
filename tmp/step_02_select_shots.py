"""Step 2 — scaffold or validate the high-information shot selection.

Reads:  tmp/work/<movie_slug>/stage0/visual_segments.json
Writes: tmp/work/<movie_slug>/stage2/selected_shots.json

First run produces a scaffold with all shots `keep=false`. Open the file
in VSCode, flip `keep=true` on the shots that should appear in the
review, save, and re-run with `validate=True` (edit the call below) to
verify the result.

This file is a skeleton — the underlying module is not implemented yet.
See plan.md Phase 1.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage2_select_shots import main as stage2_main

CONFIG = DEFAULT_CONFIG


def run(validate: bool = False) -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.visual_segments.exists():
        return fail(f"visual segments not found: {paths.visual_segments}")

    banner(f"Stage 2 — select shots for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"output          : {paths.selected_shots}")
    print(f"mode            : {'validate' if validate else 'scaffold'}")

    args = [
        "--visual-segments", str(paths.visual_segments),
        "--out", str(paths.selected_shots),
    ]
    if validate:
        args.append("--validate")

    return stage2_main(args)


if __name__ == "__main__":
    raise SystemExit(run(validate=False))
