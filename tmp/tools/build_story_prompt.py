"""Harness for app.tools.build_story_prompt using tmp/configs/current_movie.toml."""

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

from app.tools.build_story_prompt import main as build_story_prompt_main


CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    output_path = get_optional_tool_path(cfg, "build_story_prompt", "out") or paths.story_prompt

    if not paths.style.is_file():
        return fail(f"style file not found: {paths.style}")
    if not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")
    if not paths.visual_segments.is_file():
        return fail(f"visual segments not found: {paths.visual_segments}")
    if not paths.subtitles_text.is_file():
        return fail(f"subtitles txt not found: {paths.subtitles_text}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    banner(f"Tool — build story prompt for {cfg['common']['movie_title']}")
    print(f"style           : {paths.style}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles txt   : {paths.subtitles_text}")
    print(f"output          : {output_path}")

    args = [
        "--style", str(paths.style),
        "--synopsis", str(paths.synopsis),
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(output_path),
    ]

    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])

    return build_story_prompt_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
