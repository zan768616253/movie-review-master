"""Stage 2: Two-pass script authoring prompt assembler.

This stage stays manual for now, but the prompt contract is split into
two explicit passes:

1. Writer pass (`--mode writer`): produce narration beats with no timing.
2. Grounding pass (`--mode grounder`): consume the beat draft, full SRT,
    and `visual_segments.json`, then emit the final grounded script using
    `[SCENE start=... end=... source=...]` markers.

The goal is to keep Stage 2's human/LLM handoff reproducible while Stage 4
and Stage 5 operate on a precise grounding contract.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.pipeline.common.script_contract import (
    load_visual_segments,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.stage1_parse_subtitles import parse_subtitles


SCRIPT_WRITER_ROLE = (
    "You are a Chinese movie-review scriptwriter. You strictly follow the style "
    "rulebook provided below. You write in Simplified Chinese and focus only on "
    "storytelling, tone, and pacing. Do not assign timestamps in this pass."
)
GROUNDING_EDITOR_ROLE = (
    "You are the alignment editor for a movie-review pipeline. You must anchor "
    "each narration beat to either the SRT or the visual segment index, use the "
    "reference blocks to choose the best timestamp window, and mark uncertain beats "
    "as ungrounded instead of inventing times."
)
DEFAULT_GENRE = "general"


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def get_segment_characters(segment: dict[str, object]) -> list[str]:
    raw_characters = segment.get("characters")
    if not isinstance(raw_characters, list):
        return []
    return [character for character in raw_characters if isinstance(character, str)]


def infer_movie_title(subtitle_srt_path: Path, explicit_title: str | None) -> str:
    return explicit_title or subtitle_srt_path.stem


def build_srt_reference(subtitle_srt_path: Path) -> str:
    subtitles = parse_subtitles(subtitle_srt_path)
    lines = []
    for index, subtitle in enumerate(subtitles, 1):
        lines.append(
            f"[srt:{index:03d}] {seconds_to_timestamp(subtitle.start)} --> "
            f"{seconds_to_timestamp(subtitle.end)} :: {collapse_whitespace(subtitle.text)}"
        )
    return "\n".join(lines)


def build_visual_reference(visual_segments_path: Path) -> str:
    segments = load_visual_segments(visual_segments_path)
    lines = []
    for index, segment in enumerate(segments, 1):
        segment_id = str(segment.get("id") or f"visual:{index:03d}")
        characters = "|".join(get_segment_characters(segment)) or "-"
        summary = collapse_whitespace(str(segment.get("summary") or ""))
        ocr_text = collapse_whitespace(str(segment.get("ocr_text") or ""))
        suffix = f" | ocr={ocr_text}" if ocr_text else ""
        lines.append(
            f"[{segment_id}] {segment['start']} --> {segment['end']} "
            f"| chars={characters} | summary={summary}{suffix}"
        )
    return "\n".join(lines)


def build_merged_timeline(subtitle_srt_path: Path, visual_segments_path: Path) -> str:
    """Interleave subtitle dialogue and visual-segment action by timestamp.

    The merged timeline is the writer pass's single plot source: a chronological
    ledger that exposes both spoken dialogue and silent / visual-only beats so
    the writer can anchor narration to either anchor type.
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


def build_writer_prompt(
    style_path: Path,
    subtitle_srt_path: Path,
    visual_segments_path: Path,
    movie_title: str,
    genre: str,
) -> str:
    style_text = style_path.read_text(encoding="utf-8")
    merged_timeline = build_merged_timeline(subtitle_srt_path, visual_segments_path)

    return f"""# Role
{SCRIPT_WRITER_ROLE}

# Style Rulebook
The rulebook below is the single source of truth for tone, structure, beat
density, character naming, length window (target duration AND character-count
window), and genre modulation. Follow every rule exactly.

<<<STYLE_RULEBOOK_START>>>
{style_text}
<<<STYLE_RULEBOOK_END>>>

# Movie
Title: {movie_title}
Genre: {genre}

# Plot Source — chronological timeline merging dialogue (SRT) and on-screen action (visual segments)
Each line is one event in movie order. `[srt:NNN]` lines are spoken dialogue;
`[visual:NNN]` lines are silent or visual-only beats with character presence
and a one-phrase action summary. Use both: dialogue lines for plot and emotional
beats, visual lines for action beats, transitions, and re-engagement moments
that have no dialogue. Timestamps are reference context only — do NOT emit them
in your output.

<<<TIMELINE_START>>>
{merged_timeline}
<<<TIMELINE_END>>>

# Output requirements

1. Length target: follow the Style Rulebook's "Target Duration" and
   "Character-count Window" frontmatter exactly.
2. Keep the structural markers prescribed by the rulebook:
   [TITLE], [HOOK], [ACT 1 - SETUP], [ACT 2 - ESCALATION],
   [ACT 3 - CLIMAX], [ACT 4 - RESOLUTION], [CLOSING].
   The exact suffix after "ACT N -" may follow the rulebook (e.g. some styles
   use "REVEAL + CLIMAX" instead of "CLIMAX").
3. Under each section, break the narration into short beats using explicit
   markers: [BEAT 1], [BEAT 2], [BEAT 3], ... numbered continuously across
   the whole script.
4. Aim for 30-60 beats total. Each beat is one breathable spoken sentence or
   a short paragraph (~30-90 Chinese characters).
5. Do not output any [SCENE] or [BROLL] markers in this pass.
6. Do not guess timestamps. Ignore clip timing entirely.
7. The [CLOSING] section still contains narration beats, but no visual marker
   of any kind.

# Produce
Output only the beat draft itself. No preamble. No code fences.
"""


def build_grounding_prompt(
    beats_path: Path,
    subtitle_srt_path: Path,
    visual_segments_path: Path,
    movie_title: str,
) -> str:
    beats_text = beats_path.read_text(encoding="utf-8")
    srt_reference = build_srt_reference(subtitle_srt_path)
    visual_reference = build_visual_reference(visual_segments_path)

    return f"""# Role
{GROUNDING_EDITOR_ROLE}

# Movie
Title: {movie_title}

# Narration Beat Draft
The beat draft below is already written in the target voice. Preserve the wording unless a tiny edit is needed for clarity.

<<<BEATS_START>>>
{beats_text}
<<<BEATS_END>>>

# Full SRT Reference
Use SRT citations whenever a beat references spoken dialogue, paraphrased dialogue, or a moment anchored by subtitles.

<<<SRT_REFERENCE_START>>>
{srt_reference}
<<<SRT_REFERENCE_END>>>

# Visual Segment Reference
Use this only for non-dialogue beats: action, reactions, transitions, and establishing shots.

<<<VISUAL_REFERENCE_START>>>
{visual_reference}
<<<VISUAL_REFERENCE_END>>>

# Grounding algorithm

1. Classify each beat as DIALOGUE or ACTION.
2. If DIALOGUE: search the SRT reference first. Choose the best matching subtitle timestamp window.
3. If ACTION: search the visual segment reference. Prefer character overlap, then semantic match.
4. If the best candidate is weak, emit the beat as ungrounded instead of hallucinating a timestamp.
5. Preserve the section structure and narration text from the beat draft.

# Output contract

1. Replace every [BEAT N] marker with a grounded [SCENE ...] marker immediately above the beat text.
2. Use this exact attribute form for grounded beats:
    [SCENE start=HH:MM:SS.mmm end=HH:MM:SS.mmm source=srt|visual]
3. When a beat is ungrounded, use:
    [SCENE source=ungrounded]
4. If character identity is clear and useful for fallback B-roll selection, add:
   characters="Name A|Name B"
5. Keep [TITLE], [HOOK], [ACT ...], and [CLOSING].
6. Do not output [BEAT] markers in the final result.
7. Do not output code fences or explanations.

# Produce
Output only the final grounded script.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stage2-generate-script",
        description="Print the Stage 2 writer or grounding prompt to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    writer_parser = subparsers.add_parser(
        "writer",
        help="Build the writer-pass prompt.",
    )
    writer_parser.add_argument("style", type=Path, help="Path to the style .md file")
    writer_parser.add_argument("subtitle_srt", type=Path, help="Source subtitle file (.srt or .ass)")
    writer_parser.add_argument("visual_segments", type=Path, help="visual_segments.json from Stage 0")
    writer_parser.add_argument(
        "--movie-title",
        help="Movie title with optional language. Defaults to the subtitle filename stem.",
    )
    writer_parser.add_argument(
        "--genre",
        default=DEFAULT_GENRE,
        help="Genre keyword for the writer pass.",
    )

    grounder_parser = subparsers.add_parser(
        "grounder",
        help="Build the grounding-pass prompt.",
    )
    grounder_parser.add_argument("beats", type=Path, help="Beat draft produced by the writer pass")
    grounder_parser.add_argument("subtitle_srt", type=Path, help="Source subtitle file (.srt or .ass)")
    grounder_parser.add_argument("visual_segments", type=Path, help="visual_segments.json from Stage 0")
    grounder_parser.add_argument(
        "--movie-title",
        help="Movie title with optional language. Defaults to the subtitle filename stem.",
    )
    return parser


def missing_input_paths(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists()]


def report_missing_paths(missing: list[Path]) -> None:
    for path_arg in missing:
        print(f"Input not found: {path_arg}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "writer":
        missing_paths = missing_input_paths(
            [args.style, args.subtitle_srt, args.visual_segments]
        )
        if missing_paths:
            report_missing_paths(missing_paths)
            return 1
        movie_title = infer_movie_title(args.subtitle_srt, args.movie_title)
        print(
            build_writer_prompt(
                style_path=args.style,
                subtitle_srt_path=args.subtitle_srt,
                visual_segments_path=args.visual_segments,
                movie_title=movie_title,
                genre=args.genre,
            )
        )
        return 0
    else:
        missing_paths = missing_input_paths([args.beats, args.subtitle_srt, args.visual_segments])
        if missing_paths:
            report_missing_paths(missing_paths)
            return 1
        movie_title = infer_movie_title(args.subtitle_srt, args.movie_title)
        print(
            build_grounding_prompt(
                beats_path=args.beats,
                subtitle_srt_path=args.subtitle_srt,
                visual_segments_path=args.visual_segments,
                movie_title=movie_title,
            )
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
