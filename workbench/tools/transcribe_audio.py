"""Harness for app.tools.transcribe_audio using tmp/configs/current_movie.toml."""

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
    get_tool_value,
    load_config,
)

from app.tools.transcribe_audio import main as transcribe_audio_main


CONFIG = DEFAULT_CONFIG
TOOL_NAME = "transcribe_audio"


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    input_path = get_optional_tool_path(cfg, TOOL_NAME, "input_path") or paths.voice_reference_dir
    language = get_tool_value(cfg, TOOL_NAME, "language", "zh")

    if not input_path.exists():
        return fail(f"transcribe input path not found: {input_path}")

    banner(f"Tool — transcribe audio for {cfg['common']['movie_title']}")
    print(f"input path      : {input_path}")
    print(f"language        : {language}")

    args = [str(input_path)]
    if language is not None:
        args += ["--language", str(language)]

    return transcribe_audio_main(args)


if __name__ == "__main__":
    raise SystemExit(run())