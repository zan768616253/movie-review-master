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
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.pipeline.common.script_contract import (
    load_visual_segments,
    seconds_to_timestamp,
    timestamp_to_seconds,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*\n", re.DOTALL)
_SUBTITLE_TXT_PATTERN = re.compile(
    r"^\[(?P<start>\d{2}:\d{2}:\d{2}\.\d+) -> (?P<end>\d{2}:\d{2}:\d{2}\.\d+)\]\s*(?P<body>.*)$"
)


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


def parse_style_frontmatter(style_text: str) -> tuple[dict[str, object], str]:
    """Extract simple key-value frontmatter from a style markdown file."""
    m = _FRONTMATTER_RE.match(style_text)
    if not m:
        return {}, style_text
    meta: dict[str, object] = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        for convert in (int, float):
            try:
                val = convert(val)  # type: ignore[assignment]
                break
            except (ValueError, TypeError):
                continue
        meta[key] = val
    return meta, style_text[m.end():]


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

        entries.append(TimelineEntry(
            kind="VISUAL",
            start_s=start_s,
            end_s=end_s,
            body=" | ".join(parts),
            priority=0,
            sequence=index,
        ))

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
        body = f"{speaker}: {text}" if speaker else text

        entries.append(TimelineEntry(
            kind="SUBTITLE",
            start_s=start_s,
            end_s=end_s,
            body=body,
            priority=1,
            sequence=index,
        ))

    return sorted(entries, key=lambda item: (item.start_s, item.priority, item.end_s, item.sequence))


def render_timeline(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> str:
    return "\n".join(entry.render() for entry in build_timeline_entries(visual_segments, subtitles))


# ---------------------------------------------------------------------------
# Story prompt (default mode; pass 2 of the two-pass workflow)
# ---------------------------------------------------------------------------


def _extract_golden_paragraph(genre_text: str, max_lines: int = 20) -> str | None:
    lines = [line for line in genre_text.strip().split("\n") if line.strip()]
    if not lines:
        return None
    return "\n".join(lines[:max_lines])


def build_story_prompt(
    *,
    style_text: str,
    timeline_text: str | None = None,
    digest_text: str | None = None,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_text: str | None = None,
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
        "- Make the script easy to follow even though the source material is fragmented notes.",
        "- Prioritize motive, causality, reversals, emotional movement, and payoff over flat scene listing.",
        "- Use the style's deeper storytelling logic, not just its wording.",
        "- If the style file defines naming rules, narrator stance, hook strategy, or ending pattern, follow those rules.",
    ])
    sections.append("\n".join(task_lines))

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
        "- No JSON.\n"
        "- No bullet points inside act prose.\n"
        "- No analysis before or after the script.\n"
        "- Keep the script in the primary language implied by the style file unless the source material clearly requires another language."
    )

    return "\n\n".join(sections).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Digest prompt (--digest mode; pass 1 of the two-pass workflow)
# ---------------------------------------------------------------------------


def build_digest_prompt(
    *,
    timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
    target_minutes: float = 12.0,
) -> str:
    """Assemble the Pass 1 digest prompt."""
    movie_label = movie_title.strip() or "Unknown movie"

    sections: list[str] = []

    sections.append(
        "# Task\n"
        "You are a movie analyst preparing a detailed plot digest for a movie REVIEWER.\n"
        "The reviewer will use your digest to write an entertaining, detail-rich "
        f"movie retelling script (~{target_minutes:.0f} minutes of spoken narration).\n\n"
        "Your job is to extract EVERYTHING the reviewer needs — not just the bare plot, "
        "but the moments that make this movie interesting, funny, tense, absurd, or "
        "emotionally powerful to talk about.\n\n"
        "A good digest preserves:\n"
        "- The full plot with causal reasoning (WHY things happen, not just WHAT)\n"
        "- Memorable dialogue worth quoting verbatim\n"
        "- Visually striking or absurd moments\n"
        "- Ironic situations, satisfying revenge, and emotional gut-punches\n"
        "- Character dynamics, power shifts, and betrayals\n"
        "- Action set-pieces with enough detail to narrate vividly\n"
        "- The actual ending (no spoiler avoidance)\n\n"
        "A bad digest is a dry plot summary that loses all the flavor."
    )

    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            f"# Synopsis for {movie_label}\n"
            "Use this as authoritative context for character names, relationships, "
            "and overall story arc.\n"
            "<<<SYNOPSIS_START>>>\n"
            f"{synopsis_text.strip()}\n"
            "<<<SYNOPSIS_END>>>"
        )

    sections.append(
        "# Chronological Movie Timeline\n"
        "This timeline contains VISUAL segments (what happens on screen) and "
        "SUBTITLE segments (what characters say). Read it carefully to "
        "reconstruct the full movie.\n"
        "<<<MOVIE_TIMELINE_START>>>\n"
        f"{timeline_text.strip()}\n"
        "<<<MOVIE_TIMELINE_END>>>"
    )

    sections.append(
        f"# Output Format: Plot Digest for {movie_label}\n"
        "Write the entire digest in Chinese. Be detailed — the reviewer cannot "
        "watch the movie, so your digest is their only source.\n\n"
        "## 角色表 (Character Table)\n"
        "For each important character (max 8-10), provide:\n"
        "- 原名: Original name from the movie\n"
        "- 身份: Role (protagonist / antagonist / ally / victim / etc.)\n"
        "- 关系: Key relationships to other characters\n"
        "- 动机: What they want\n"
        "- 结局: What ultimately happens to them\n"
        "- 性格特点: 1-2 defining personality traits\n\n"
        "## 权力结构 (Power Map)\n"
        "Describe who controls what, who deceives whom, and how power shifts "
        "throughout the movie. Who is pretending? Who is trapped? Who holds "
        "the real leverage?\n\n"
        "## 剧情脉络 (Plot Beats)\n"
        "List 30-50 major story beats in chronological order. For EACH beat:\n"
        "- 事件: What happens (2-3 sentences, vivid and specific)\n"
        "- 因果: Why this happens / what it causes (the causal chain)\n"
        "- 台词: Key dialogue if any (quote the most impactful lines verbatim)\n"
        "- 情绪: Emotional register (tension / humor / horror / tenderness / etc.)\n\n"
        "IMPORTANT: Be detailed enough that someone who has never seen the movie "
        "can retell the FULL story. Each major scene transition should be a "
        "separate beat. Do NOT merge multiple scenes into one vague beat.\n\n"
        "## 名场面 (Reviewable Moments)\n"
        "List 10-15 moments a movie reviewer would love to describe:\n"
        "- Visually absurd or striking images\n"
        "- Ironic situations or logic failures\n"
        "- Satisfying revenge or comeuppance\n"
        "- Embarrassing or humiliating scenes\n"
        "- Shocking twists or reveals\n"
        "- Action sequences with interesting choreography\n"
        "- Emotional gut-punches\n"
        "- Unintentionally funny moments\n\n"
        "For each moment, include 2-4 sentences of vivid detail — enough for "
        "the reviewer to narrate it as if they watched it.\n\n"
        "## 核心矛盾 (Core Conflict & Themes)\n"
        "- What is this movie really about? (1-2 sentences)\n"
        "- What is the central irony or contradiction?\n"
        "- What question does the movie leave the audience with?\n\n"
        "## 结局 (Full Ending)\n"
        "Describe the ending in FULL detail:\n"
        "- How the climax resolves\n"
        "- Every main character's final fate\n"
        "- The emotional aftertaste\n"
        "- Any post-credits scene or final twist"
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

    # Story-mode-only options
    parser.add_argument("--style", type=Path,
                        help="Style markdown file. Required in story mode.")
    parser.add_argument("--plot-digest", type=Path,
                        help="Pass 1 plot digest file. When provided in story mode, switches to digest mode.")
    parser.add_argument("--genre", help="Optional genre name. Loads styles/genres/<style>/<genre>.txt as a rhythm example.")
    return parser


def _resolve_optional(path: Path | None) -> Path | None:
    return path.expanduser().resolve() if path is not None else None


def _run_digest(args) -> int:
    visual_segments_path = _resolve_optional(args.visual_segments)
    subtitles_txt_path = _resolve_optional(args.subtitles_txt)
    synopsis_path = _resolve_optional(args.synopsis)
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

    prompt_text = build_digest_prompt(
        timeline_text=timeline_text,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
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
    if args.genre:
        genre_file = style_path.parent / "genres" / style_path.stem / f"{args.genre}.txt"
        if not genre_file.exists():
            genre_file = style_path.parent / "genre" / style_path.stem / f"{args.genre}.txt"
        if genre_file.exists():
            genre_text = _read_text(genre_file)
        else:
            print(f"Warning: Genre example not found at {genre_file}", file=sys.stderr)

    prompt_text = build_story_prompt(
        style_text=style_text,
        timeline_text=timeline_text,
        digest_text=digest_text,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
        genre_text=genre_text,
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
