"""Step 2 — build the LLM prompts for the multi-pass script pipeline.

Pipeline:

    python workbench/step_2_build_prompt.py --outline   # writes outline_prompt.txt
    # paste outline_prompt.txt into LLM, save reply as scene_markers.json
    python workbench/step_2_build_prompt.py --digest    # writes digest_prompt.txt
                                                        # (or 3 sibling files if digest_mode = "chunked")
    # paste digest_prompt.txt into LLM, save reply as plot_digest.txt
    python workbench/step_2_build_prompt.py             # writes story_prompt.txt
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


def _run_outline(cfg, paths) -> int:
    rc = _common_inputs_present(paths)
    if rc is not None:
        return rc

    banner(f"Stage 2 — outline (Pass 0) for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles       : {paths.subtitles_text}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"output          : {paths.outline_prompt}")
    print(f"-> paste reply as: {paths.scene_markers.name}")

    args = [
        "--outline",
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.outline_prompt),
    ]
    return stage_2_main(args)


def _run_digest(cfg, paths) -> int:
    rc = _common_inputs_present(paths)
    if rc is not None:
        return rc

    digest_mode = cfg["common"].get("digest_mode", "single")
    if digest_mode not in ("single", "chunked"):
        return fail(f"Invalid digest_mode: {digest_mode!r} (expected 'single' or 'chunked')")

    if not paths.scene_markers.is_file():
        return fail(
            f"scene_markers.json not found: {paths.scene_markers}\n"
            "Run --outline first and paste the LLM reply into that file."
        )

    banner(f"Stage 2 — digest (Pass 1, {digest_mode}) for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles       : {paths.subtitles_text}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"scene markers   : {paths.scene_markers}")
    print(f"output          : {paths.digest_prompt}")

    args = [
        "--digest",
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--scene-markers", str(paths.scene_markers),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.digest_prompt),
    ]
    if paths.style.is_file():
        args.extend(["--style", str(paths.style)])
    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])
    target_minutes = _target_minutes(cfg)
    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])
    if digest_mode == "chunked":
        args.append("--chunked")
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

    mode = "DIGEST (multi-pass)" if use_digest else "TIMELINE (single-pass)"
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--outline", action="store_true", help="Build Pass 0 outline prompt.")
    mode.add_argument("--digest", action="store_true", help="Build Pass 1 digest prompt(s).")
    args = parser.parse_args(argv)

    cfg = load_config(DEFAULT_CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if args.outline:
        return _run_outline(cfg, paths)
    if args.digest:
        return _run_digest(cfg, paths)
    return _run_story(cfg, paths)


if __name__ == "__main__":
    raise SystemExit(run())
