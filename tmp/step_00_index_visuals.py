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

    args = [
        "--video", str(paths.video),
        "--output", str(paths.visual_segments),
        "--tmp-dir", str(paths.stage0_dir / "tmp"),
        "--workers", "5",
    ]
    # Auto-attach the movie's synopsis as a Cast Reference when available.
    # This lets the VLM apply consistent character names across chunks
    # without risking franchise-knowledge over-attribution.
    if paths.synopsis.exists():
        print(f"synopsis      : {paths.synopsis}")
        args += ["--synopsis", str(paths.synopsis)]
    else:
        print(f"synopsis      : (none — no Cast Reference will be passed to the VLM)")

    # Auto-attach Face Gallery if a characters directory exists next to the video.
    chars_dir = paths.video.parent / "characters"
    if chars_dir.exists() and chars_dir.is_dir():
        print(f"face gallery  : {chars_dir}")
        args += ["--characters-dir", str(chars_dir)]
    else:
        print(f"face gallery  : (none)")

    return stage0_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
