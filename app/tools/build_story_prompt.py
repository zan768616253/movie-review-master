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
    parser.add_argument("--visual-segments", type=Path, required=True, help="Stage 0 visual_segments.json.")
    parser.add_argument("--subtitles-txt", type=Path, required=True, help="Stage 1 subtitles.txt.")
    parser.add_argument("--out", type=Path, required=True, help="Output path for the generated prompt text.")
    parser.add_argument("--movie-title", default="", help="Optional movie title for prompt framing.")
    parser.add_argument(
        "--synopsis",
        type=Path,
        help="Optional synopsis markdown for plot, cast, and continuity grounding.",
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


def build_prompt(
    *,
    style_text: str,
    timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
) -> str:
    movie_label = movie_title.strip() or "Unknown movie"
    sections = [
        "# Role\n"
        "You are writing a plain movie-review / story-retelling script for a short-form movie channel.",
        "# Core style transfer requirement\n"
        "Do not merely borrow wording, catchphrases, or surface-level sentence patterns from the style file. "
        "Absorb the style's soul: narrator mindset, value system, pace, rhythm, humor, hook logic, emotional release, "
        "scene selection instinct, and compression strategy. The final script should feel native to the style, not like a paraphrase wearing the style's vocabulary.",
        "# Writing task\n"
        f"Write one complete script for {movie_label} based on the source material below.\n"
        "- Retell the whole movie from beginning to end.\n"
        "- Make the script easy to follow even though the source material is fragmented notes.\n"
        "- Prioritize motive, causality, reversals, emotional movement, and payoff over flat scene listing.\n"
        "- Use the style's deeper storytelling logic, not just its wording.\n"
        "- If the style file defines naming rules, narrator stance, hook strategy, or ending pattern, follow those rules.",
        "# How to use the source material\n"
        "- The style file defines the narrator's soul, pace, rhythm, humor, and storytelling logic.\n"
        "- The synopsis, when provided, is the best high-level guide to plot continuity, character identity, relationships, and motive.\n"
        "- The movie timeline is already mixed in chronological order line by line.\n"
        "- VISUAL lines tell you what is happening on screen.\n"
        "- SUBTITLE lines tell you what characters literally say.\n"
        "- Use both together so you can reconstruct the whole movie without watching it.\n"
        "- Use the synopsis to keep the overall story coherent, especially when the timeline notes are fragmented or locally ambiguous.\n"
        "- Prefer subtitles for exact spoken content and visual lines for action, staging, on-screen text, and non-verbal beats.\n"
        "- Do not mention timestamps, visual segments, subtitles, JSON, or source notes in the final answer.",
        "# Output requirements\n"
        "- Output only the final script.\n"
        "- No JSON.\n"
        "- No bullet points.\n"
        "- No section headings.\n"
        "- No analysis before or after the script.\n"
        "- Keep the script in the primary language implied by the style file unless the source material clearly requires another language.",
        "# Style rulebook\n"
        "<<<STYLE_RULEBOOK_START>>>\n"
        f"{style_text.strip()}\n"
        "<<<STYLE_RULEBOOK_END>>>",
    ]

    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            "# Movie synopsis and cast grounding\n"
            "Treat this synopsis as authoritative high-level context for names, relationships, motive, and full-story continuity.\n"
            "<<<SYNOPSIS_START>>>\n"
            f"{synopsis_text.strip()}\n"
            "<<<SYNOPSIS_END>>>"
        )

    sections.append(
        "# Chronological movie timeline\n"
        "<<<MOVIE_TIMELINE_START>>>\n"
        f"{timeline_text.strip()}\n"
        "<<<MOVIE_TIMELINE_END>>>"
    )

    return "\n\n".join(sections).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    style_path = args.style.expanduser().resolve()
    visual_segments_path = args.visual_segments.expanduser().resolve()
    subtitles_txt_path = args.subtitles_txt.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    synopsis_path = args.synopsis.expanduser().resolve() if args.synopsis else None

    try:
        if not style_path.exists():
            raise FileNotFoundError(f"Style file not found: {style_path}")
        if not visual_segments_path.exists():
            raise FileNotFoundError(f"Visual segments file not found: {visual_segments_path}")
        if not subtitles_txt_path.exists():
            raise FileNotFoundError(f"Subtitles TXT file not found: {subtitles_txt_path}")
        if synopsis_path is not None and not synopsis_path.exists():
            raise FileNotFoundError(f"Synopsis file not found: {synopsis_path}")

        style_text = _read_text(style_path)
        synopsis_text = _read_text(synopsis_path) if synopsis_path is not None else None
        visual_segments = load_visual_segments(visual_segments_path)
        subtitles = load_subtitles(subtitles_txt_path)
        timeline_text = render_timeline(visual_segments, subtitles)
        if not timeline_text.strip():
            raise ValueError("The merged movie timeline is empty")

        prompt_text = build_prompt(
            style_text=style_text,
            timeline_text=timeline_text,
            movie_title=args.movie_title,
            synopsis_text=synopsis_text,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(prompt_text, encoding="utf-8")
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Generated story prompt: {out_path}")
    print(f"  visual segments: {len(visual_segments)}")
    print(f"  subtitles      : {len(subtitles)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
