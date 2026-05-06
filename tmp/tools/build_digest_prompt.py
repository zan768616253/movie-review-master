"""Harness for app.tools.build_digest_prompt using tmp/configs/current_movie.toml."""

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

from app.tools.build_digest_prompt import main as build_digest_prompt_main


CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    output_path = (
        get_optional_tool_path(cfg, "build_digest_prompt", "out")
        or paths.tools_dir / "digest_prompt.txt"
    )

    if not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")
    if not paths.visual_segments.is_file():
        return fail(f"visual segments not found: {paths.visual_segments}")
    if not paths.subtitles_text.is_file():
        return fail(f"subtitles txt not found: {paths.subtitles_text}")

    target_seconds = cfg["common"].get("target_seconds", 720.0)
    target_minutes = target_seconds / 60.0

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Pre-create files for user to paste LLM results
    digest_path = (
        get_optional_tool_path(cfg, "build_story_prompt", "plot_digest")
        or paths.tools_dir / "plot_digest.txt"
    )
    scripts_path = paths.tools_dir / "scripts.txt"
    
    digest_path.touch(exist_ok=True)
    scripts_path.touch(exist_ok=True)

    banner(f"Tool — build digest prompt for {cfg['common']['movie_title']}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles txt   : {paths.subtitles_text}")
    print(f"target minutes  : {target_minutes:.1f}")
    print(f"output prompt   : {output_path}")
    print(f"-> created empty: {digest_path.name} (paste digest LLM output here)")
    print(f"-> created empty: {scripts_path.name} (paste final script LLM output here)")

    args = [
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--target-minutes", str(target_minutes),
        "--out", str(output_path),
    ]

    return build_digest_prompt_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
