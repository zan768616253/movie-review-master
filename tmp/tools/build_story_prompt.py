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

    # --- Auto-detect digest mode ---
    # If plot_digest.txt exists in the tools dir, use two-pass digest mode.
    # Otherwise fall back to the original single-pass timeline mode.
    digest_path = (
        get_optional_tool_path(cfg, "build_story_prompt", "plot_digest")
        or paths.tools_dir / "plot_digest.txt"
    )
    use_digest = digest_path.is_file()

    if not use_digest:
        if not paths.visual_segments.is_file():
            return fail(f"visual segments not found: {paths.visual_segments}")
        if not paths.subtitles_text.is_file():
            return fail(f"subtitles txt not found: {paths.subtitles_text}")

    # --- Target minutes from config ---
    target_seconds = cfg["common"].get("target_seconds")
    target_minutes = target_seconds / 60.0 if target_seconds else None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    scripts_path = paths.tools_dir / "scripts.txt"
    scripts_path.touch(exist_ok=True)

    mode_label = "DIGEST (two-pass)" if use_digest else "TIMELINE (single-pass)"
    banner(f"Tool — build story prompt for {cfg['common']['movie_title']} [{mode_label}]")
    print(f"style           : {paths.style}")
    print(f"synopsis        : {paths.synopsis}")
    if use_digest:
        print(f"plot digest     : {digest_path}")
    else:
        print(f"visual segments : {paths.visual_segments}")
        print(f"subtitles txt   : {paths.subtitles_text}")
    if target_minutes:
        print(f"target minutes  : {target_minutes:.1f}")
    print(f"output prompt   : {output_path}")
    print(f"-> created empty: {scripts_path.name} (paste LLM script output here)")

    args = [
        "--style", str(paths.style),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(output_path),
    ]

    if use_digest:
        args.extend(["--plot-digest", str(digest_path)])
    else:
        args.extend([
            "--visual-segments", str(paths.visual_segments),
            "--subtitles-txt", str(paths.subtitles_text),
        ])

    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])

    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])

    return build_story_prompt_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
