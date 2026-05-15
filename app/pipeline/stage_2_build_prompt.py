"""Stage 2: build the LLM prompt for movie script writing.

Two modes:

- **story** (default): assemble a single-pass prompt that asks the LLM to
  write the full styled script directly. If ``--plot-digest`` is supplied,
  switches to two-pass mode where the prompt embeds a structured plot
  digest instead of the raw timeline.
- **digest** (``--digest``): assemble the Pass 1 prompt that asks the LLM
  to extract a structured plot digest. The digest reply is then used in
  story mode via ``--plot-digest`` for higher-quality long-movie scripts.

Both modes emit a single text file ready to paste into Gemini / DeepSeek /
Qwen.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from app.pipeline.common.script_contract import (
    load_visual_segments,
)

from app.pipeline.stage_2.timeline import (
    TimelineEntry,
    build_timeline_entries,
    load_subtitles,
    normalize_inline_text,
    parse_style_frontmatter,
    read_text_strict as _read_text,
    render_timeline,
)

from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt


# ---------------------------------------------------------------------------
# Story prompt (default mode; pass 2 of the two-pass workflow)
# ---------------------------------------------------------------------------



def _extract_golden_paragraph(genre_text: str, max_lines: int = 20) -> str | None:
    lines = [line for line in genre_text.strip().split("\n") if line.strip()]
    if not lines:
        return None
    return "\n".join(lines[:max_lines])


def _grounding_section(*, use_digest: bool) -> str:
    source_term = "the digest's Plot Beats" if use_digest else "the timeline's VISUAL lines"
    return (
        "# Grounding requirement (HARD RULE — read twice)\n"
        "Every narrative sentence you write must be cuttable: the human editor needs to find matching "
        "footage in the source movie for it. To enforce this, annotate every sentence with the "
        "visual_segment IDs that show what the sentence describes.\n\n"
        "**Format** — place a <refs>...</refs> tag on its own line directly ABOVE each sentence:\n\n"
        "```\n"
        "<refs>visual:031, visual:033-035</refs>\n"
        "故事开场，老猜每天送女儿去溜冰场学习。\n\n"
        "<refs>visual:050-052</refs>\n"
        "直到那天，雪山下的小镇发生了一起绑架案。\n"
        "```\n\n"
        "**Rules:**\n"
        "- One <refs> line per sentence. A sentence is a clause ending in 。！？.\n"
        "- A sentence may cite multiple IDs (comma-separated). Use a dash for consecutive ranges: "
        "`visual:033-035` means 033, 034, and 035.\n"
        f"- Only cite visual:NNN IDs that ACTUALLY appear in {source_term}. Do NOT invent IDs.\n"
        "- If you cannot find at least one visual_segment that depicts what a sentence describes, "
        "DROP that sentence. Brevity beats invention. A sentence with no footage breaks the edit.\n"
        "- The <refs> lines are metadata for the editor — they are stripped before TTS. Keep them on "
        "their own lines, NEVER inline within the narration prose.\n"
        "- The structural markers ([TITLE], [HOOK], [ACT N - ...], [CLOSING]) do not need <refs>. "
        "Only the narration sentences inside them do.\n"
        "- For an opening hook line that talks about the movie as a whole, cite one or two "
        "representative shots; do not cite dozens.\n\n"
        "**Concrete-noun rule — read this too:** stick to nouns, objects, locations, and "
        "subject-verb-object directions that appear in the cited visual_segments' summaries, "
        "on-screen text, character labels, or in the subtitles. Do NOT introduce weapons, "
        "vehicles, props, settings, or who-acts-on-whom relationships that are not in the "
        "source material. If the source says 'person holds a gun', do not write 'knife'. If "
        "the source describes A grabbing B, do not write that B grabs A. When the source is "
        "ambiguous about the direction, narrate vaguely ('two men struggle') rather than "
        "guessing a specific direction.\n"
    )


def build_story_prompt(
    *,
    style_text: str,
    timeline_text: str | None = None,
    digest_text: str | None = None,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_text: str | None = None,
    genre_rules_text: str | None = None,
    target_minutes: float | None = None,
    chars_per_minute: int = 250,
) -> str:
    if timeline_text is None and digest_text is None:
        raise ValueError("Either timeline_text or digest_text must be provided")

    use_digest = digest_text is not None
    movie_label = movie_title.strip() or "Unknown movie"

    sections: list[str] = []

    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            "# Source Material: Movie Synopsis and Cast\n"
            "Use this synopsis ONLY to look up character names and relationships. "
            "It may describe off-screen plot points the movie never shows — those have no footage "
            "and must NOT appear in the script.\n"
            "<<<SYNOPSIS_START>>>\n"
            f"{synopsis_text.strip()}\n"
            "<<<SYNOPSIS_END>>>"
        )

    if use_digest:
        sections.append(
            "# Source Material: Plot Digest\n"
            "This digest was extracted from the movie's visual segments and subtitles. "
            "It contains everything you need to write the script: characters, plot beats "
            "with causal reasoning, power dynamics, reviewable moments, key dialogue, "
            "and the full ending.\n"
            "<<<PLOT_DIGEST_START>>>\n"
            f"{digest_text.strip()}\n"
            "<<<PLOT_DIGEST_END>>>"
        )
    else:
        sections.append(
            "# Source Material: Chronological Movie Timeline\n"
            "This timeline contains VISUAL segments (what happens on screen) and SUBTITLE segments (what characters say).\n"
            "<<<MOVIE_TIMELINE_START>>>\n"
            f"{timeline_text.strip()}\n" 
            "<<<MOVIE_TIMELINE_END>>>"
        )

    sections.append(
        "# Role\n"
        "You are writing a plain movie-review / story-retelling script for a short-form movie channel."
    )

    sections.append(
        "# Core style transfer requirement\n"
        "Do not merely borrow wording, catchphrases, or surface-level sentence patterns from the style file. "
        "Absorb the style's soul: narrator mindset, value system, pace, rhythm, humor, hook logic, emotional release, "
        "scene selection instinct, and compression strategy. The final script should feel native to the style, not like a paraphrase wearing the style's vocabulary."
    )

    task_lines = [
        "# Writing task",
        f"Write one complete script for {movie_label} based on the source material provided above.",
    ]
    if target_minutes is not None:
        task_lines.append(
            f"- Target script length: approximately {target_minutes:.0f} minutes of spoken narration "
            f"(~{int(target_minutes * chars_per_minute)} Chinese characters)."
        )
    task_lines.extend([
        "- Retell the whole movie from beginning to end.",
        "- Narrate AROUND gaps in the source material. Do not invent footage, characters, dialogue, "
        "or plot points that are not present in the source material — the video editor needs to find "
        "matching footage for every sentence, and invented content has no footage.",
        "- Prioritize motive, causality, reversals, emotional movement, and payoff over flat scene listing.",
        "- Use the style's deeper storytelling logic, not just its wording.",
        "- If the style file defines naming rules, narrator stance, hook strategy, or ending pattern, follow those rules.",
    ])
    sections.append("\n".join(task_lines))

    sections.append(_grounding_section(use_digest=use_digest))

    if use_digest:
        sections.append(
            "# How to use the source material\n"
            "- The style file defines the narrator's soul, pace, rhythm, humor, and storytelling logic.\n"
            "- The synopsis, when provided, is ONLY for clarifying character names and relationships. "
            "Do NOT use the synopsis to add plot points that are not in the digest — those plot points have no footage.\n"
            "- The plot digest contains structured story beats with causal reasoning — use these to build BECAUSE-chains in your narration.\n"
            "- Each Plot Beat in the digest cites visual_segment IDs (镜头: visual:NNN, ...). "
            "Those IDs are what you cite in <refs> for each sentence — see the grounding requirement below.\n"
            "- The 名场面 (Reviewable Moments) section highlights scenes that deserve detailed, vivid narration — do not skip them.\n"
            "- The 权力结构 (Power Map) helps you frame the story as a system of control and rebellion.\n"
            "- Preserve key dialogue from the digest when it serves the narration.\n"
            "- Do not mention the digest, plot beats, or source notes in the final answer."
        )
    else:
        sections.append(
            "# How to use the source material\n"
            "- The style file defines the narrator's soul, pace, rhythm, humor, and storytelling logic.\n"
            "- The synopsis, when provided, is ONLY for clarifying character names and relationships. "
            "Do NOT use the synopsis to add plot points that are not in the timeline — those plot points have no footage.\n"
            "- The movie timeline is already mixed in chronological order line by line.\n"
            "- VISUAL lines tell you what is happening on screen. Each starts with its visual_segment ID (e.g. `visual:031 | ...`); "
            "these IDs are what you cite in <refs> for each sentence — see the grounding requirement below.\n"
            "- SUBTITLE lines tell you what characters literally say.\n"
            "- Use both together so you can reconstruct the whole movie without watching it.\n"
            "- Prefer subtitles for exact spoken content and visual lines for action, staging, on-screen text, and non-verbal beats.\n"
            "- Do not mention timestamps, JSON, or source notes in the final answer (visual:NNN IDs in <refs> are the only exception)."
        )

    sections.append(
        "# Style rulebook\n"
        "<<<STYLE_RULEBOOK_START>>>\n"
        f"{style_text.strip()}\n"
        "<<<STYLE_RULEBOOK_END>>>"
    )

    if genre_rules_text is not None and genre_rules_text.strip():
        sections.append(
            "# Genre focus\n"
            "Genre-specific emphasis layered on top of the style rulebook. The style defines the "
            "narrator's voice; these rules tell you what to weight for this particular genre.\n"
            "<<<GENRE_RULES_START>>>\n"
            f"{genre_rules_text.strip()}\n"
            "<<<GENRE_RULES_END>>>"
        )

    if genre_text is not None and genre_text.strip():
        sections.append(
            "# Genre example script\n"
            "Below is a high-quality example script in the target style and genre. "
            "Study its pacing, phrasing, tone, and structure to understand how the final script should read.\n"
            "<<<GENRE_EXAMPLE_START>>>\n"
            f"{genre_text.strip()}\n"
            "<<<GENRE_EXAMPLE_END>>>"
        )

        golden = _extract_golden_paragraph(genre_text)
        if golden:
            sections.append(
                "# Style reminder — match this rhythm\n"
                "Your script MUST match the line-by-line rhythm of the genre example. "
                "Here is its opening again for emphasis — notice the short, punchy lines:\n"
                "```\n"
                f"{golden}\n"
                "```\n"
                "Write in this rhythm: short lines, staccato delivery, register-collision humor. "
                "Do NOT write long compound paragraphs."
            )

    sections.append(
        "# Output requirements\n"
        "- Output only the final script.\n"
        "- Use the act structure headers defined in the Style Rulebook "
        "(e.g. [TITLE], [HOOK], [ACT 1 - SETUP], etc.). No additional sub-headings beyond those.\n"
        "- Every narration sentence is preceded by its own <refs>...</refs> line per the grounding requirement.\n"
        "- No JSON.\n"
        "- No bullet points inside act prose.\n"
        "- No analysis before or after the script.\n"
        "- Keep the script in the primary language implied by the style file unless the source material clearly requires another language."
    )

    return "\n\n".join(sections).rstrip() + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-prompt",
        description="Stage 2: build the LLM prompt for movie script writing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--digest", action="store_true",
                        help="Build the Pass 1 digest prompt instead of the story prompt.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output path for the generated prompt text.")
    parser.add_argument("--movie-title", default="",
                        help="Optional movie title for prompt framing.")
    parser.add_argument("--target-minutes", type=float, default=None,
                        help="Target script length in minutes of spoken narration.")
    parser.add_argument("--synopsis", type=Path,
                        help="Optional synopsis markdown for plot, cast, and continuity grounding.")
    parser.add_argument("--visual-segments", type=Path,
                        help="Stage 1 visual_segments.json. Required unless --plot-digest is used in story mode.")
    parser.add_argument("--subtitles-txt", type=Path,
                        help="Stage 1 subtitles.txt. Required unless --plot-digest is used in story mode.")
    parser.add_argument("--style", type=Path,
                        help="Style markdown file. Required in story mode; optional in --digest mode "
                             "(used only to locate the genre rules file).")
    parser.add_argument("--genre",
                        help="Optional genre name. In story mode loads styles/genres/<style>/<genre>.txt "
                             "as a rhythm example. In both modes, also loads <genre>.rules.md as a "
                             "genre-specific focus rulebook when present.")

    # Story-mode-only options
    parser.add_argument("--plot-digest", type=Path,
                        help="Pass 1 plot digest file. When provided in story mode, switches to digest mode.")
    return parser


def _resolve_optional(path: Path | None) -> Path | None:
    return path.expanduser().resolve() if path is not None else None


def _find_genre_asset(style_path: Path, genre: str, filename: str) -> Path | None:
    for parent in ("genres", "genre"):
        candidate = style_path.parent / parent / style_path.stem / filename
        if candidate.exists():
            return candidate
    return None


def _run_digest(args) -> int:
    visual_segments_path = _resolve_optional(args.visual_segments)
    subtitles_txt_path = _resolve_optional(args.subtitles_txt)
    synopsis_path = _resolve_optional(args.synopsis)
    style_path = _resolve_optional(args.style)
    out_path = args.out.expanduser().resolve()

    if visual_segments_path is None or subtitles_txt_path is None:
        print("Error: --visual-segments and --subtitles-txt are required in --digest mode", file=sys.stderr)
        return 1
    if not visual_segments_path.exists():
        print(f"Error: Visual segments not found: {visual_segments_path}", file=sys.stderr)
        return 1
    if not subtitles_txt_path.exists():
        print(f"Error: Subtitles not found: {subtitles_txt_path}", file=sys.stderr)
        return 1
    if synopsis_path is not None and not synopsis_path.exists():
        print(f"Error: Synopsis not found: {synopsis_path}", file=sys.stderr)
        return 1

    synopsis_text = _read_text(synopsis_path) if synopsis_path else None
    visual_segments = load_visual_segments(visual_segments_path)
    subtitles = load_subtitles(subtitles_txt_path)
    timeline_text = render_timeline(visual_segments, subtitles)
    if not timeline_text.strip():
        print("Error: The merged movie timeline is empty", file=sys.stderr)
        return 1

    genre_rules_text: str | None = None
    if args.genre and style_path is not None:
        rules_file = _find_genre_asset(style_path, args.genre, f"{args.genre}.rules.md")
        if rules_file is not None:
            genre_rules_text = _read_text(rules_file)

    prompt_text = build_digest_prompt(
        timeline_text=timeline_text,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
        genre_rules_text=genre_rules_text,
        target_minutes=args.target_minutes if args.target_minutes is not None else 12.0,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt_text, encoding="utf-8")
    print(f"Generated digest prompt: {out_path}")
    print(f"  visual segments : {len(visual_segments)}")
    print(f"  subtitles       : {len(subtitles)}")
    return 0


def _run_story(args) -> int:
    style_path = _resolve_optional(args.style)
    out_path = args.out.expanduser().resolve()
    synopsis_path = _resolve_optional(args.synopsis)
    digest_path = _resolve_optional(args.plot_digest)

    if style_path is None:
        print("Error: --style is required in story mode", file=sys.stderr)
        return 1
    if not style_path.exists():
        print(f"Error: Style file not found: {style_path}", file=sys.stderr)
        return 1
    if synopsis_path is not None and not synopsis_path.exists():
        print(f"Error: Synopsis file not found: {synopsis_path}", file=sys.stderr)
        return 1

    style_raw = _read_text(style_path)
    style_meta, style_text = parse_style_frontmatter(style_raw)
    chars_per_minute = int(style_meta.get("chars_per_minute", 250))
    synopsis_text = _read_text(synopsis_path) if synopsis_path else None

    use_digest = digest_path is not None
    timeline_text: str | None = None
    digest_text: str | None = None
    visual_segments: list[dict[str, object]] = []
    subtitles: list[dict[str, object]] = []

    if use_digest:
        if not digest_path.exists():
            print(f"Error: Plot digest not found: {digest_path}", file=sys.stderr)
            return 1
        digest_text = _read_text(digest_path)
    else:
        visual_segments_path = _resolve_optional(args.visual_segments)
        subtitles_txt_path = _resolve_optional(args.subtitles_txt)
        if visual_segments_path is None or subtitles_txt_path is None:
            print("Error: --visual-segments and --subtitles-txt are required when --plot-digest is not provided",
                  file=sys.stderr)
            return 1
        if not visual_segments_path.exists():
            print(f"Error: Visual segments not found: {visual_segments_path}", file=sys.stderr)
            return 1
        if not subtitles_txt_path.exists():
            print(f"Error: Subtitles not found: {subtitles_txt_path}", file=sys.stderr)
            return 1
        visual_segments = load_visual_segments(visual_segments_path)
        subtitles = load_subtitles(subtitles_txt_path)
        timeline_text = render_timeline(visual_segments, subtitles)
        if not timeline_text.strip():
            print("Error: The merged movie timeline is empty", file=sys.stderr)
            return 1

    genre_text = None
    genre_rules_text = None
    if args.genre:
        example_file = _find_genre_asset(style_path, args.genre, f"{args.genre}.txt")
        if example_file is not None:
            genre_text = _read_text(example_file)
        else:
            print(f"Warning: Genre example not found for {args.genre!r} under {style_path.parent}", file=sys.stderr)

        rules_file = _find_genre_asset(style_path, args.genre, f"{args.genre}.rules.md")
        if rules_file is not None:
            genre_rules_text = _read_text(rules_file)

    prompt_text = build_story_prompt(
        style_text=style_text,
        timeline_text=timeline_text,
        digest_text=digest_text,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
        genre_text=genre_text,
        genre_rules_text=genre_rules_text,
        target_minutes=args.target_minutes,
        chars_per_minute=chars_per_minute,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt_text, encoding="utf-8")

    mode_label = "digest" if use_digest else "timeline"
    print(f"Generated story prompt ({mode_label} mode): {out_path}")
    if use_digest:
        print(f"  plot digest    : {digest_path}")
    else:
        print(f"  visual segments: {len(visual_segments)}")
        print(f"  subtitles      : {len(subtitles)}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run_digest(args) if args.digest else _run_story(args)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
