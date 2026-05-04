"""Step 3 — TTS the anchored script into one voiceover mp3 + manifest.

Reads:  tmp/work/<movie_slug>/stage2/anchored_script.txt
Writes: tmp/work/<movie_slug>/stage3/voiceover_<tag>_voiceclone.{mp3,manifest.json}

Tag defaults to the style filename stem (e.g. "niu-shu") unless overridden
in [stage3].tag in the config.
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
from app.pipeline.stage3_generate_audio import main as stage3_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not is_filled(paths.anchored_script, PLACEHOLDER_ANCHORED):
        return fail(
            f"Stage 2 anchored_script is missing or still contains the placeholder: {paths.anchored_script}\n"
            f"Run step_02_generate_script.py, paste the planner output, then re-run this step."
        )

    tag = cfg.get("stage3", {}).get("tag")

    banner(f"Stage 3 — generate audio for {cfg['common']['movie_title']}")
    print(f"script     : {paths.anchored_script}")
    print(f"style      : {paths.style}")
    print(f"output dir : {paths.stage3_dir}")
    print(f"tag        : {tag or '(default, derived from style filename)'}")

    argv = [
        "--script", str(paths.anchored_script),
        "--style", str(paths.style),
        "--output-dir", str(paths.stage3_dir),
    ]
    if tag:
        argv.extend(["--tag", tag])
    return stage3_main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
