"""Harness for app.tools.voice_analysis using tmp/configs/current_movie.toml."""

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
    load_config,
)

from app.tools.voice_analysis import main as voice_analysis_main


CONFIG = DEFAULT_CONFIG
TOOL_NAME = "voice_analysis"


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    audio_path = get_optional_tool_path(cfg, TOOL_NAME, "audio") or paths.voice_reference_audio
    transcript_path = get_optional_tool_path(cfg, TOOL_NAME, "transcript") or paths.voice_reference_text
    out_path = get_optional_tool_path(cfg, TOOL_NAME, "out") or paths.voice_reference_analysis

    if not audio_path.is_file():
        return fail(f"audio not found: {audio_path}")
    if not transcript_path.is_file():
        return fail(f"transcript not found: {transcript_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    banner(f"Tool — voice analysis for {cfg['common']['movie_title']}")
    print(f"audio           : {audio_path}")
    print(f"transcript      : {transcript_path}")
    print(f"output          : {out_path}")

    args = [
        str(audio_path),
        "--transcript", str(transcript_path),
        "--out", str(out_path),
    ]
    return voice_analysis_main(args)


if __name__ == "__main__":
    raise SystemExit(run())