"""Step 8 — concat fitted beats, burn subs, mux voiceover → review.mp4.

Reads:  tmp/work/<movie_slug>/stage6/fitted/beat_*.mp4
        tmp/work/<movie_slug>/stage5/voiceover_*.mp3
        tmp/work/<movie_slug>/stage7/subtitle_manifest.json
Writes: tmp/work/<movie_slug>/stage8/review.mp4

This file is a skeleton — the underlying module is not implemented yet.
See plan.md Phase 7. Note: this step depends on the Phase 6 rename of
`stage4_align_subtitles.py` → `stage7_align_subtitles.py` so that the
subtitle manifest path resolves correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage8_render_video import main as stage8_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.fitted_dir.exists():
        return fail(f"fitted dir not found: {paths.fitted_dir}")
    if not paths.voiceover.exists():
        return fail(f"voiceover not found: {paths.voiceover}")
    if not paths.subtitle_manifest.exists():
        return fail(f"subtitle manifest not found: {paths.subtitle_manifest}")

    banner(f"Stage 8 — render draft video for {cfg['common']['movie_title']}")
    print(f"fitted dir        : {paths.fitted_dir}")
    print(f"voiceover         : {paths.voiceover}")
    print(f"subtitle manifest : {paths.subtitle_manifest}")
    print(f"output            : {paths.review_video}")

    args = [
        "--fitted-dir", str(paths.fitted_dir),
        "--voiceover", str(paths.voiceover),
        "--subtitle-manifest", str(paths.subtitle_manifest),
        "--out", str(paths.review_video),
    ]
    return stage8_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
