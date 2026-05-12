"""Step 1 — prepare inputs for script generation.

Indexes the movie into visual segments and parses the subtitle file into
a normalized text + JSON pair. Both outputs feed Step 2's prompt builder.

Reads:  movies/<title>/<movie>.{mkv,mp4}, movies/<title>/<movie>.{srt,ass}
Writes: workbench/work/<slug>/stage0/visual_segments.json
        workbench/work/<slug>/stage0/subtitles.txt
        workbench/work/<slug>/stage0/subtitles.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.common.script_contract import seconds_to_timestamp
from app.pipeline.stage_1_index_visuals import main as stage_1_index_visuals_main
from app.pipeline.stage_1_parse_subtitles import parse_subtitles


def _run_index_visuals(paths) -> int:
    if not paths.video.exists():
        return fail(f"video not found: {paths.video}")
    if not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")
    if not paths.characters_dir.is_dir() or not any(paths.characters_dir.iterdir()):
        return fail(f"face gallery directory missing or empty: {paths.characters_dir}")

    banner("Stage 1a — index visuals")
    print(f"video        : {paths.video}")
    print(f"synopsis     : {paths.synopsis}")
    print(f"face gallery : {paths.characters_dir}")
    print(f"output       : {paths.visual_segments}")

    return stage_1_index_visuals_main([
        "--video", str(paths.video),
        "--output", str(paths.visual_segments),
        "--tmp-dir", str(paths.stage0_dir / "indexing"),
        "--synopsis", str(paths.synopsis),
        "--characters-dir", str(paths.characters_dir),
    ])


def _run_parse_subtitles(paths) -> int:
    if not paths.subtitle_srt.exists():
        return fail(f"subtitle file not found: {paths.subtitle_srt}")

    banner("Stage 1b — parse subtitles")
    print(f"input  : {paths.subtitle_srt}")
    print(f"output : {paths.subtitles_text}")

    subtitles = parse_subtitles(paths.subtitle_srt)
    lines = []
    for s in subtitles:
        prefix = f"[{seconds_to_timestamp(s.start)} -> {seconds_to_timestamp(s.end)}]"
        text = s.text.replace("\n", " / ")
        lines.append(f"{prefix} {s.speaker}: {text}" if s.speaker else f"{prefix} {text}")
    paths.subtitles_text.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {len(subtitles)} lines.")
    return 0


def run() -> int:
    cfg = load_config(DEFAULT_CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    rc = _run_index_visuals(paths)
    if rc:
        return rc
    return _run_parse_subtitles(paths)


if __name__ == "__main__":
    raise SystemExit(run())
