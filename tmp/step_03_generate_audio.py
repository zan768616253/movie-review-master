"""Step 3 — TTS the grounded script into one voiceover mp3 + manifest.

Reads:  tmp/work/<movie_slug>/stage2/grounded_script.txt
Writes: tmp/work/<movie_slug>/stage3/voiceover_<tag>_voiceclone.{mp3,manifest.json}

Tag defaults to the style filename stem (e.g. "niu-shu") unless overridden
in [stage3].tag in the config.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage3_generate_audio import main as stage3_main

CONFIG = "configs/jujutsu_kaisen_0.toml"


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.grounded_script.exists():
        return fail(
            f"Stage 2 grounded_script missing: {paths.grounded_script}\n"
            f"Run step_02_generate_script.py first."
        )

    tag = cfg.get("stage3", {}).get("tag")

    banner(f"Stage 3 — generate audio for {cfg['common']['movie_title']}")
    print(f"script     : {paths.grounded_script}")
    print(f"style      : {paths.style}")
    print(f"output dir : {paths.stage3_dir}")
    print(f"tag        : {tag or '(default, derived from style filename)'}")

    argv = [
        "--script", str(paths.grounded_script),
        "--style", str(paths.style),
        "--output-dir", str(paths.stage3_dir),
    ]
    if tag:
        argv.extend(["--tag", tag])
    return stage3_main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
