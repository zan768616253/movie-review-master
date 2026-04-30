"""Stage 2: planner-writer prompt assembler (single pass).

Replaces the old writer + grounder two-pass design. One LLM call now picks
visual anchors AND writes narration that fits inside those anchors.
Narration character count is bounded by ``sum(range_seconds) * chars_per_second``
so audio always fits the visual budget. Stage 5 trims excess video shot-aware.

Manual flow stays the same shape:

    1. Run ``stage2-generate-script`` to print the planner prompt to stdout.
    2. Paste the prompt into your LLM (Gemini 2.5 Pro recommended).
    3. Paste the LLM reply into ``anchored_script.txt``.
    4. ``validate_anchored_script`` (in ``script_contract``) checks budgets.

See ``docs/OVERHAUL_PLAN.md`` §3, §4 for the architecture rationale.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.pipeline.common.script_contract import (
    MAX_ANCHOR_RANGE_DURATION_S,
    MAX_ANCHOR_TOTAL_DURATION_S,
    load_visual_segments,
    read_style_chars_per_second,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.stage1_parse_subtitles import parse_subtitles


# Sub-shots shorter than this are visual flickers, not real beats. Stage 0
# scene-detect occasionally produces tight clusters of boundaries on flash
# frames or quick whip-pans; collapsing those keeps the [shot:NNN] timeline
# free of unselectable 0.1s entries.
MIN_SHOT_DURATION_S = 0.5


PLANNER_ROLE = (
    "You are the planner-writer for a Chinese movie-review pipeline. You pick "
    "visual anchors from the source movie AND write narration in the target "
    "style — both in one pass. Your output is the final script; there is no "
    "second editor."
)
DEFAULT_GENRE = "general"
DEFAULT_TARGET_SECONDS = 540.0  # 9 min. Hint only; the planner is allowed to flex ±30%.


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def get_segment_characters(segment: dict[str, object]) -> list[str]:
    raw_characters = segment.get("characters")
    if not isinstance(raw_characters, list):
        return []
    return [character for character in raw_characters if isinstance(character, str)]


def infer_movie_title(subtitle_srt_path: Path, explicit_title: str | None) -> str:
    return explicit_title or subtitle_srt_path.stem


def split_segment_into_shots(
    segment: dict[str, object],
) -> list[tuple[float, float]]:
    """Split one Stage 0 visual segment into its constituent source shots.

    Stage 0 emits each segment with a `shot_boundaries_s` list — the cuts
    that fall strictly inside the segment's window. The segment's own
    `start` and `end` are themselves shot boundaries (they were snapped
    there by Stage 0). Combining the three gives the full set of cuts
    inside the segment, which we expand into back-to-back sub-shots.

    Empty `shot_boundaries_s` ⇒ the whole segment is one shot. A segment
    with two inner cuts ⇒ three sub-shots.

    Sub-shots shorter than `MIN_SHOT_DURATION_S` are dropped — those are
    flicker frames the planner cannot use as a meaningful range.
    """
    try:
        seg_start = timestamp_to_seconds(str(segment["start"]))
        seg_end = timestamp_to_seconds(str(segment["end"]))
    except (KeyError, ValueError):
        return []
    if seg_end <= seg_start:
        return []

    inner: list[float] = []
    for raw in segment.get("shot_boundaries_s") or ():  # type: ignore[union-attr]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if seg_start < value < seg_end:
            inner.append(value)
    inner.sort()

    cut_points = [seg_start, *inner, seg_end]
    shots: list[tuple[float, float]] = []
    for i in range(len(cut_points) - 1):
        start = cut_points[i]
        end = cut_points[i + 1]
        if end - start >= MIN_SHOT_DURATION_S:
            shots.append((start, end))
    return shots


def build_merged_timeline(subtitle_srt_path: Path, visual_segments_path: Path) -> str:
    """Interleave SRT dialogue and per-shot visual entries chronologically.

    The merged timeline is the planner's single plot ledger. Two entry kinds:

    - ``[srt:NNN]`` — one spoken-dialogue line. **Context only**, not a
      legitimate range source: SRT timestamps start at speech onset, not
      at shot cuts, so picking a range from SRT timestamps will almost
      always cross a shot boundary and the validator will reject it.
    - ``[shot:NNN]`` — one source-movie shot, with its duration. Anchor
      ranges MUST be picked from these. Multi-shot beats are expressed
      with a multi-range anchor where each range is one ``[shot:NNN]``.

    Each Stage 0 visual segment expands into 1+ ``[shot:NNN]`` entries
    via `split_segment_into_shots`. All sub-shots from one segment share
    the segment's `summary`, `characters`, and `ocr_text` because the
    segment described one event (e.g. "shot-reverse-shot dialogue"); the
    planner picks individual shot ranges for fine pacing control.

    Example lines::

        [shot:042] 00:23:00.000 --> 00:23:08.000 (8.0s) :: chars=Yuta | walks into bloody room
        [shot:043] 00:23:08.000 --> 00:23:14.000 (6.0s) :: chars=Villain | villain stands in corner
        [srt:128]  00:23:11.000 --> 00:23:13.500 :: Yuta: 你是谁
    """
    subtitles = parse_subtitles(subtitle_srt_path)
    segments = load_visual_segments(visual_segments_path)

    events: list[tuple[float, str]] = []

    for index, subtitle in enumerate(subtitles, 1):
        speaker_part = f"{subtitle.speaker}: " if subtitle.speaker else ""
        text = collapse_whitespace(subtitle.text)
        line = (
            f"[srt:{index:03d}] "
            f"{seconds_to_timestamp(subtitle.start)} --> "
            f"{seconds_to_timestamp(subtitle.end)} :: "
            f"{speaker_part}{text}"
        )
        events.append((subtitle.start, line))

    shot_index = 0
    for segment in segments:
        characters = "|".join(get_segment_characters(segment))
        chars_part = f"chars={characters} | " if characters else ""
        summary = collapse_whitespace(str(segment.get("summary") or ""))
        ocr_text = collapse_whitespace(str(segment.get("ocr_text") or ""))
        ocr_part = f" | ocr={ocr_text}" if ocr_text else ""

        for shot_start, shot_end in split_segment_into_shots(segment):
            shot_index += 1
            duration_s = shot_end - shot_start
            line = (
                f"[shot:{shot_index:03d}] "
                f"{seconds_to_timestamp(shot_start)} --> "
                f"{seconds_to_timestamp(shot_end)} "
                f"({duration_s:.1f}s) :: "
                f"{chars_part}{summary}{ocr_part}"
            )
            events.append((shot_start, line))

    events.sort(key=lambda event: event[0])
    return "\n".join(line for _, line in events)


def read_synopsis(synopsis_path: Path | None) -> str:
    """Read the optional synopsis file, returning the empty string when absent.

    Synopsis files are user-authored markdown describing plot, cast, and
    cultural context the planner needs but cannot infer from raw SRT/visuals.
    Recommended structure: one-line pitch, cast list with archetype labels,
    beat outline, cultural hooks. See HANDBOOK §6 (post-overhaul).
    """
    if synopsis_path is None or not synopsis_path.exists():
        return ""
    return synopsis_path.read_text(encoding="utf-8")


def build_planner_prompt(
    style_path: Path,
    subtitle_srt_path: Path,
    visual_segments_path: Path,
    movie_title: str,
    genre: str,
    target_seconds: float,
    synopsis_path: Path | None = None,
    chars_per_second: float | None = None,
) -> str:
    """Assemble the single-pass planner-writer prompt.

    The planner sees the full style rulebook (verbatim), an optional external
    synopsis, the merged SRT+visual chronological timeline, and the budget
    formula. It outputs the final anchored script in one shot.

    `chars_per_second` defaults to whatever the style file declares (read by
    `read_style_chars_per_second`); pass an override only for tests.
    """
    style_text = style_path.read_text(encoding="utf-8")
    if chars_per_second is None:
        chars_per_second = read_style_chars_per_second(style_path)
    merged_timeline = build_merged_timeline(subtitle_srt_path, visual_segments_path)
    synopsis_text = read_synopsis(synopsis_path).strip()

    synopsis_block = (
        synopsis_text
        if synopsis_text
        else "(No synopsis provided. Infer plot/character context from the timeline below.)"
    )

    target_min = max(60.0, target_seconds * 0.7)
    target_max = target_seconds * 1.3
    # Macro-level budget — LLMs pace much better when given the global total
    # alongside the per-anchor formula.
    total_budget_chars = int(round(target_seconds * chars_per_second))
    # Anchor-count guidance under the shot-aware contract: each anchor caps
    # at MAX_ANCHOR_TOTAL_DURATION_S (12s) and averages ~8-10s. Lower bound
    # is the math floor (every anchor at the cap); upper bound assumes
    # ~5-6s avg anchor (more rapid cuts for action-heavy material).
    anchor_count_low = max(20, int(target_seconds / float(MAX_ANCHOR_TOTAL_DURATION_S)))
    anchor_count_high = max(anchor_count_low + 10, int(target_seconds / 6))

    return f"""# Role
{PLANNER_ROLE}

# Style Rulebook (your voice authority)
The rulebook below is the single source of truth for tone, structure, beat
density, character naming, length window, and genre modulation. Follow every
rule exactly. The voice you produce must read as if written by a human in
this style — never sacrifice voice quality to fit the budget below.

<<<STYLE_RULEBOOK_START>>>
{style_text}
<<<STYLE_RULEBOOK_END>>>

# External Context
Use this to ground character names, plot stakes, cultural hooks, and any
narrative interpretation that cannot be derived from raw dialogue alone.

<<<SYNOPSIS_START>>>
{synopsis_block}
<<<SYNOPSIS_END>>>

# Movie
Title: {movie_title}
Genre: {genre}

# TTS Budget — HARD CONSTRAINT
chars_per_second = {chars_per_second}

For every [ANCHOR ...] block, the narration text underneath it must satisfy:

    chars(narration) ≤ sum(range_seconds) × {chars_per_second}

Where `sum(range_seconds)` is the total duration of all ranges in that
anchor. Example: an anchor with ranges totalling 12 seconds has a budget
of 12 × {chars_per_second} = {int(12 * chars_per_second)} characters of narration.

**Per-anchor duration cap (NEW — shot-aware contract):**
Each anchor's total duration MUST be ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s. This is a hard
validator constraint. Beyond {int(MAX_ANCHOR_TOTAL_DURATION_S)}s the within-anchor drift between
narration pace and source-edit pace exceeds ~3s and the audience hears
narration about a beat they aren't seeing yet. If a story moment needs
more than {int(MAX_ANCHOR_TOTAL_DURATION_S)}s of screen time, **split it into two consecutive
anchors**, each describing the next slice of the moment.

**Total-script budget (macro pacing target):**
With a target review of ~{target_seconds:.0f}s, your total narration across
ALL anchors must land in {int(total_budget_chars * 0.85)}-{total_budget_chars} characters
(target: {total_budget_chars}). Pace your four acts evenly — do not blow
{int(total_budget_chars * 0.5)} chars on the hook and arrive at the climax with
nothing left. Equally important: **do NOT undershoot.** Under-budget audio
makes the finished video feel thin and unfinished — falling below
{int(total_budget_chars * 0.85)} chars is a failure mode, not a safe choice.

To support this budget, your selected anchor ranges must cover enough total
seconds: aim for `sum(all_anchor_seconds) ≈ {target_seconds:.0f}`. With each
anchor capped at {int(MAX_ANCHOR_TOTAL_DURATION_S)}s, expect ~{anchor_count_low}–{anchor_count_high} anchors total.

A downstream validator rejects narrations that exceed any single anchor's
budget by more than 10% — Stage 5 then trims any small remaining video
slack shot-aware. The 10% over-budget cap is the only ceiling; the floor is
the macro range above.

# Source Material — chronological event ledger
Each line is one event in movie order. Two entry kinds:

- `[shot:NNN] HH:MM:SS.mmm --> HH:MM:SS.mmm (Xs) :: ...` — one **source
  shot** (the editor's atomic visual unit). The `(Xs)` annotation is the
  shot's duration. **Anchor ranges MUST come from these timestamps.**
- `[srt:NNN] HH:MM:SS.mmm --> HH:MM:SS.mmm :: speaker: line` — one
  spoken-dialogue line, included so you know what is said in each beat.
  **NEVER use `[srt:NNN]` timestamps as anchor ranges** — SRT lines start
  at speech onset, not at shot cuts, and ranges built from them will
  almost always cross a shot boundary and be rejected by the validator.

**How to choose shots:**

- **Prefer long shots (≥5s).** A long single-shot anchor is the most
  comfortable pacing for the audience. Use multi-range anchors only when
  the beat is genuinely shown across multiple shots in the source.
- **Avoid very short shots (<2s)** unless one specific frame is essential
  to the beat. They cause rapid cuts and make the review feel switchy.
- **Multi-range anchors** are how you cover a multi-shot beat (e.g. wide
  shot then reaction): `ranges="<shot42 ts>, <shot43 ts>, <shot44 ts>"`.
  Each range = exactly ONE `[shot:NNN]`. Never widen a range to cover two
  shots — that bridges a hard cut and the validator rejects it.
- **Sub-shot trims are allowed.** You may pick less than a full shot's
  duration (e.g. only the last 3s of an 8s shot), but you MUST stay
  inside that one shot — never let a range cross a `[shot:NNN]` boundary.

<<<TIMELINE_START>>>
{merged_timeline}
<<<TIMELINE_END>>>

# Authoring Algorithm
1. Read the style rulebook. Internalize the voice.
2. Read the synopsis (if any) and skim the timeline for the story shape.
3. Identify the narrative beats worth featuring. Each beat = one anchor.
   Be selective — the shot menu is not a quota; you may leave large
   portions of the source unselected.
4. Allocate screen-time roughly: climax beats deserve more anchors, setup
   beats fewer. Aim for ~{anchor_count_low}–{anchor_count_high} anchors total
   for a {target_seconds:.0f}s review.
5. For each beat, choose its anchor's ranges from the `[shot:NNN]` lines:
   - **Single-shot anchor (preferred default):** pick one shot, ideally
     ≥5s long. `ranges="<shot's start>-<shot's end>"`.
   - **Multi-shot anchor:** pick 2-3 shots that visualize the same beat
     (wide → reaction; or rapid action covered by 2-3 cuts). The ranges
     play back-to-back as one continuous beat under one narration line.
   - **Sub-shot trim:** if you only want the last few seconds of a long
     shot, write a range with timestamps inside that shot. Just stay
     inside ONE `[shot:NNN]` — never bridge two.
   - Total anchor duration (sum of range durations) ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s.
6. Write narration in the style voice. Size each beat's character count
   to fit `sum(range_seconds) × {chars_per_second}`. Self-check before finalizing.
7. Total review length: aim for roughly {target_seconds:.0f}s
   ({target_min:.0f}–{target_max:.0f}s acceptable).

# Output Schema

```
[TITLE] {movie_title}
[HOOK]
[ANCHOR ranges="HH:MM:SS.mmm-HH:MM:SS.mmm" characters="Name A|Name B"]
narration text bounded by sum_of_range_seconds × {chars_per_second}

[ACT 1 - SETUP]
[ANCHOR ranges="HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS"]
narration spanning two consecutive shots

[ACT 2 - ESCALATION]
[ANCHOR ...]
narration

[ACT 3 - CLIMAX]
[ANCHOR ...]
narration

[ACT 4 - RESOLUTION]
[ANCHOR ...]
narration

[CLOSING]
narration with NO [ANCHOR] — plays over a still keyframe
```

The exact ACT suffixes follow the style rulebook (some styles use
"REVEAL + CLIMAX" instead of "CLIMAX").

# Hard Constraints
- Anchors must be in chronological order across the script (early-movie
  before later-movie within each ACT, and ACTs in story order).
- Within one [ANCHOR], multi-range entries must NOT overlap. Order does
  not matter — the parser sorts ranges by start time so playback is
  always forward in source time.
- All range timestamps MUST come from `[shot:NNN]` lines in the timeline
  above. Never use `[srt:NNN]` timestamps; never invent times.
- **Each range must stay inside ONE `[shot:NNN]`.** A range that bridges
  two consecutive shots crosses a hard cut — the validator rejects it
  because the audience sees a jump cut mid-narration. To cover two shots
  in one beat, use a multi-range anchor with one range per shot.
- **Each individual range duration must be ≤ {int(MAX_ANCHOR_RANGE_DURATION_S)}s.** A range
  longer than this is almost always a typo in the end timestamp — for
  example, writing `00:29:53-01:00:00` when you meant `00:30:00`. Before
  emitting any anchor, double-check that each end timestamp's hour and
  minute digits are correct relative to its start.
- **Each anchor's total duration (sum of range durations) must be ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s.**
  If a beat needs more screen time, split into two consecutive anchors.
- Closing chunk has narration but no [ANCHOR].

# Final Budget Reminder — RE-STATED because this prompt is long
This prompt contains a large timeline above. Before you start writing,
confirm these numbers (originally stated under "TTS Budget — HARD CONSTRAINT"):

- **Total narration must land in {int(total_budget_chars * 0.85)}-{total_budget_chars} characters
  (target {total_budget_chars}).** Anything below {int(total_budget_chars * 0.85)} is a failure
  — the resulting audio will be too short to cover the movie's plot.
- **Per-act guideline (sums to {total_budget_chars}):**
  Act 1 ≈ {int(total_budget_chars * 0.20)} chars, Act 2 ≈ {int(total_budget_chars * 0.30)} chars,
  Act 3 ≈ {int(total_budget_chars * 0.30)} chars, Act 4 ≈ {int(total_budget_chars * 0.20)} chars.
- **Anchor coverage:** the sum of all your selected anchor seconds should
  be approximately {target_seconds:.0f}s, distributed across ~{anchor_count_low}-{anchor_count_high}
  anchors (avg ~{int(target_seconds / max(anchor_count_low, 1))}s per anchor, capped at {int(MAX_ANCHOR_TOTAL_DURATION_S)}s).
- **Per-anchor budget:** chars(narration) ≤ sum(range_seconds) × {chars_per_second}.
- **Per-anchor duration cap:** sum(range_seconds) ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s.
- **Per-range shot rule:** each range must stay inside ONE `[shot:NNN]`.

**Pre-output self-check (do this mentally before emitting the script):**
1. Will my total narration fall in {int(total_budget_chars * 0.85)}-{total_budget_chars} chars?
2. Does each act's char count match its share above?
3. Have I selected enough anchor seconds (~{target_seconds:.0f}s total) to support the budget?
4. Does every range I wrote come from a `[shot:NNN]` line, not `[srt:NNN]`?
5. Does every anchor's total duration stay ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s?

If any answer is "no", expand the script before outputting — do NOT emit
a short script "to be safe."

# Produce
Output ONLY the anchored script. No preamble, no code fences, no commentary.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stage2-generate-script",
        description="Print the Stage 2 planner-writer prompt to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("style", type=Path, help="Path to the style .md file")
    parser.add_argument("subtitle_srt", type=Path, help="Source subtitle file (.srt or .ass)")
    parser.add_argument("visual_segments", type=Path, help="visual_segments.json from Stage 0")
    parser.add_argument(
        "--movie-title",
        help="Movie title with optional language. Defaults to the subtitle filename stem.",
    )
    parser.add_argument(
        "--genre",
        default=DEFAULT_GENRE,
        help="Genre keyword for genre-modulated voice.",
    )
    parser.add_argument(
        "--synopsis",
        type=Path,
        default=None,
        help="Optional path to a synopsis markdown file (plot, cast, cultural context).",
    )
    parser.add_argument(
        "--target-seconds",
        type=float,
        default=DEFAULT_TARGET_SECONDS,
        help="Target review duration in seconds. Hint only; planner may flex ±30%%.",
    )
    return parser


def missing_input_paths(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists()]


def report_missing_paths(missing: list[Path]) -> None:
    for path_arg in missing:
        print(f"Input not found: {path_arg}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    required = [args.style, args.subtitle_srt, args.visual_segments]
    missing_paths = missing_input_paths(required)
    if missing_paths:
        report_missing_paths(missing_paths)
        return 1

    if args.synopsis is not None and not args.synopsis.exists():
        # Optional input — but if the user asked for one, fail loud rather
        # than silently producing a context-less prompt.
        print(f"Synopsis not found: {args.synopsis}", file=sys.stderr)
        return 1

    movie_title = infer_movie_title(args.subtitle_srt, args.movie_title)
    print(
        build_planner_prompt(
            style_path=args.style,
            subtitle_srt_path=args.subtitle_srt,
            visual_segments_path=args.visual_segments,
            movie_title=movie_title,
            genre=args.genre,
            target_seconds=args.target_seconds,
            synopsis_path=args.synopsis,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
