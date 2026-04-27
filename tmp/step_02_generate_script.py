"""Step 2 — write the writer + grounder prompts for the LLM.

This step is a two-phase manual loop:

  1. First run            : writes writer_prompt.txt; you paste it into an LLM,
                            then paste the LLM's reply into writer_beats.txt.
  2. Run again            : writes grounder_prompt.txt; you paste it into the LLM,
                            then paste the LLM's reply into grounded_script.txt.
  3. Run again (optional) : reports "all done — Stage 2 complete".

Files live under tmp/work/<movie_slug>/stage2/.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    PLACEHOLDER_BEATS,
    PLACEHOLDER_GROUNDED,
    banner,
    build_paths,
    ensure_stage_dirs,
    fail,
    is_filled,
    load_config,
)

from app.pipeline.stage2_generate_script import (
    build_grounding_prompt,
    build_writer_prompt,
)

CONFIG = "configs/jujutsu_kaisen_0.toml"


def writer_override(target_seconds: float, genre: str) -> str:
    minutes = target_seconds / 60.0
    return (
        "# Harness Override\n"
        f"Ignore any default runtime target below. Target about {minutes:.1f} minutes of narration "
        f"(~{int(minutes * 180)}-{int(minutes * 280)} Chinese characters). "
        f"Prefer a {genre}-forward cut.\n\n"
    )


def grounder_override(genre: str) -> str:
    return (
        "# Harness Override\n"
        f"This run is {genre}-forward. When multiple visual candidates are similarly valid, "
        "prefer footage that matches the genre. Preserve beat wording unless a tiny fix is "
        "needed for grounding clarity.\n\n"
    )


def seed_placeholders(paths) -> None:
    if not paths.writer_beats.exists():
        paths.writer_beats.write_text(PLACEHOLDER_BEATS, encoding="utf-8")
    if not paths.grounded_script.exists():
        paths.grounded_script.write_text(PLACEHOLDER_GROUNDED, encoding="utf-8")


def run() -> int:
    cfg = load_config(CONFIG)
    common = cfg["common"]
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.visual_segments.exists():
        return fail(
            f"Stage 0 output missing: {paths.visual_segments}\n"
            f"Run step_00_index_visuals.py first."
        )

    seed_placeholders(paths)

    # Phase 1: writer beats not filled in yet → produce writer prompt.
    if not is_filled(paths.writer_beats, PLACEHOLDER_BEATS):
        banner("Stage 2a — writer prompt")
        prompt = writer_override(common["target_seconds"], common["genre"]) + build_writer_prompt(
            style_path=paths.style,
            subtitle_srt_path=paths.subtitle_srt,
            visual_segments_path=paths.visual_segments,
            movie_title=common["movie_title"],
            genre=common["genre"],
        )
        paths.writer_prompt.write_text(prompt, encoding="utf-8")
        print(f"Wrote: {paths.writer_prompt}")
        print(f"\nNext: paste the prompt above into an LLM, then paste its reply into:")
        print(f"  {paths.writer_beats}")
        print(f"Then re-run this script.")
        return 0

    # Phase 2: writer beats filled, grounded script not → produce grounder prompt.
    if not is_filled(paths.grounded_script, PLACEHOLDER_GROUNDED):
        banner("Stage 2b — grounder prompt")
        prompt = grounder_override(common["genre"]) + build_grounding_prompt(
            beats_path=paths.writer_beats,
            subtitle_srt_path=paths.subtitle_srt,
            visual_segments_path=paths.visual_segments,
            movie_title=common["movie_title"],
        )
        paths.grounder_prompt.write_text(prompt, encoding="utf-8")
        print(f"Wrote: {paths.grounder_prompt}")
        print(f"\nNext: paste the prompt above into an LLM, then paste its reply into:")
        print(f"  {paths.grounded_script}")
        print(f"Then run step_03_generate_audio.py (or run_all.py).")
        return 0

    banner("Stage 2 — already complete")
    print(f"writer beats    : {paths.writer_beats}")
    print(f"grounded script : {paths.grounded_script}")
    print("Both files are filled. Move on to step_03_generate_audio.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
