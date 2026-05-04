"""Step 6 — trim/extend each rough-cut beat to match its TTS duration.

Reads:  tmp/work/<movie_slug>/stage3/rough_cut.json
        tmp/work/<movie_slug>/stage3/rough_cut.mp4
        tmp/work/<movie_slug>/stage5/voiceover_*.manifest.json
Writes: tmp/work/<movie_slug>/stage6/fitted/beat_NNN.mp4

This file is a skeleton — the underlying module is not implemented yet.
See plan.md Phase 5.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage6_fit_visuals import main as stage6_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.rough_cut_manifest.exists():
        return fail(f"rough cut manifest not found: {paths.rough_cut_manifest}")
    if not paths.rough_cut_video.exists():
        return fail(f"rough cut video not found: {paths.rough_cut_video}")
    if not paths.voiceover_manifest.exists():
        return fail(f"voiceover manifest not found: {paths.voiceover_manifest}")

    banner(f"Stage 6 — fit visuals for {cfg['common']['movie_title']}")
    print(f"rough cut json  : {paths.rough_cut_manifest}")
    print(f"rough cut video : {paths.rough_cut_video}")
    print(f"voiceover mfst  : {paths.voiceover_manifest}")
    print(f"out dir         : {paths.stage6_dir}")

    args = [
        "--rough-cut-manifest", str(paths.rough_cut_manifest),
        "--rough-cut-video", str(paths.rough_cut_video),
        "--voiceover-manifest", str(paths.voiceover_manifest),
        "--out-dir", str(paths.stage6_dir),
    ]
    return stage6_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
