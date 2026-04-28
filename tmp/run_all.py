"""Run all steps end-to-end for one movie, stopping at Stage 2 for manual input.

Each step is skipped when its output already exists, so this is safe to
re-run any number of times.

Flow:
    step_00 → step_01 → [STOP at step_02 if anchored_script
    not filled] → step_03 → step_04 → step_05 → step_06

To run a different movie, edit tmp/configs/current_movie.toml.
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

import step_00_index_visuals
import step_01_parse_subtitles
import step_03_generate_audio
import step_04_video_processor
import step_05_render_video
import step_06_finalize_video

CONFIG = DEFAULT_CONFIG


def _set_config(*modules) -> None:
    for m in modules:
        m.CONFIG = CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    _set_config(
        step_00_index_visuals,
        step_01_parse_subtitles,
        step_03_generate_audio,
        step_04_video_processor,
        step_05_render_video,
        step_06_finalize_video,
    )

    # Stage 0
    if paths.visual_segments.exists():
        banner("Stage 0 — skipping (visual_segments.json already exists)")
        print(f"  {paths.visual_segments}")
    else:
        rc = step_00_index_visuals.run()
        if rc != 0:
            return rc

    # Stage 1
    if paths.subtitles_text.exists():
        banner("Stage 1 — skipping (subtitles.txt already exists)")
        print(f"  {paths.subtitles_text}")
    else:
        rc = step_01_parse_subtitles.run()
        if rc != 0:
            return rc

    # Stage 2 — manual. Stop here unless the anchored script is filled.
    if not is_filled(paths.anchored_script, PLACEHOLDER_ANCHORED):
        banner("Stage 2 — STOP: manual step required")
        print("Anchored script not yet filled. Run:")
        print("  conda run -n py312_machine_learning --no-capture-output \\")
        print("    python tmp/step_02_generate_script.py")
        print(f"\nThen paste the LLM output into:")
        print(f"  {paths.anchored_script}")
        print(f"\nWhen anchored_script.txt is filled, re-run this script.")
        return 0
    print(f"\nStage 2 already complete: {paths.anchored_script}")

    # Stage 3
    if paths.stage3_voiceover.exists() and paths.stage3_manifest.exists():
        banner("Stage 3 — skipping (voiceover already exists)")
        print(f"  {paths.stage3_voiceover}")
    else:
        rc = step_03_generate_audio.run()
        if rc != 0:
            return rc

    # Stage 4
    if paths.stage4_clip_manifest.exists():
        banner("Stage 4 — skipping (clip_manifest.json already exists)")
        print(f"  {paths.stage4_clip_manifest}")
    else:
        rc = step_04_video_processor.run()
        if rc != 0:
            return rc

    # Stage 5
    if paths.stage5_review_video.exists():
        banner("Stage 5 — skipping (draft review video already exists)")
        print(f"  {paths.stage5_review_video}")
    else:
        rc = step_05_render_video.run()
        if rc != 0:
            return rc

    # Stage 6
    if paths.final_video.exists():
        banner("Stage 6 — skipping (upload-ready final video already exists)")
        print(f"  {paths.final_video}")
    else:
        rc = step_06_finalize_video.run()
        if rc != 0:
            return rc

    banner("All stages complete")
    print(f"Final video: {paths.final_video}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
