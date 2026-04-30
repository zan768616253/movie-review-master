"""Step 6 — produce the upload-ready final video.

Combines:
  - Stage 5 draft review video
  - Stage 3 voiceover track

Writes: tmp/work/<movie_slug>/stage6/final_video.mp4
        tmp/work/<movie_slug>/stage6/delivery_manifest.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage6_finalize_video import main as stage6_main

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    required = [
        ("draft review video", paths.stage5_review_video),
        ("voiceover", paths.stage3_voiceover),
    ]
    for label, path in required:
        if not path.exists():
            return fail(f"{label} missing: {path}")

    banner(f"Stage 6 — finalize upload video for {cfg['common']['movie_title']}")
    print(f"review mp4 : {paths.stage5_review_video}")
    print(f"voiceover  : {paths.stage3_voiceover}")
    print(f"output     : {paths.final_video}")

    return stage6_main([
        "--review-video", str(paths.stage5_review_video),
        "--voiceover", str(paths.stage3_voiceover),
        "--output", str(paths.final_video),
        "--manifest-output", str(paths.final_video_manifest),
    ])


if __name__ == "__main__":
    raise SystemExit(run())