"""Step 0 — (optional) generate an SRT subtitle file for the movie.

Runs faster-whisper on the movie's video and writes a sibling ``.srt`` next
to it. Skips silently when a ``.srt`` or ``.ass`` is already present in the
movie folder — human-curated subtitles always win.

Reads:  movies/<title>/<video>
Writes: movies/<title>/<video_basename>.srt   (only if no .srt/.ass exists)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import banner, fail, resolve_run_context

from app.pipeline.stage_0_generate_subtitles import main as stage_0_main


def run() -> int:
    ctx = resolve_run_context(ensure_dirs=False)
    cfg, paths = ctx.cfg, ctx.paths

    if not paths.movie_dir.is_dir():
        return fail(f"movie folder not found: {paths.movie_dir}")

    banner(f"Stage 0 — generate subtitles for {cfg['common']['movie_title']}")
    print(f"movie folder : {paths.movie_dir}")

    return stage_0_main([str(paths.movie_dir)])


if __name__ == "__main__":
    raise SystemExit(run())
