"""Step 1 — parse the .srt/.ass subtitle file into a normalized text file.

Reads:  <movie>.srt (or .ass)
Writes: tmp/work/<movie_slug>/stage1/subtitles.txt

Note: stage1's CLI main() doesn't take an argv parameter, so this step
calls parse_subtitles() directly and writes the output itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.common.script_contract import seconds_to_timestamp
from app.pipeline.stage1_parse_subtitles import parse_subtitles

CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.subtitle_srt.exists():
        return fail(f"subtitle file not found: {paths.subtitle_srt}")

    banner(f"Stage 1 — parse subtitles for {cfg['common']['movie_title']}")
    print(f"input  : {paths.subtitle_srt}")
    print(f"output : {paths.subtitles_text}")

    subtitles = parse_subtitles(paths.subtitle_srt)
    lines = []
    for s in subtitles:
        start_str = seconds_to_timestamp(s.start)
        end_str = seconds_to_timestamp(s.end)
        prefix = f"[{start_str} -> {end_str}]"
        text = s.text.replace("\n", " / ")
        if s.speaker:
            lines.append(f"{prefix} {s.speaker}: {text}")
        else:
            lines.append(f"{prefix} {text}")
    paths.subtitles_text.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {len(subtitles)} lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
