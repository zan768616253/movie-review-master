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
    MAX_ANCHOR_TOTAL_DURATION_S,
    REAL_TTS_CPS,
    AnchorValidation,
    ScriptValidation,
    StructureIssue,
    build_coverage_budget,
    build_review_budget,
    build_shot_boundary_set,
    build_timeline_intervals,
    inject_missing_anchor_ids,
    load_visual_segments,
    read_style_chars_per_second,
    validate_anchored_script,
)
from app.pipeline.stage1_parse_subtitles import parse_subtitles
from app.pipeline.stage2_generate_script import build_planner_prompt, build_shot_menu

CONFIG = DEFAULT_CONFIG


def seed_placeholders(paths) -> None:
    if not paths.anchored_script.exists():
        paths.anchored_script.write_text(PLACEHOLDER_ANCHORED, encoding="utf-8")


def ensure_anchor_ids(paths) -> None:
    """Inject missing ``id="chunk-NNN"`` attributes and persist the result.

    The planner prompt asks the LLM to emit `id="..."` on every anchor,
    but on a fresh script the LLM may forget. We patch in sequential ids
    on the in-place file so the validator and the feedback prompt below
    can refer to anchors by stable handles. Existing ids are preserved.
    """
    text = paths.anchored_script.read_text(encoding="utf-8")
    new_text, injected = inject_missing_anchor_ids(text)
    if injected:
        paths.anchored_script.write_text(new_text, encoding="utf-8")
        print(
            f"Injected {injected} missing chunk id(s) into "
            f"{paths.anchored_script.name}; future regenerations must keep them."
        )


def report_validation(paths, chars_per_second: float, target_seconds: float) -> int:
    """Validate the user-pasted anchored script and print a per-chunk verdict.

    Performs both budget checks and structure checks (orphan narration,
    missing acts, anchor monotonicity, range provenance against real
    SRT/visual timestamps).

    On failure, also writes ``validation_feedback.txt`` next to the
    anchored script — a self-contained prompt the user can paste verbatim
    into a fresh LLM chat to get a corrected script. The authoritative
    shot menu is embedded, so no separate ``visual_segments.json`` upload
    is normally required.

    Returns 0 if no failures (warns tolerated), 1 if any chunk OR any
    structural issue failed.
    """
    ensure_anchor_ids(paths)
    text = paths.anchored_script.read_text(encoding="utf-8")
    subtitles = parse_subtitles(paths.subtitle_srt)
    visual_segments = load_visual_segments(paths.visual_segments)
    timeline_intervals = build_timeline_intervals(
        subtitle_intervals=[(s.start, s.end) for s in subtitles],
        visual_segments=visual_segments,
    )
    shot_boundaries = build_shot_boundary_set(visual_segments)
    result = validate_anchored_script(
        text,
        chars_per_second=chars_per_second,
        timeline_intervals=timeline_intervals,
        shot_boundaries=shot_boundaries,
        target_seconds=target_seconds,
    )
    # Macro budget uses real TTS speech rate (REAL_TTS_CPS), not the
    # per-anchor writing cap. Total chars needed for `target_seconds` of
    # audio is governed by playback speed, not by what the planner is
    # allowed to write per anchor.
    review_budget = build_review_budget(target_seconds, REAL_TTS_CPS)
    coverage_budget = build_coverage_budget(target_seconds, chars_per_second)

    ok = sum(1 for c in result.chunks if c.severity == "ok")
    warn = sum(1 for c in result.chunks if c.severity == "warn")
    fail_count = sum(1 for c in result.chunks if c.severity == "fail")

    print(f"Anchored chunks: {len(result.chunks)} (ok={ok} warn={warn} fail={fail_count})")
    print(
        "Totals: "
        f"spoken={result.total_narration_chars} chars "
        f"(min {review_budget.min_chars}, target {review_budget.target_chars}), "
        f"anchor coverage={result.total_anchor_seconds:.1f}s "
        f"(min {coverage_budget.min_seconds:.1f}s, target {coverage_budget.target_seconds:.1f}s, "
        f"max {coverage_budget.max_seconds:.1f}s)"
    )
    if warn:
        print("\nBudget warnings (Stage 5 scene-extension will absorb):")
        for c in result.chunks:
            if c.severity == "warn":
                print(
                    f"  {c.chunk_id}: {c.narration_chars} chars "
                    f"vs budget {c.budget_chars} ({c.overrun_ratio:.2f}× over)"
                )
    if fail_count:
        print("\nBudget failures (rewrite needed — narration is sacred, no auto-trim):")
        for c in result.failures():
            print(
                f"  {c.chunk_id}: {c.narration_chars} chars "
                f"vs budget {c.budget_chars} ({c.overrun_ratio:.2f}× over)"
            )
            print(f"    anchor: {c.anchor.raw}")

    if result.issues:
        print(f"\nStructure issues: {len(result.issues)}")
        for issue in result.issues:
            chunk_part = f"{issue.chunk_id}: " if issue.chunk_id else ""
            print(f"  [{issue.severity}] {issue.code}: {chunk_part}{issue.message}")

    if result.has_failures:
        feedback_path = write_validation_feedback(paths, result, chars_per_second)
        print(f"\nFix-request written to: {feedback_path}")
        print("Paste it into a fresh LLM chat — the authoritative shot menu is already inlined,")
        print(f"then paste the corrected script back into:")
        print(f"  {paths.anchored_script}")
        print("then re-run this step.")
        return 1

    # Validation passed — clear any stale fix-request from a previous failed run
    # so the workspace doesn't show a phantom open issue.
    stale_feedback = paths.stage2_dir / "validation_feedback.txt"
    if stale_feedback.exists():
        stale_feedback.unlink()
    return 0


_FIX_HINTS_BY_CODE: dict[str, str] = {
    "range_too_long": (
        "Shorten or split the oversized range so every individual range "
        f"stays within the {int(MAX_ANCHOR_RANGE_DURATION_S)}s cap."
    ),
    "anchor_too_long": (
        "Split this beat into two or more consecutive anchors so each "
        f"new anchor stays within the {int(MAX_ANCHOR_TOTAL_DURATION_S)}s "
        "total-duration cap. Use a new sequential id (e.g. chunk-024 and "
        "chunk-024b) for the extra anchor."
    ),
    "range_shot_crossing": (
        "Rewrite the ranges so each range stays inside exactly one "
        "[shot:NNN]. Use a multi-range anchor with one range per shot, or "
        "split into two anchors."
    ),
    "non_monotonic": (
        "Reorder this anchor so its first range starts at or after the "
        "previous anchor's first range, OR move it under a new section "
        "marker (HOOK / ACT N / CLOSING)."
    ),
    "range_provenance": (
        "The range timestamps don't overlap any real shot or dialogue "
        "entry. Pick a [shot:NNN] from the inlined shot menu (derived "
        "from visual_segments.json) and copy its start/end verbatim."
    ),
    "orphan_narration": (
        "Move this narration text under a preceding [ANCHOR] line, or "
        "delete it. Stage 3 silently drops orphan narration."
    ),
    "script_too_short": (
        "Expand the script substantially until the total spoken narration "
        "reaches the Stage 2 minimum. Add missing plot beats and denser "
        "story coverage; do not pad with filler."
    ),
    "anchor_coverage_short": (
        "Add more anchors covering omitted story beats until the selected "
        "source footage reaches the Stage 2 minimum anchor coverage."
    ),
    "anchor_coverage_long": (
        "Reduce total selected source footage until anchor coverage returns "
        "to the Stage 2 window. Over-coverage makes Stage 6 discard planned "
        "visual beats and hurts sync."
    ),
    "bad_anchor": (
        "Re-emit this [ANCHOR] line with valid syntax: ranges= must be "
        "non-empty, chronological, and non-overlapping; all timestamps "
        "must be HH:MM:SS.mmm with end > start."
    ),
}


def _group_issues_by_chunk(result: ScriptValidation) -> tuple[
    dict[str, list[StructureIssue]], list[StructureIssue], dict[str, AnchorValidation]
]:
    """Group failures by chunk id so the LLM gets one block per anchor.

    Returns ``(issues_by_id, script_level_issues, chunk_lookup)``:
    - ``issues_by_id`` maps chunk_id → ordered list of failing issues
      attached to that anchor
    - ``script_level_issues`` are failures with no chunk_id (no_title,
      no_anchors, orphan_narration, bad_anchor on a malformed line)
    - ``chunk_lookup`` maps chunk_id → AnchorValidation so we can render
      each chunk's current anchor line and narration
    """
    issues_by_id: dict[str, list[StructureIssue]] = {}
    script_level: list[StructureIssue] = []
    chunk_lookup: dict[str, AnchorValidation] = {c.chunk_id: c for c in result.chunks}

    for chunk in result.failures():
        issues_by_id.setdefault(chunk.chunk_id, []).append(
            StructureIssue(
                severity="fail",
                code="budget_overrun",
                message=(
                    f"narration is {chunk.narration_chars} chars vs budget "
                    f"{chunk.budget_chars} ({chunk.overrun_ratio:.2f}× over — "
                    f"cap is 1.10×)"
                ),
                chunk_id=chunk.chunk_id,
            )
        )

    for issue in result.fail_issues():
        if issue.chunk_id and issue.chunk_id in chunk_lookup:
            issues_by_id.setdefault(issue.chunk_id, []).append(issue)
        else:
            script_level.append(issue)

    return issues_by_id, script_level, chunk_lookup


def _backfill_chunk_ids_after_injection(
    result: ScriptValidation, injected_script_text: str
) -> None:
    """After auto-injecting ids into the script text, propagate the new ids
    onto the existing ``AnchorValidation`` and ``StructureIssue`` objects.

    The validator may have been called on a pre-injection script — in
    which case every chunk got the ``anchor-#N`` fallback id. Re-walking
    the injected script positionally lets us upgrade those fallbacks to
    real ``chunk-NNN`` ids without re-running the entire validation.
    """
    from app.pipeline.common.script_contract import parse_anchor_marker

    new_anchor_lines = [
        line.strip()
        for line in injected_script_text.splitlines()
        if line.strip().startswith("[ANCHOR ")
    ]
    fallback_to_id: dict[str, str] = {}
    for index, (chunk, new_line) in enumerate(zip(result.chunks, new_anchor_lines), 1):
        try:
            new_anchor = parse_anchor_marker(new_line)
        except ValueError:
            continue
        if new_anchor is None or not new_anchor.id:
            continue
        if not chunk.anchor.id:
            fallback_to_id[f"anchor-#{index}"] = new_anchor.id
            chunk.anchor.id = new_anchor.id
            chunk.anchor.raw = new_line
    for issue in result.issues:
        if issue.chunk_id and issue.chunk_id in fallback_to_id:
            issue.chunk_id = fallback_to_id[issue.chunk_id]


def write_validation_feedback(
    paths,
    result: ScriptValidation,
    chars_per_second: float,
) -> Path:
    """Emit a self-contained fix-request prompt the LLM can act on alone.

    The prompt embeds the role, the current script, every issue grouped
    by chunk id, the style rulebook, optional synopsis, the authoritative
    shot menu, the rules of fixing, the constraint reminder, and the
    expected output shape.

    If the script on disk lacks anchor ids, this function auto-injects
    them, persists the file, and backfills the existing validation
    result so issues reference the new ``chunk-NNN`` handles.
    """
    raw_script = paths.anchored_script.read_text(encoding="utf-8")
    injected_script, injected_count = inject_missing_anchor_ids(raw_script)
    if injected_count:
        paths.anchored_script.write_text(injected_script, encoding="utf-8")
        _backfill_chunk_ids_after_injection(result, injected_script)
    current_script = injected_script
    issues_by_id, script_level, chunk_lookup = _group_issues_by_chunk(result)
    style_text = paths.style.read_text(encoding="utf-8")
    shot_menu = build_shot_menu(paths.visual_segments)
    synopsis_text = ""
    if paths.synopsis.exists():
        synopsis_text = paths.synopsis.read_text(encoding="utf-8").strip()

    lines: list[str] = []

    lines.append("# Role")
    lines.append(
        "You are revising an existing anchored script for the "
        "movie-review-master Stage 2 pipeline. Return a COMPLETE corrected "
        "script that passes the validator. Do not summarize, do not explain "
        "— output only the corrected script."
    )
    lines.append("")
    lines.append("# Primary Goal")
    lines.append(
        "Fix every listed issue while preserving the voice, plot coverage, "
        "act structure, and all unaffected anchors."
    )
    lines.append("")
    lines.append("# Inputs You Must Use")
    lines.append(
        "- The current script is pasted below under `# Current Script`. "
        "Every anchor has a stable `id=\"chunk-NNN\"` attribute — do not "
        "renumber existing ids."
    )
    lines.append(
        "- The authoritative shot menu is inlined below under "
        "`# Shot Menu`. It is derived from `visual_segments.json`, so you "
        "do NOT need any separate upload to fix this prompt."
    )
    lines.append(
        "- The style rulebook and synopsis are inlined below so you "
        "preserve how this script writes."
    )
    lines.append("")
    lines.append("# Non-Negotiable Fixing Rules")
    lines.append("- Keep every unaffected anchor line and narration text byte-identical.")
    lines.append("- Preserve every existing anchor id exactly.")
    lines.append(
        "- Only change anchors or script text required to resolve the listed "
        "validator failures. Do not do optional rewrites, polish passes, or "
        "style improvements outside the invalid parts."
    )
    lines.append(
        "- If a failing anchor must be SPLIT, keep the original id on the "
        "first replacement and add suffixed ids to extra anchors "
        "(e.g. `chunk-024` → `chunk-024` + `chunk-024b`)."
    )
    lines.append("- Every [ANCHOR] line must include an `id=\"...\"` attribute.")
    lines.append(
        "- Use only timestamps grounded in the inlined shot menu block "
        "below. Each range must be a copy of one shot's start/end (or a "
        "sub-window inside one shot)."
    )
    lines.append(
        "- Never widen a range just to fit narration. Rewrite narration "
        "or split into more anchors instead."
    )
    lines.append("- Return the COMPLETE updated script, not just the changed anchors.")
    lines.append("")

    lines.append("# Issues to Fix")
    if not issues_by_id and not script_level:
        lines.append("(no issues — this prompt should not have been generated)")
    if issues_by_id:
        lines.append(
            f"{len(issues_by_id)} anchor(s) need rework. Each block below "
            "shows the anchor's current line, current narration, the failing "
            "checks, and the prescribed fix per check."
        )
        lines.append("")
        for n, (chunk_id, chunk_issues) in enumerate(issues_by_id.items(), 1):
            chunk = chunk_lookup.get(chunk_id)
            lines.append(f"{n}. {chunk_id}")
            if chunk is not None:
                lines.append(f"   Anchor line: {chunk.anchor.raw}")
                # Pull the narration verbatim from the script body so the
                # LLM sees what it currently said and can rewrite it.
                narration = _extract_narration_for_chunk(current_script, chunk)
                if narration:
                    lines.append(f"   Current narration: {narration}")
            for issue in chunk_issues:
                lines.append(f"   - [{issue.code}] {issue.message}")
                hint = _FIX_HINTS_BY_CODE.get(issue.code)
                if hint:
                    lines.append(f"     Required fix: {hint}")
            lines.append("")
    if script_level:
        lines.append("Script-level issues (not tied to a single chunk):")
        for issue in script_level:
            lines.append(f"   - [{issue.code}] {issue.message}")
            hint = _FIX_HINTS_BY_CODE.get(issue.code)
            if hint:
                lines.append(f"     Required fix: {hint}")
        lines.append("")

    lines.append("# Style Rulebook (preserve voice, structure, naming, density)")
    lines.append("<<<STYLE_RULEBOOK_START>>>")
    lines.append(style_text)
    lines.append("<<<STYLE_RULEBOOK_END>>>")
    lines.append("")

    if synopsis_text:
        lines.append("# Synopsis (plot, cast, cultural context)")
        lines.append("<<<SYNOPSIS_START>>>")
        lines.append(synopsis_text)
        lines.append("<<<SYNOPSIS_END>>>")
        lines.append("")

    lines.append("# Shot Menu (authoritative legal range source)")
    lines.append("<<<SHOT_MENU_START>>>")
    lines.append(shot_menu)
    lines.append("<<<SHOT_MENU_END>>>")
    lines.append("")

    lines.append("# Current Script (to be revised)")
    lines.append("<<<CURRENT_SCRIPT_START>>>")
    lines.append(current_script.rstrip("\n"))
    lines.append("<<<CURRENT_SCRIPT_END>>>")
    lines.append("")

    lines.append("# Reminder of Constraints (the validator will reject any violation)")
    lines.append(
        f"- Each individual range must be ≤ {int(MAX_ANCHOR_RANGE_DURATION_S)} seconds."
    )
    lines.append(
        f"- Each anchor's total duration (sum of range durations) must be "
        f"≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)} seconds. If a beat needs more "
        f"screen time, split it into two consecutive anchors."
    )
    lines.append(
        "- Each range must stay inside ONE shot from the inlined shot menu "
        "block below. A range that crosses a shot boundary is rejected as a "
        "hard cut mid-narration."
    )
    lines.append(
        "- All range timestamps must come from a shot's start/end in the "
        "inlined shot menu (derived from `visual_segments.json`) — never "
        "from dialogue timestamps, never invented."
    )
    lines.append(
        f"- Per anchor: chars(narration) ≤ sum(range_seconds) × "
        f"{chars_per_second} × 1.10 (the validator allows 10% slack; beyond "
        f"that the audio runs past the visuals)."
    )
    lines.append(
        "- Anchors must stay in chronological order within each section "
        "([HOOK], [ACT N], [CLOSING]); cross-section jumps are allowed."
    )
    lines.append("- Every [ANCHOR] line must declare a unique `id=\"chunk-NNN\"`.")
    lines.append("")

    lines.append("# Expected Result")
    lines.append(
        "Return ONLY the complete corrected anchored script in plain text. "
        "No explanations, no bullet lists, no markdown fences, no JSON. "
        "Every anchor — fixed or untouched — appears in the output, in the "
        "same act structure as the current script."
    )

    feedback_path = paths.stage2_dir / "validation_feedback.txt"
    feedback_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return feedback_path


def _extract_narration_for_chunk(script_text: str, chunk: AnchorValidation) -> str:
    """Pull the narration block that lives under the chunk's anchor line.

    Used by the feedback writer to embed the anchor's current text so the
    LLM can compare current → required directly. Best-effort: returns
    empty string when the anchor's `raw` line can't be found verbatim
    (for example, after manual edits that re-formatted whitespace).
    """
    if not chunk.anchor.raw:
        return ""
    lines = script_text.splitlines()
    try:
        idx = next(i for i, line in enumerate(lines) if line.strip() == chunk.anchor.raw)
    except StopIteration:
        return ""
    collected: list[str] = []
    for line in lines[idx + 1 :]:
        stripped = line.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            break
        collected.append(stripped)
    return " ".join(collected)


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
    print(f"target_seconds = {common['target_seconds']}")
    print(f"Script: {paths.anchored_script}")
    rc = report_validation(paths, chars_per_second, common["target_seconds"])
    if rc == 0:
        print("\nStage 2 OK. Move on to step_03_generate_audio.py.")
    else:
        print("\nStage 2 has failing chunks. Edit the anchored script and re-run.")
    return rc


if __name__ == "__main__":
    raise SystemExit(run())
