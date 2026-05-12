"""Step 2 — build the LLM prompt for script writing.

Default behaviour: build the story prompt (single-pass timeline mode, or
two-pass digest mode if `plot_digest.txt` already exists in the stage1 dir).

With ``--digest``: build the Pass 1 *digest* prompt instead. Workflow:

    python workbench/step_2_build_prompt.py --digest      # writes digest_prompt.txt
    # paste digest_prompt.txt into LLM, save reply as plot_digest.txt
    python workbench/step_2_build_prompt.py               # writes story_prompt.txt (digest mode)
    # paste story_prompt.txt into LLM, save reply as script.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage_2_build_prompt import main as stage_2_main


def _target_minutes(cfg: dict) -> float | None:
    seconds = cfg["common"].get("target_seconds")
    return seconds / 60.0 if seconds else None


def _common_inputs_present(paths) -> int | None:
    if not paths.visual_segments.is_file():
        return fail(f"visual segments not found: {paths.visual_segments}")
    if not paths.subtitles_text.is_file():
        return fail(f"subtitles not found: {paths.subtitles_text}")
    if not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")
    return None


def _run_digest(cfg, paths) -> int:
    rc = _common_inputs_present(paths)
    if rc is not None:
        return rc

    banner(f"Stage 2 — digest prompt for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles       : {paths.subtitles_text}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"output          : {paths.digest_prompt}")

    args = [
        "--digest",
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.digest_prompt),
    ]
    target_minutes = _target_minutes(cfg)
    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])
    return stage_2_main(args)


def _run_story(cfg, paths) -> int:
    if not paths.style.is_file():
        return fail(f"style file not found: {paths.style}")

    use_digest = paths.plot_digest.is_file()
    if not use_digest:
        rc = _common_inputs_present(paths)
        if rc is not None:
            return rc
    elif not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")

    paths.script.touch(exist_ok=True)

    mode = "DIGEST (two-pass)" if use_digest else "TIMELINE (single-pass)"
    banner(f"Stage 2 — story prompt for {cfg['common']['movie_title']} [{mode}]")
    print(f"style           : {paths.style}")
    print(f"synopsis        : {paths.synopsis}")
    if use_digest:
        print(f"plot digest     : {paths.plot_digest}")
    else:
        print(f"visual segments : {paths.visual_segments}")
        print(f"subtitles       : {paths.subtitles_text}")
    print(f"output prompt   : {paths.story_prompt}")
    print(f"-> ready to fill: {paths.script.name} (paste LLM script output here)")

    args = [
        "--style", str(paths.style),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.story_prompt),
    ]
    if use_digest:
        args.extend(["--plot-digest", str(paths.plot_digest)])
    else:
        args.extend([
            "--visual-segments", str(paths.visual_segments),
            "--subtitles-txt", str(paths.subtitles_text),
        ])

    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])
    target_minutes = _target_minutes(cfg)
    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])
    return stage_2_main(args)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--digest", action="store_true",
                        help="Build the Pass 1 digest prompt instead of the story prompt.")
    args = parser.parse_args(argv)

    cfg = load_config(DEFAULT_CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    return _run_digest(cfg, paths) if args.digest else _run_story(cfg, paths)


if __name__ == "__main__":
    raise SystemExit(run())
