"""Step 4 — narration writing prompt or validation.

Reads:  tmp/work/<movie_slug>/stage3/rough_cut.json
        tmp/work/<movie_slug>/stage0/visual_segments.json
        tmp/work/<movie_slug>/stage1/subtitles.json
        styles/<style>.md
        movies/<...>/synopsis.md (optional)
Writes: tmp/work/<movie_slug>/stage4/narration_prompt.txt
        tmp/work/<movie_slug>/stage4/narration.json (placeholder)

First run emits the prompt. Paste it into Gemini 3 Pro / Qwen 3.6, paste
the JSON reply into `narration.json`, and re-run with `validate=True`.

This file is a skeleton — the underlying module is not implemented yet.
See plan.md Phase 4.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage4_write_narration import main as stage4_main

CONFIG = DEFAULT_CONFIG


def run(validate: bool = False) -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.rough_cut_manifest.exists():
        return fail(f"rough cut manifest not found: {paths.rough_cut_manifest}")
    if not paths.visual_segments.exists():
        return fail(f"visual segments not found: {paths.visual_segments}")
    if not paths.subtitles_json.exists():
        return fail(f"subtitles json not found: {paths.subtitles_json}")
    if not paths.style.exists():
        return fail(f"style file not found: {paths.style}")

    banner(f"Stage 4 — write narration for {cfg['common']['movie_title']}")
    print(f"rough cut       : {paths.rough_cut_manifest}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles json  : {paths.subtitles_json}")
    print(f"style           : {paths.style}")
    print(f"out dir         : {paths.stage4_dir}")
    print(f"mode            : {'validate' if validate else 'prompt'}")

    args = [
        "--rough-cut-manifest", str(paths.rough_cut_manifest),
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-json", str(paths.subtitles_json),
        "--style", str(paths.style),
        "--out-dir", str(paths.stage4_dir),
    ]
    if paths.synopsis.exists():
        args += ["--synopsis", str(paths.synopsis)]
    if validate:
        args.append("--validate")

    return stage4_main(args)


if __name__ == "__main__":
    raise SystemExit(run(validate=False))
