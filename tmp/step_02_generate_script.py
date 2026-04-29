"""Step 2 — write the planner prompt for the LLM (single pass).

Flow:

  1. First run  : writes ``planner_prompt.txt``. Paste it into your LLM, paste
                  the reply into ``anchored_script.txt``.
  2. Second run : validates ``anchored_script.txt`` against the per-anchor
                  character budget and reports ok / warn / fail counts.

If your movie folder contains ``synopsis.md`` (plot/cast/cultural context),
it is automatically included in the prompt under `# External Context`.
This is optional — the planner can still work from raw SRT + visuals alone.

Files live under tmp/work/<movie_slug>/stage2/.
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
    MAX_ANCHOR_RANGE_DURATION_S,
    ScriptValidation,
    build_timeline_intervals,
    load_visual_segments,
    read_style_chars_per_second,
    validate_anchored_script,
)
from app.pipeline.stage1_parse_subtitles import parse_subtitles
from app.pipeline.stage2_generate_script import build_planner_prompt

CONFIG = DEFAULT_CONFIG


def seed_placeholders(paths) -> None:
    if not paths.anchored_script.exists():
        paths.anchored_script.write_text(PLACEHOLDER_ANCHORED, encoding="utf-8")


def report_validation(paths, chars_per_second: float) -> int:
    """Validate the user-pasted anchored script and print a per-chunk verdict.

    Performs both budget checks and structure checks (orphan narration,
    missing acts, anchor monotonicity, range provenance against real
    SRT/visual timestamps).

    On failure, also writes ``validation_feedback.txt`` next to the
    anchored script — a ready-to-paste message asking the LLM to fix only
    the offending anchors.

    Returns 0 if no failures (warns tolerated), 1 if any chunk OR any
    structural issue failed.
    """
    text = paths.anchored_script.read_text(encoding="utf-8")
    subtitles = parse_subtitles(paths.subtitle_srt)
    visual_segments = load_visual_segments(paths.visual_segments)
    timeline_intervals = build_timeline_intervals(
        subtitle_intervals=[(s.start, s.end) for s in subtitles],
        visual_segments=visual_segments,
    )
    result = validate_anchored_script(
        text,
        chars_per_second=chars_per_second,
        timeline_intervals=timeline_intervals,
    )

    ok = sum(1 for c in result.chunks if c.severity == "ok")
    warn = sum(1 for c in result.chunks if c.severity == "warn")
    fail_count = sum(1 for c in result.chunks if c.severity == "fail")

    print(f"Anchored chunks: {len(result.chunks)} (ok={ok} warn={warn} fail={fail_count})")
    if warn:
        print("\nBudget warnings (Stage 5 scene-extension will absorb):")
        for c in result.chunks:
            if c.severity == "warn":
                print(
                    f"  chunk {c.index}: {c.narration_chars} chars "
                    f"vs budget {c.budget_chars} ({c.overrun_ratio:.2f}× over)"
                )
    if fail_count:
        print("\nBudget failures (rewrite needed — narration is sacred, no auto-trim):")
        for c in result.failures():
            print(
                f"  chunk {c.index}: {c.narration_chars} chars "
                f"vs budget {c.budget_chars} ({c.overrun_ratio:.2f}× over)"
            )
            print(f"    anchor: {c.anchor.raw}")

    if result.issues:
        print(f"\nStructure issues: {len(result.issues)}")
        for issue in result.issues:
            print(f"  [{issue.severity}] {issue.code}: {issue.message}")

    if result.has_failures:
        feedback_path = write_validation_feedback(paths, result, chars_per_second)
        print(f"\nFix-request written to: {feedback_path}")
        print("Paste it into your LLM, paste the corrected anchors back into")
        print(f"  {paths.anchored_script}")
        print("then re-run this step.")
        return 1

    # Validation passed — clear any stale fix-request from a previous failed run
    # so the workspace doesn't show a phantom open issue.
    stale_feedback = paths.stage2_dir / "validation_feedback.txt"
    if stale_feedback.exists():
        stale_feedback.unlink()
    return 0


def write_validation_feedback(
    paths,
    result: ScriptValidation,
    chars_per_second: float,
) -> Path:
    """Write a ready-to-paste fix-request listing every failing anchor.

    The file goes to ``stage2/validation_feedback.txt`` and is structured
    so the planner LLM can see exactly which anchors broke which rule and
    regenerate only those — keeping the rest of the script untouched.
    """
    lines: list[str] = []
    lines.append(
        "The previous anchored script you produced has issues that violate "
        "the hard constraints from the original prompt. Please regenerate "
        "ONLY the affected anchors below, keeping every other anchor and all "
        "narration text unchanged. Re-output the COMPLETE updated script."
    )
    lines.append("")
    lines.append("ISSUES")
    lines.append("------")

    n = 0
    for chunk in result.failures():
        n += 1
        lines.append(
            f"{n}. [budget_overrun] chunk {chunk.index}: narration is "
            f"{chunk.narration_chars} chars vs budget {chunk.budget_chars} "
            f"({chunk.overrun_ratio:.2f}× over — cap is 1.10×)."
        )
        lines.append(f"   Anchor: {chunk.anchor.raw}")
        lines.append("   Fix: shrink the narration text under this anchor; do not widen the ranges.")
        lines.append("")

    for issue in result.fail_issues():
        n += 1
        lines.append(f"{n}. [{issue.code}] {issue.message}")
        lines.append("")

    lines.append("REMINDER OF CONSTRAINTS")
    lines.append("-----------------------")
    lines.append(f"- Each individual range must be ≤ {int(MAX_ANCHOR_RANGE_DURATION_S)} seconds.")
    lines.append(
        "- All timestamps must come from the timeline in the original prompt — "
        "do not invent times."
    )
    lines.append(
        f"- Per anchor: chars(narration) ≤ sum(range_seconds) × "
        f"{chars_per_second} × 1.10."
    )
    lines.append(
        "- Anchors must stay in chronological order across the script."
    )

    feedback_path = paths.stage2_dir / "validation_feedback.txt"
    feedback_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return feedback_path


def run() -> int:
    cfg = load_config(CONFIG)
    common = cfg["common"]
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if not paths.visual_segments.exists():
        return fail(
            f"Stage 0 output missing: {paths.visual_segments}\n"
            f"Run step_00_index_visuals.py first."
        )

    seed_placeholders(paths)

    # Phase 1: anchored script not yet filled → emit the planner prompt.
    if not is_filled(paths.anchored_script, PLACEHOLDER_ANCHORED):
        banner("Stage 2 — planner prompt")
        synopsis_path = paths.synopsis if paths.synopsis.exists() else None
        prompt = build_planner_prompt(
            style_path=paths.style,
            subtitle_srt_path=paths.subtitle_srt,
            visual_segments_path=paths.visual_segments,
            movie_title=common["movie_title"],
            genre=common["genre"],
            target_seconds=common["target_seconds"],
            synopsis_path=synopsis_path,
        )
        paths.planner_prompt.write_text(prompt, encoding="utf-8")
        print(f"Wrote: {paths.planner_prompt}")
        if synopsis_path is None:
            print(f"(No synopsis.md found in {paths.movie_dir} — proceeding without external context.)")
        else:
            print(f"Synopsis included from: {synopsis_path}")
        print(f"\nNext: paste the prompt into an LLM, then paste its reply into:")
        print(f"  {paths.anchored_script}")
        print(f"Then re-run this script to validate the result.")
        return 0

    # Phase 2: anchored script filled → validate it.
    banner("Stage 2 — validating anchored script")
    chars_per_second = read_style_chars_per_second(paths.style)
    print(f"Style: {paths.style.name}")
    print(f"chars_per_second = {chars_per_second}")
    print(f"Script: {paths.anchored_script}")
    rc = report_validation(paths, chars_per_second)
    if rc == 0:
        print("\nStage 2 OK. Move on to step_03_generate_audio.py.")
    else:
        print("\nStage 2 has failing chunks. Edit the anchored script and re-run.")
    return rc


if __name__ == "__main__":
    raise SystemExit(run())
