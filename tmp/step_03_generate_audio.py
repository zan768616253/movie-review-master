"""Step 3 — TTS the anchored script into one voiceover mp3 + manifest.

Reads:  tmp/work/<movie_slug>/stage2/anchored_script.txt
Writes: tmp/work/<movie_slug>/stage3/voiceover_<tag>_voiceclone.{mp3,manifest.json}

Tag defaults to the style filename stem (e.g. "niu-shu") unless overridden
in [stage3].tag in the config.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (
    DEFAULT_CONFIG,
    PLACEHOLDER_ANCHORED,
    banner,
    build_paths,
    ensure_stage_dirs,
    fail,
    is_filled,
    load_config,
)

from app.pipeline.common.script_contract import (
    build_timeline_intervals,
    load_visual_segments,
    read_style_chars_per_second,
    validate_anchored_script,
)
from app.pipeline.stage1_parse_subtitles import parse_subtitles
from app.pipeline.stage3_generate_audio import main as stage3_main

CONFIG = DEFAULT_CONFIG


def gate_on_stage2_validation(paths) -> int:
    """Refuse to run if the anchored script doesn't pass Stage 2 validation.

    Stage 3 is the first step that consumes the anchored script for real
    work (TTS audio). Re-running the same validator the user saw in
    Stage 2 closes the loop: a script that was hand-edited after Stage 2
    last passed (or never validated at all) cannot leak into the audio
    pipeline.
    """
    text = paths.anchored_script.read_text(encoding="utf-8")
    subtitles = parse_subtitles(paths.subtitle_srt)
    visual_segments = load_visual_segments(paths.visual_segments)
    timeline_intervals = build_timeline_intervals(
        subtitle_intervals=[(s.start, s.end) for s in subtitles],
        visual_segments=visual_segments,
    )
    chars_per_second = read_style_chars_per_second(paths.style)
    result = validate_anchored_script(
        text,
        chars_per_second=chars_per_second,
        timeline_intervals=timeline_intervals,
    )
    if not result.has_failures:
        return 0

    fail_chunks = sum(1 for c in result.chunks if c.severity == "fail")
    fail_issues = sum(1 for i in result.issues if i.severity == "fail")
    return fail(
        f"anchored_script has {fail_chunks} failing chunk(s) and "
        f"{fail_issues} structural issue(s).\n"
        f"Run step_02_generate_script.py to see the details and to regenerate "
        f"the LLM fix-request file.\n"
        f"Stage 3 will not run on a script that fails Stage 2 validation."
    )


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not is_filled(paths.anchored_script, PLACEHOLDER_ANCHORED):
        return fail(
            f"Stage 2 anchored_script is missing or still contains the placeholder: {paths.anchored_script}\n"
            f"Run step_02_generate_script.py, paste the planner output, then re-run this step."
        )

    rc = gate_on_stage2_validation(paths)
    if rc != 0:
        return rc

    tag = cfg.get("stage3", {}).get("tag")

    banner(f"Stage 3 — generate audio for {cfg['common']['movie_title']}")
    print(f"script     : {paths.anchored_script}")
    print(f"style      : {paths.style}")
    print(f"output dir : {paths.stage3_dir}")
    print(f"tag        : {tag or '(default, derived from style filename)'}")

    argv = [
        "--script", str(paths.anchored_script),
        "--style", str(paths.style),
        "--output-dir", str(paths.stage3_dir),
    ]
    if tag:
        argv.extend(["--tag", tag])
    return stage3_main(argv)


if __name__ == "__main__":
    raise SystemExit(run())
