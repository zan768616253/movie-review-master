"""Shared helpers for the workbench step scripts.

Loads the active movie's TOML config, resolves every path the 4-step
pipeline uses, and exposes a single Paths dataclass that step_*.py
consumes.
"""

from __future__ import annotations

import sys
import tomllib

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

WORKBENCH_ROOT = REPO_ROOT / "workbench"
WORK_ROOT = WORKBENCH_ROOT / "work"
DEFAULT_CONFIG = "configs/current_movie.toml"


@dataclass
class Paths:
    # Inputs (live with the source movie / chosen style)
    movie_dir: Path
    video: Path
    subtitle_srt: Path
    style: Path
    synopsis: Path
    characters_dir: Path

    # Per-stage work dirs under workbench/work/<movie_slug>/
    stage0_dir: Path
    stage1_dir: Path
    stage2_dir: Path
    stage3_dir: Path
    stage4_dir: Path

    # Stage 1 — visuals + subtitles
    visual_segments: Path
    subtitles_text: Path
    subtitles_json: Path
    thumbnails_dir: Path

    # Stage 2 — prompts + script
    outline_prompt: Path
    scene_markers: Path
    digest_prompt: Path
    plot_digest: Path
    story_prompt: Path
    script: Path
    hallucination_report: Path

    # Stage 3 — voiceover + SRT
    voiceover_mp3: Path
    voiceover_srt: Path
    voiceover_manifest: Path

    # Stage 4 — editor cheatsheet
    cheatsheet_html: Path

    # Voice reference assets (live with the style)
    voice_reference_dir: Path
    voice_reference_audio: Path
    voice_reference_text: Path
    voice_reference_analysis: Path


def resolve_repo_path(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


def get_tool_value(config: dict[str, Any], tool_name: str, key: str, default: Any = None) -> Any:
    tools = config.get("tools", {})
    if not isinstance(tools, dict):
        raise ValueError("[tools] must be a table in the harness config")
    tool_config = tools.get(tool_name, {}) or {}
    if not isinstance(tool_config, dict):
        raise ValueError(f"[tools.{tool_name}] must be a table in the harness config")
    return tool_config.get(key, default)


def get_optional_tool_path(config: dict[str, Any], tool_name: str, key: str) -> Path | None:
    raw_value = get_tool_value(config, tool_name, key)
    return resolve_repo_path(raw_value) if raw_value else None


def get_required_tool_path(config: dict[str, Any], tool_name: str, key: str) -> Path:
    raw_value = get_tool_value(config, tool_name, key)
    if not raw_value:
        raise ValueError(f"workbench/configs/current_movie.toml is missing [tools.{tool_name}].{key}")
    return resolve_repo_path(raw_value)


def load_config(config_path: str | Path) -> dict:
    config_path = Path(config_path)
    if not config_path.is_absolute():
        config_path = WORKBENCH_ROOT / config_path
    with config_path.open("rb") as f:
        return tomllib.load(f)


def build_paths(config: dict) -> Paths:
    common = config["common"]

    movie_slug = common["movie_slug"]
    movie_dir = resolve_repo_path(common["movie_dir"])
    style = resolve_repo_path(common["style_path"])

    work_dir = WORK_ROOT / movie_slug
    stage0_dir = work_dir / "stage0"
    stage1_dir = work_dir / "stage1"
    stage2_dir = work_dir / "stage2"
    stage3_dir = work_dir / "stage3"
    stage4_dir = work_dir / "stage4"

    tag = style.stem
    voiceover_basename = f"voiceover_{tag}"
    voice_reference_dir = style.parent / "voice-assets" / style.stem / "reference"

    return Paths(
        movie_dir=movie_dir,
        video=movie_dir / common["video_file"],
        subtitle_srt=movie_dir / common["subtitle_file"],
        style=style,
        synopsis=movie_dir / "synopsis.md",
        characters_dir=movie_dir / "characters",
        stage0_dir=stage0_dir,
        stage1_dir=stage1_dir,
        stage2_dir=stage2_dir,
        stage3_dir=stage3_dir,
        stage4_dir=stage4_dir,
        visual_segments=stage1_dir / "visual_segments.json",
        subtitles_text=stage1_dir / "subtitles.txt",
        subtitles_json=stage1_dir / "subtitles.json",
        thumbnails_dir=stage1_dir / "thumbnails",
        outline_prompt=stage2_dir / "outline_prompt.txt",
        scene_markers=stage2_dir / "scene_markers.json",
        digest_prompt=stage2_dir / "digest_prompt.txt",
        plot_digest=stage2_dir / "plot_digest.txt",
        story_prompt=stage2_dir / "story_prompt.txt",
        script=stage2_dir / "script.txt",
        hallucination_report=stage2_dir / "hallucination_report.json",
        voiceover_mp3=stage3_dir / f"{voiceover_basename}.mp3",
        voiceover_srt=stage3_dir / f"{voiceover_basename}.srt",
        voiceover_manifest=stage3_dir / f"{voiceover_basename}.manifest.json",
        cheatsheet_html=stage4_dir / "editor_cheatsheet.html",
        voice_reference_dir=voice_reference_dir,
        voice_reference_audio=voice_reference_dir / "clone_reference.mp3",
        voice_reference_text=voice_reference_dir / "clone_reference.txt",
        voice_reference_analysis=voice_reference_dir / "clone_reference.analysis.json",
    )


def ensure_stage_dirs(paths: Paths) -> None:
    for d in (paths.stage0_dir, paths.stage1_dir, paths.stage2_dir, paths.stage3_dir, paths.stage4_dir):
        d.mkdir(parents=True, exist_ok=True)


def banner(msg: str) -> None:
    print(f"\n{'=' * 8} {msg} {'=' * 8}", flush=True)


def fail(msg: str) -> int:
    print(f"\nERROR: {msg}", file=sys.stderr)
    return 1
