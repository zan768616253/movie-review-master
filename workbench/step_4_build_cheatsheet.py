"""Step 4 — build the 剪映 editor cheatsheet (thumbnails + HTML).

Reads:  workbench/work/<slug>/stage3/voiceover_<style>.manifest.json
        workbench/work/<slug>/stage1/visual_segments.json
        movies/<slug>/<video_file>
Writes: workbench/work/<slug>/stage1/thumbnails/visual_NNN.jpg (cached)
        workbench/work/<slug>/stage4/editor_cheatsheet.html

The cheatsheet is what the operator opens next to 剪映: each narration
sentence is shown alongside thumbnail cards for every visual_segment the
LLM cited, so the editor can match a shot from 剪映's bin to a sentence
without scrubbing the 2-hour timeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import banner, fail, resolve_run_context

from app.pipeline.stage_4_build_cheatsheet import main as stage_4_main


def run() -> int:
    ctx = resolve_run_context()
    cfg, paths = ctx.cfg, ctx.paths

    if not paths.voiceover_manifest.is_file():
        return fail(f"voiceover manifest not found: {paths.voiceover_manifest}")
    if not paths.visual_segments.is_file():
        return fail(f"visual_segments.json not found: {paths.visual_segments}")
    if not paths.video.is_file():
        return fail(f"source video not found: {paths.video}")

    banner(f"Stage 4 — editor cheatsheet for {cfg['common']['movie_title']}")
    print(f"manifest       : {paths.voiceover_manifest}")
    print(f"visual segments: {paths.visual_segments}")
    print(f"video          : {paths.video}")
    print(f"thumbnails dir : {paths.thumbnails_dir}")
    print(f"output HTML    : {paths.cheatsheet_html}")

    args = [
        "--manifest", str(paths.voiceover_manifest),
        "--visual-segments", str(paths.visual_segments),
        "--video", str(paths.video),
        "--thumbnails-dir", str(paths.thumbnails_dir),
        "--out", str(paths.cheatsheet_html),
        "--title", str(cfg["common"].get("movie_title") or paths.video.stem),
    ]
    return stage_4_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
