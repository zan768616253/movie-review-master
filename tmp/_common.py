"""Shared helpers for the per-step scripts in tmp/.

Loads a TOML config, resolves all paths used by the new video-driven
pipeline, and exposes a single Paths dataclass that every step_*.py
file consumes.

Keep this small. If a helper only matters to one stage, put it in that
step file, not here.

Stage numbers below correspond to the **target** layout in
docs/HANDBOOK.md §6 / docs/TECHNICAL.md §5. Surviving legacy modules
(`stage4_align_subtitles.py`, `stage7_finalize_video.py`) still live
under their old names in `app/pipeline/` until the renames in plan.md
Phases 6 and 8 — the path slots here use the **new** semantic stage
numbers (`stage7_dir`, `stage9_dir`) regardless.
"""

from __future__ import annotations

import sys
import tomllib

from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = REPO_ROOT / "tmp"
WORK_ROOT = TMP_ROOT / "work"
DEFAULT_CONFIG = "configs/current_movie.toml"


@dataclass
class Paths:
    # Inputs from the movie folder
    movie_dir: Path
    video: Path
    subtitle_srt: Path
    style: Path
    synopsis: Path  # optional; user-authored plot/cast/context

    # Per-stage work dirs (under tmp/work/<movie_slug>/)
    stage0_dir: Path
    stage1_dir: Path
    stage2_dir: Path
    stage3_dir: Path
    stage4_dir: Path
    stage5_dir: Path
    stage6_dir: Path
    stage7_dir: Path
    stage8_dir: Path
    stage9_dir: Path

    # Stage 0
    visual_segments: Path

    # Stage 1
    subtitles_text: Path
    subtitles_json: Path

    # Stage 2
    selected_shots: Path

    # Stage 3
    rough_cut_video: Path
    rough_cut_manifest: Path

    # Stage 4
    narration_prompt: Path
    narration: Path

    # Stage 5
    voiceover: Path
    voiceover_manifest: Path

    # Stage 6
    fitted_dir: Path

    # Stage 7 (current `stage4_align_subtitles.py` writes here)
    subtitle_manifest: Path

    # Stage 8
    review_video: Path

    # Stage 9 (current `stage7_finalize_video.py` writes here)
    final_video: Path
    final_video_manifest: Path


def load_config(config_path: str | Path) -> dict:
    """Read a TOML config file and return its contents as a dict."""
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = TMP_ROOT / config_path
    with config_path.open("rb") as f:
        return tomllib.load(f)


def build_paths(config: dict) -> Paths:
    """Resolve every path the pipeline cares about from a loaded config dict."""
    common = config["common"]

    movie_slug = common["movie_slug"]
    movie_dir = (REPO_ROOT / common["movie_dir"]).resolve()
    style = (REPO_ROOT / common["style_path"]).resolve()
    video = movie_dir / common["video_file"]
    subtitle_srt = movie_dir / common["subtitle_file"]

    work_dir = WORK_ROOT / movie_slug
    stage0_dir = work_dir / "stage0"
    stage1_dir = work_dir / "stage1"
    stage2_dir = work_dir / "stage2"
    stage3_dir = work_dir / "stage3"
    stage4_dir = work_dir / "stage4"
    stage5_dir = work_dir / "stage5"
    stage6_dir = work_dir / "stage6"
    stage7_dir = work_dir / "stage7"
    stage8_dir = work_dir / "stage8"
    stage9_dir = work_dir / "stage9"

    # Voiceover filename follows the legacy convention so the surviving
    # subtitle-alignment module finds it without changes:
    #   voiceover_<style-stem>_voiceclone.{mp3,manifest.json}
    tag = style.stem
    voiceover_basename = f"voiceover_{tag}_voiceclone"

    return Paths(
        movie_dir=movie_dir,
        video=video,
        subtitle_srt=subtitle_srt,
        style=style,
        synopsis=movie_dir / "synopsis.md",
        stage0_dir=stage0_dir,
        stage1_dir=stage1_dir,
        stage2_dir=stage2_dir,
        stage3_dir=stage3_dir,
        stage4_dir=stage4_dir,
        stage5_dir=stage5_dir,
        stage6_dir=stage6_dir,
        stage7_dir=stage7_dir,
        stage8_dir=stage8_dir,
        stage9_dir=stage9_dir,
        visual_segments=stage0_dir / "visual_segments.json",
        subtitles_text=stage1_dir / "subtitles.txt",
        subtitles_json=stage1_dir / "subtitles.json",
        selected_shots=stage2_dir / "selected_shots.json",
        rough_cut_video=stage3_dir / "rough_cut.mp4",
        rough_cut_manifest=stage3_dir / "rough_cut.json",
        narration_prompt=stage4_dir / "narration_prompt.txt",
        narration=stage4_dir / "narration.json",
        voiceover=stage5_dir / f"{voiceover_basename}.mp3",
        voiceover_manifest=stage5_dir / f"{voiceover_basename}.manifest.json",
        fitted_dir=stage6_dir / "fitted",
        subtitle_manifest=stage7_dir / "subtitle_manifest.json",
        review_video=stage8_dir / "review.mp4",
        final_video=stage9_dir / "final_video.mp4",
        final_video_manifest=stage9_dir / "delivery_manifest.json",
    )


def ensure_stage_dirs(paths: Paths) -> None:
    for d in (
        paths.stage0_dir,
        paths.stage1_dir,
        paths.stage2_dir,
        paths.stage3_dir,
        paths.stage4_dir,
        paths.stage5_dir,
        paths.stage6_dir,
        paths.stage7_dir,
        paths.stage8_dir,
        paths.stage9_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)


def banner(msg: str) -> None:
    print(f"\n{'=' * 8} {msg} {'=' * 8}", flush=True)


def fail(msg: str) -> int:
    print(f"\nERROR: {msg}", file=sys.stderr)
    return 1
