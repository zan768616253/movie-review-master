"""Build a copy-paste prompt for external LLM movie script drafting.

This tool does not generate the script itself. It assembles a plain-text
prompt from:

- a style markdown file
- Stage 0 `visual_segments.json`
- Stage 1 `subtitles.txt`

The prompt is designed for manual paste into Gemini / DeepSeek / similar
models so they can draft a full movie-retelling script in the chosen style.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.pipeline.common.json_io import load_json
from app.pipeline.common.script_contract import (
    load_visual_segments,
    seconds_to_timestamp,
    timestamp_to_seconds,
)


@dataclass(frozen=True)
class TimelineEntry:
    kind: str
    start_s: float
    end_s: float
    body: str
    priority: int
    sequence: int

    def render(self) -> str:
        start = seconds_to_timestamp(self.start_s)
        end = seconds_to_timestamp(self.end_s)
        return f"[{self.kind} {start} -> {end}] {self.body}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-story-prompt",
        description="Build a manual copy-paste prompt for external LLM movie script drafting.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--style", type=Path, required=True, help="Style markdown file.")
    parser.add_argument("--visual-segments", type=Path, default=None,
                        help="Stage 0 visual_segments.json. Required unless --plot-digest is used.")
    parser.add_argument("--subtitles-txt", type=Path, default=None,
                        help="Stage 1 subtitles.txt. Required unless --plot-digest is used.")
    parser.add_argument("--plot-digest", type=Path, default=None,
                        help="Pass 1 plot digest file. When provided, uses digest mode (two-pass workflow).")
    parser.add_argument("--out", type=Path, required=True, help="Output path for the generated prompt text.")
    parser.add_argument("--movie-title", default="", help="Optional movie title for prompt framing.")
    parser.add_argument("--target-minutes", type=float, default=None,
                        help="Target script length in minutes of spoken narration.")
    parser.add_argument(
        "--synopsis",
        type=Path,
        help="Optional synopsis markdown for plot, cast, and continuity grounding.",
    )
    parser.add_argument(
        "--genre",
        help="Optional genre name (e.g. Action, Comedy). If provided, will load example script from styles/genres/<style>/<genre>.txt.",
    )
    return parser


def normalize_inline_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    return " / ".join(part.strip() for part in text.split("\n") if part.strip())


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Text file is empty: {path}")
    return text


import re

_SUBTITLE_TXT_PATTERN = re.compile(
    r"^\[(?P<start>\d{2}:\d{2}:\d{2}\.\d+) -> (?P<end>\d{2}:\d{2}:\d{2}\.\d+)\]\s*(?P<body>.*)$"
)

def load_subtitles(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
        
    subtitles = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = _SUBTITLE_TXT_PATTERN.match(line)
        if not match:
            raise ValueError(f"Invalid subtitle line format: {line}")
            
        subtitles.append({
            "start": match.group("start"),
            "end": match.group("end"),
            "text": match.group("body"),
        })
    return subtitles


def build_timeline_entries(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []

    for index, segment in enumerate(visual_segments):
        try:
            start = str(segment["start"])
            end = str(segment["end"])
        except KeyError as exc:
            raise ValueError(f"Visual segment #{index + 1} is missing {exc.args[0]!r}") from exc

        start_s = timestamp_to_seconds(start)
        end_s = timestamp_to_seconds(end)
        if end_s <= start_s:
            raise ValueError(f"Visual segment #{index + 1} has end <= start")

        segment_id = str(segment.get("id") or f"visual:{index + 1:03d}")
        summary = normalize_inline_text(segment.get("summary")) or "(no visual summary)"
        parts = [f"{segment_id} | {summary}"]

        characters = segment.get("characters")
        if isinstance(characters, list):
            character_names = [normalize_inline_text(item) for item in characters if normalize_inline_text(item)]
            if character_names:
                parts.append(f"characters: {', '.join(character_names)}")

        ocr_text = normalize_inline_text(segment.get("ocr_text"))
        if ocr_text:
            parts.append(f"on-screen text: {ocr_text}")

        entries.append(
            TimelineEntry(
                kind="VISUAL",
                start_s=start_s,
                end_s=end_s,
                body=" | ".join(parts),
                priority=0,
                sequence=index,
            )
        )

    for index, subtitle in enumerate(subtitles):
        try:
            start_s = timestamp_to_seconds(str(subtitle["start"]))
            end_s = timestamp_to_seconds(str(subtitle["end"]))
        except KeyError as exc:
            raise ValueError(f"Subtitle #{index + 1} is missing {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Subtitle #{index + 1} has invalid timing values") from exc

        if end_s <= start_s:
            raise ValueError(f"Subtitle #{index + 1} has end <= start")

        text = normalize_inline_text(subtitle.get("text"))
        if not text:
            continue

        speaker = normalize_inline_text(subtitle.get("speaker"))
        if speaker:
            body = f"{speaker}: {text}"
        else:
            body = text

        entries.append(
            TimelineEntry(
                kind="SUBTITLE",
                start_s=start_s,
                end_s=end_s,
                body=body,
                priority=1,
                sequence=index,
            )
        )

    return sorted(entries, key=lambda item: (item.start_s, item.priority, item.end_s, item.sequence))


def render_timeline(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> str:
    return "\n".join(entry.render() for entry in build_timeline_entries(visual_segments, subtitles))


def _extract_golden_paragraph(genre_text: str, max_lines: int = 20) -> str | None:
    """Extract the first non-empty lines from the genre example as a style reminder."""
    lines = [line for line in genre_text.strip().split("\n") if line.strip()]
    if not lines:
        return None
    return "\n".join(lines[:max_lines])


def build_prompt(
    *,
    style_text: str,
    timeline_text: str,
    digest_text: str | None = None,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_text: str | None = None,
    target_minutes: float | None = None,
) -> str:
    if timeline_text is None and digest_text is None:
        raise ValueError("Either timeline_text or digest_text must be provided")

    use_digest = digest_text is not None
    movie_label = movie_title.strip() or "Unknown movie"

    # We build the prompt in sections.
    # To combat context rot, we put the massive data block (timeline or digest)
    # first, followed by the instructional and styling context. This ensures
    # the model pays maximum attention to the rules and output format right
    # before generation.
    sections: list[str] = []

    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            "# Source Material: Movie Synopsis and Cast\n"
            "Treat this synopsis as authoritative high-level context for names, relationships, motive, and full-story continuity.\n"
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

    # --- Writing task with optional length guidance ---
    task_lines = [
        "# Writing task",
        f"Write one complete script for {movie_label} based on the source material provided above.",
    ]
    if target_minutes is not None:
        task_lines.append(
            f"- Target script length: approximately {target_minutes:.0f} minutes of spoken narration "
            f"(~{int(target_minutes * 250)} Chinese characters)."
        )
    task_lines.extend([
        "- Retell the whole movie from beginning to end.",
        "- Make the script easy to follow even though the source material is fragmented notes.",
        "- Prioritize motive, causality, reversals, emotional movement, and payoff over flat scene listing.",
        "- Use the style's deeper storytelling logic, not just its wording.",
        "- If the style file defines naming rules, narrator stance, hook strategy, or ending pattern, follow those rules.",
    ])
    sections.append("\n".join(task_lines))

    # --- Source material usage guidance (differs for digest vs timeline) ---
    if use_digest:
        sections.append(
            "# How to use the source material\n"
            "- The style file defines the narrator's soul, pace, rhythm, humor, and storytelling logic.\n"
            "- The synopsis, when provided, is the best guide to character names and relationships.\n"
            "- The plot digest contains structured story beats with causal reasoning — use these to build BECAUSE-chains in your narration.\n"
            "- The 名场面 (Reviewable Moments) section highlights scenes that deserve detailed, vivid narration — do not skip them.\n"
            "- The 权力结构 (Power Map) helps you frame the story as a system of control and rebellion.\n"
            "- Preserve key dialogue from the digest when it serves the narration.\n"
            "- Do not mention the digest, plot beats, or source notes in the final answer."
        )
    else:
        sections.append(
            "# How to use the source material\n"
            "- The style file defines the narrator's soul, pace, rhythm, humor, and storytelling logic.\n"
            "- The synopsis, when provided, is the best high-level guide to plot continuity, character identity, relationships, and motive.\n"
            "- The movie timeline is already mixed in chronological order line by line.\n"
            "- VISUAL lines tell you what is happening on screen.\n"
            "- SUBTITLE lines tell you what characters literally say.\n"
            "- Use both together so you can reconstruct the whole movie without watching it.\n"
            "- Use the synopsis to keep the overall story coherent, especially when the timeline notes are fragmented or locally ambiguous.\n"
            "- Prefer subtitles for exact spoken content and visual lines for action, staging, on-screen text, and non-verbal beats.\n"
            "- Do not mention timestamps, visual segments, subtitles, JSON, or source notes in the final answer."
        )

    sections.append(
        "# Style rulebook\n"
        "<<<STYLE_RULEBOOK_START>>>\n"
        f"{style_text.strip()}\n"
        "<<<STYLE_RULEBOOK_END>>>"
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

        # Golden paragraph: repeat the opening of the genre example right
        # before the output gate as a final rhythm reminder.
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

    # Fixed output requirements — the act-structure headers from the Style
    # Rulebook are now explicitly required instead of being contradicted.
    sections.append(
        "# Output requirements\n"
        "- Output only the final script.\n"
        "- Use the act structure headers defined in the Style Rulebook "
        "(e.g. [TITLE], [HOOK], [ACT 1 - SETUP], etc.). No additional sub-headings beyond those.\n"
        "- No JSON.\n"
        "- No bullet points inside act prose.\n"
        "- No analysis before or after the script.\n"
        "- Keep the script in the primary language implied by the style file unless the source material clearly requires another language."
    )

    return "\n\n".join(sections).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    style_path = args.style.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    synopsis_path = args.synopsis.expanduser().resolve() if args.synopsis else None
    digest_path = args.plot_digest.expanduser().resolve() if args.plot_digest else None

    use_digest = digest_path is not None

    try:
        if not style_path.exists():
            raise FileNotFoundError(f"Style file not found: {style_path}")
        if synopsis_path is not None and not synopsis_path.exists():
            raise FileNotFoundError(f"Synopsis file not found: {synopsis_path}")

        style_text = _read_text(style_path)
        synopsis_text = _read_text(synopsis_path) if synopsis_path is not None else None

        # --- Digest mode (two-pass workflow) ---
        timeline_text: str
        digest_text: str | None = None
        visual_segments: list[dict[str, object]] = []
        subtitles: list[dict[str, object]] = []

        if use_digest:
            if not digest_path.exists():
                raise FileNotFoundError(f"Plot digest not found: {digest_path}")
            digest_text = _read_text(digest_path)
        else:
            # --- Timeline mode (original single-pass workflow) ---
            if args.visual_segments is None or args.subtitles_txt is None:
                raise ValueError(
                    "--visual-segments and --subtitles-txt are required "
                    "when --plot-digest is not provided"
                )
            visual_segments_path = args.visual_segments.expanduser().resolve()
            subtitles_txt_path = args.subtitles_txt.expanduser().resolve()
            if not visual_segments_path.exists():
                raise FileNotFoundError(f"Visual segments file not found: {visual_segments_path}")
            if not subtitles_txt_path.exists():
                raise FileNotFoundError(f"Subtitles TXT file not found: {subtitles_txt_path}")

            visual_segments = load_visual_segments(visual_segments_path)
            subtitles = load_subtitles(subtitles_txt_path)
            timeline_text = render_timeline(visual_segments, subtitles)
            if not timeline_text.strip():
                raise ValueError("The merged movie timeline is empty")

        # --- Genre example ---
        genre_text = None
        if args.genre:
            style_name = style_path.stem
            # Look in styles/genres/<style_name>/<genre>.txt (or fallback to style/genre/)
            genre_file = style_path.parent / "genres" / style_name / f"{args.genre}.txt"
            if not genre_file.exists():
                genre_file = style_path.parent / "genre" / style_name / f"{args.genre}.txt"

            if genre_file.exists():
                genre_text = _read_text(genre_file)
            else:
                print(f"Warning: Genre example not found at {genre_file}", file=sys.stderr)

        prompt_text = build_prompt(
            style_text=style_text,
            timeline_text=timeline_text,
            digest_text=digest_text,
            movie_title=args.movie_title,
            synopsis_text=synopsis_text,
            genre_text=genre_text,
            target_minutes=args.target_minutes,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(prompt_text, encoding="utf-8")
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    mode_label = "digest" if use_digest else "timeline"
    print(f"Generated story prompt ({mode_label} mode): {out_path}")
    if use_digest:
        print(f"  plot digest    : {digest_path}")
    else:
        print(f"  visual segments: {len(visual_segments)}")
        print(f"  subtitles      : {len(subtitles)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
