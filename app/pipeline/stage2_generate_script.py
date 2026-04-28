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
    load_visual_segments,
    read_style_chars_per_second,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.stage1_parse_subtitles import parse_subtitles


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


def build_merged_timeline(subtitle_srt_path: Path, visual_segments_path: Path) -> str:
    """Interleave subtitle dialogue and visual-segment action by timestamp.

    The merged timeline is the planner's single plot ledger: every event in
    chronological order, with both spoken dialogue (`[srt:NNN]`) and
    silent / visual-only beats (`[visual:NNN]`). The planner picks anchor
    ranges by selecting from these entries.

    Example merged line::

        [srt:042] 00:23:11.000 --> 00:23:13.500 :: 乙骨憂太: 里香!

    Example visual line::

        [visual:128] 00:23:14.000 --> 00:23:18.000 :: chars=Rika | summary=ghost form appears | ocr=
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

    for index, segment in enumerate(segments, 1):
        try:
            start_seconds = timestamp_to_seconds(str(segment["start"]))
        except (KeyError, ValueError):
            continue

        characters = "|".join(get_segment_characters(segment))
        chars_part = f"chars={characters} | " if characters else ""
        summary = collapse_whitespace(str(segment.get("summary") or ""))
        ocr_text = collapse_whitespace(str(segment.get("ocr_text") or ""))
        ocr_part = f" | ocr={ocr_text}" if ocr_text else ""
        seg_id = str(segment.get("id") or f"visual:{index:03d}")
        line = (
            f"[{seg_id}] "
            f"{segment['start']} --> {segment['end']} :: "
            f"{chars_part}{summary}{ocr_part}"
        )
        events.append((start_seconds, line))

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
    # Anchor-count guidance scales with target length (~12s avg per anchor),
    # rather than the old hard-coded 30–50.
    anchor_count_low = max(8, int(target_seconds / 18))
    anchor_count_high = max(anchor_count_low + 4, int(target_seconds / 9))

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

**Total-script budget (macro pacing target):**
With a target review of ~{target_seconds:.0f}s, your total narration across
ALL anchors should be roughly {total_budget_chars} characters. Use this to
pace your four acts evenly — do not blow {int(total_budget_chars * 0.5)} chars
on the hook and arrive at the climax with nothing left.

A downstream validator rejects narrations that exceed budget by more than
10%. Narrations that are *under* budget are fine — Stage 5 trims the excess
video shot-aware. Always plan slightly under budget when in doubt.

# Source Material — chronological event ledger
Each line is one event in movie order. `[srt:NNN]` lines are spoken
dialogue; `[visual:NNN]` lines are silent or visual-only beats with
character presence and a one-phrase action summary. Anchor ranges in your
output must come from these timestamps — do not invent times.

**Tip on choosing srt vs visual:** Prefer `[visual:NNN]` ranges for action,
reaction shots, and B-roll-style coverage — those are guaranteed to be
visually meaningful and aligned to actual shot boundaries. Reach for
`[srt:NNN]` ranges only when you specifically want the audience to see the
character speaking the line you're discussing (e.g. a famous quote). Mixing
the two inside one multi-range anchor often produces awkward cuts.

<<<TIMELINE_START>>>
{merged_timeline}
<<<TIMELINE_END>>>

# Authoring Algorithm
1. Read the style rulebook. Internalize the voice.
2. Read the synopsis (if any) and skim the timeline for the story shape.
3. Identify the moments worth featuring — be selective. The visual menu is
   not a quota; you may leave large portions of the source unselected.
4. Allocate screen-time roughly: climax beats deserve more seconds, setup
   beats fewer. Aim for ~{anchor_count_low}–{anchor_count_high} anchors total
   for a {target_seconds:.0f}s review (more for longer reviews, fewer for shorter).
5. For each beat, choose the [ANCHOR] ranges:
   - Prefer SHORT, focused single-shot ranges (~2–8 seconds each).
   - When a beat needs more screen time than one shot affords, use a
     **multi-range anchor** listing the consecutive shots you want, e.g.
     `ranges="00:23:10-00:23:14, 00:23:18-00:23:24"`.
   - DO NOT use one wide range like `ranges="00:23:10-00:23:30"` to cover
     multiple shots — that spans cuts and looks broken to the audience.
6. Write narration in the style voice. Size each beat's character count
   to fit the budget. Self-check before finalizing.
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
- All timestamps must come from the timeline above.
- Closing chunk has narration but no [ANCHOR].

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
