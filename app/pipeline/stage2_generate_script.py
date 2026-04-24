"""Stage 2: Two-pass script authoring prompt assembler.

This stage stays manual for now, but the prompt contract is split into
two explicit passes:

1. Writer pass (`--mode writer`): produce narration beats with no timing.
2. Grounding pass (`--mode grounder`): consume the beat draft, full SRT,
    and `visual_segments.json`, then emit the final grounded script using
    `[SCENE start=... end=... source=... confidence=... evidence=...]`
    markers.

The goal is to keep Stage 2's human/LLM handoff reproducible while Stage 4
and Stage 5 operate on a precise grounding contract.
"""

from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path
from typing import Any

from app.pipeline.common.script_contract import seconds_to_timestamp
from app.pipeline.stage1_parse_subtitles import parse_subtitles


SCRIPT_WRITER_ROLE = (
    "You are a Chinese movie-review scriptwriter. You strictly follow the style "
    "rulebook provided below. You write in Simplified Chinese and focus only on "
    "storytelling, tone, and pacing. Do not assign timestamps in this pass."
)
GROUNDING_EDITOR_ROLE = (
    "You are the alignment editor for a movie-review pipeline. You must anchor "
    "each narration beat to either the SRT or the visual segment index, cite the "
    "evidence, and mark uncertain beats as ungrounded instead of inventing times."
)
SRT_PREVIEW_LINES = 40


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


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
    segments: list[dict[str, Any]] = json.loads(visual_segments_path.read_text(encoding="utf-8"))
    lines = []
    for index, segment in enumerate(segments, 1):
        segment_id = str(segment.get("id") or f"visual:{index:03d}")
        characters = "|".join(segment.get("characters") or []) or "-"
        confidence = float(segment.get("confidence") or 0.0)
        summary = collapse_whitespace(str(segment.get("summary") or ""))
        ocr_text = collapse_whitespace(str(segment.get("ocr_text") or ""))
        action_flag = "true" if segment.get("is_action") else "false"
        suffix = f" | ocr={ocr_text}" if ocr_text else ""
        lines.append(
            f"[{segment_id}] {segment['start']} --> {segment['end']} | chars={characters} "
            f"| action={action_flag} | confidence={confidence:.2f} | summary={summary}{suffix}"
        )
    return "\n".join(lines)


def build_writer_prompt(
    style_path: Path,
    subtitle_text_path: Path,
    movie_title: str,
    genre: str,
    subtitle_srt_path: Path | None = None,
) -> str:
    style_text = style_path.read_text(encoding="utf-8")
    plot_text = subtitle_text_path.read_text(encoding="utf-8")
    srt_preview = ""
    if subtitle_srt_path is not None:
        srt_text = subtitle_srt_path.read_text(encoding="utf-8")
        srt_preview = "\n".join(srt_text.splitlines()[:SRT_PREVIEW_LINES])

    optional_srt_section = ""
    if srt_preview:
        optional_srt_section = f"""
# SRT Preview — first {SRT_PREVIEW_LINES} lines
This is reference-only context. Do not emit timestamps or [SCENE] markers in this pass.
<<<SRT_PREVIEW_START>>>
{srt_preview}
<<<SRT_PREVIEW_END>>>
"""

    return f"""# Role
{SCRIPT_WRITER_ROLE}

# Style Rulebook
The rulebook below is the single source of truth for tone, structure,
character naming, and genre modulation. Follow every rule exactly.

<<<STYLE_RULEBOOK_START>>>
{style_text}
<<<STYLE_RULEBOOK_END>>>

# Movie
Title: {movie_title}
Genre: {genre}

# Plot Source — parsed subtitle plain text, in movie order
<<<PLOT_START>>>
{plot_text}
<<<PLOT_END>>>
{optional_srt_section}

# Output requirements

1. Length target: 7-12 minutes of spoken Chinese, approximately 1,800-2,800 Chinese characters.
2. Keep the structural markers:
   [TITLE], [HOOK], [ACT 1 - SETUP], [ACT 2 - ESCALATION],
   [ACT 3 - CLIMAX], [ACT 4 - RESOLUTION], [CLOSING].
3. Under each section, break the narration into short beats using explicit markers:
   [BEAT 1], [BEAT 2], [BEAT 3], ...
4. Each beat should contain one sentence or one short paragraph only.
5. Do not output any [SCENE] or [BROLL] markers in this pass.
6. Do not guess timestamps. Ignore clip timing entirely.
7. The [CLOSING] section still contains narration beats, but no visual marker of any kind.

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
2. If DIALOGUE: search the SRT reference first. Choose the best matching subtitle evidence and use that timestamp window.
3. If ACTION: search the visual segment reference. Prefer character overlap, then semantic match, then action=true when motion is described.
4. If the best candidate is weak, emit the beat as ungrounded instead of hallucinating a timestamp.
5. Preserve the section structure and narration text from the beat draft.

# Output contract

1. Replace every [BEAT N] marker with a grounded [SCENE ...] marker immediately above the beat text.
2. Use this exact attribute form for grounded beats:
   [SCENE start=HH:MM:SS.mmm end=HH:MM:SS.mmm source=srt|visual confidence=0.00 evidence=srt:NNN|visual:NNN]
3. When a beat is ungrounded, use:
   [SCENE source=ungrounded confidence=0.00 evidence=none]
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
    parser.add_argument(
        "--mode",
        choices=["writer", "grounder"],
        default="writer",
        help="Writer builds the beat-draft prompt; grounder builds the alignment prompt.",
    )
    parser.add_argument("--style", type=Path, help="Path to the style .md file")
    parser.add_argument("--subtitle-text", type=Path, help="Parsed plain-text plot (from Stage 1)")
    parser.add_argument("--subtitle-srt", type=Path, help="Source subtitle file (.srt or .ass)")
    parser.add_argument("--movie-title", help="Movie title with optional language")
    parser.add_argument("--genre", help="Genre keyword for the writer pass")
    parser.add_argument("--beats", type=Path, help="Beat draft produced by the writer pass")
    parser.add_argument("--visual-segments", type=Path, help="visual_segments.json from Stage 0")
    return parser


def missing_input_paths(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists()]


def report_missing_paths(missing: list[Path]) -> None:
    for path_arg in missing:
        print(f"Input not found: {path_arg}", file=sys.stderr)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.mode == "writer":
        missing = [
            flag_name
            for flag_name, value in (
                ("--style", args.style),
                ("--subtitle-text", args.subtitle_text),
                ("--movie-title", args.movie_title),
                ("--genre", args.genre),
            )
            if value is None
        ]
        if missing:
            print(f"Writer mode requires: {', '.join(missing)}", file=sys.stderr)
            return 1
        existing_paths = [args.style, args.subtitle_text]
        if args.subtitle_srt is not None:
            existing_paths.append(args.subtitle_srt)
        missing_paths = missing_input_paths(existing_paths)
        if missing_paths:
            report_missing_paths(missing_paths)
            return 1
        print(
            build_writer_prompt(
                style_path=args.style,
                subtitle_text_path=args.subtitle_text,
                subtitle_srt_path=args.subtitle_srt,
                movie_title=args.movie_title,
                genre=args.genre,
            )
        )
        return 0

    missing = [
        flag_name
        for flag_name, value in (
            ("--beats", args.beats),
            ("--subtitle-srt", args.subtitle_srt),
            ("--visual-segments", args.visual_segments),
            ("--movie-title", args.movie_title),
        )
        if value is None
    ]
    if missing:
        print(f"Grounder mode requires: {', '.join(missing)}", file=sys.stderr)
        return 1
    missing_paths = missing_input_paths([args.beats, args.subtitle_srt, args.visual_segments])
    if missing_paths:
        report_missing_paths(missing_paths)
        return 1
    print(
        build_grounding_prompt(
            beats_path=args.beats,
            subtitle_srt_path=args.subtitle_srt,
            visual_segments_path=args.visual_segments,
            movie_title=args.movie_title,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
