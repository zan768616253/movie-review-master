"""Step 4 — derive timed subtitle cues from the Stage 3 voiceover.

Reads:  tmp/work/<movie_slug>/stage3/voiceover_<tag>_voiceclone.{mp3,manifest.json}
Writes: tmp/work/<movie_slug>/stage4/subtitle_manifest.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage4_align_subtitles import main as stage4_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    required = [
        ("voiceover", paths.stage3_voiceover),
        ("voiceover manifest", paths.stage3_manifest),
    ]
    for label, path in required:
        if not path.exists():
            return fail(f"{label} missing: {path}")

    banner(f"Stage 4 — align subtitles for {cfg['common']['movie_title']}")
    print(f"voiceover  : {paths.stage3_voiceover}")
    print(f"manifest   : {paths.stage3_manifest}")
    print(f"output     : {paths.stage4_subtitle_manifest}")

    return stage4_main([
        "--manifest", str(paths.stage3_manifest),
        "--voiceover", str(paths.stage3_voiceover),
        "--output", str(paths.stage4_subtitle_manifest),
    ])


if __name__ == "__main__":
    raise SystemExit(run())
