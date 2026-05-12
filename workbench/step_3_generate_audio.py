"""Step 3 — generate voiceover MP3 + SRT from the manual script.

Reads:  workbench/work/<slug>/stage2/script.txt
Writes: workbench/work/<slug>/stage3/voiceover_<style>.{mp3,srt,manifest.json}

TTS sampling parameters resolve as: CLI override > [tools.generate_script_audio]
in current_movie.toml > styles/voice-assets/<style>/voice_clone.toml > built-in defaults.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, get_tool_value, load_config

from app.pipeline.stage_3_generate_audio import main as stage_3_main


_OVERRIDES = (
    "max_chars_per_request",
    "temperature",
    "top_p",
    "top_k",
    "repetition_penalty",
    "max_new_tokens",
)


def run() -> int:
    cfg = load_config(DEFAULT_CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.script.is_file() or not paths.script.read_text(encoding="utf-8").strip():
        return fail(f"script is empty or missing: {paths.script}")
    if not paths.style.is_file():
        return fail(f"style file not found: {paths.style}")

    banner(f"Stage 3 — generate audio for {cfg['common']['movie_title']}")
    print(f"script     : {paths.script}")
    print(f"style      : {paths.style}")
    print(f"output dir : {paths.stage3_dir}")

    args = [
        "--script", str(paths.script),
        "--style", str(paths.style),
        "--output-dir", str(paths.stage3_dir),
    ]
    for key in _OVERRIDES:
        value = get_tool_value(cfg, "generate_script_audio", key)
        if value is not None:
            args.extend([f"--{key.replace('_', '-')}", str(value)])
    return stage_3_main(args)


if __name__ == "__main__":
    raise SystemExit(run())
