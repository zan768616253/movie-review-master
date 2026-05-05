"""Harness for app.tools.prepare_voice_reference using tmp/configs/current_movie.toml."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import (
    DEFAULT_CONFIG,
    banner,
    build_paths,
    ensure_stage_dirs,
    fail,
    get_optional_tool_path,
    get_required_tool_path,
    get_tool_value,
    load_config,
)

from app.tools.prepare_voice_reference import main as prepare_voice_reference_main


CONFIG = DEFAULT_CONFIG
TOOL_NAME = "prepare_voice_reference"


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    try:
        source_audio = get_required_tool_path(cfg, TOOL_NAME, "source_audio")
    except ValueError as exc:
        return fail(str(exc))

    transcript_path = get_optional_tool_path(cfg, TOOL_NAME, "transcript")
    clip_start = get_tool_value(cfg, TOOL_NAME, "start")
    clip_end = get_tool_value(cfg, TOOL_NAME, "end")

    if not paths.style.is_file():
        return fail(f"style file not found: {paths.style}")
    if not source_audio.is_file():
        return fail(f"source audio not found: {source_audio}")
    if transcript_path is not None and not transcript_path.is_file():
        return fail(f"transcript not found: {transcript_path}")

    banner(f"Tool — prepare voice reference for {cfg['common']['movie_title']}")
    print(f"source audio    : {source_audio}")
    print(f"style           : {paths.style}")
    print(f"transcript      : {transcript_path if transcript_path else '(auto-transcribe)'}")
    print(f"clip start      : {clip_start if clip_start else '(auto)'}")
    print(f"clip end        : {clip_end if clip_end else '(auto)'}")
    print(f"reference dir   : {paths.voice_reference_dir}")

    args = [
        str(source_audio),
        "--style", str(paths.style),
    ]
    if transcript_path is not None:
        args += ["--transcript", str(transcript_path)]
    if clip_start:
        args += ["--start", str(clip_start)]
    if clip_end:
        args += ["--end", str(clip_end)]

    return prepare_voice_reference_main(args)


if __name__ == "__main__":
    raise SystemExit(run())