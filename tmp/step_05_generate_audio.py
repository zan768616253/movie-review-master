"""Step 5 — TTS the narration into a voiceover and emit a manifest.

Reads:  tmp/work/<movie_slug>/stage4/narration.json
        styles/<style>.md (resolves the voice-clone reference)
Writes: tmp/work/<movie_slug>/stage5/voiceover_<tag>_voiceclone.mp3
        tmp/work/<movie_slug>/stage5/voiceover_<tag>_voiceclone.manifest.json

This file is a skeleton — the underlying module is not implemented yet.
See plan.md Phase 3.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage5_generate_audio import main as stage5_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.narration.exists():
        return fail(f"narration not found: {paths.narration}")
    if not paths.style.exists():
        return fail(f"style file not found: {paths.style}")

    banner(f"Stage 5 — generate voiceover for {cfg['common']['movie_title']}")
    print(f"narration : {paths.narration}")
    print(f"style     : {paths.style}")
    print(f"out dir   : {paths.stage5_dir}")

    args = [
        "--narration", str(paths.narration),
        "--style", str(paths.style),
        "--out-dir", str(paths.stage5_dir),
    ]
    return stage5_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
