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
from app.pipeline.stage_2.pass_2_story import build_story_prompt


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
