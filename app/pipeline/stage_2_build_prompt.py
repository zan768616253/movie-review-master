"""Stage 2 CLI dispatcher: build the LLM prompt for the appropriate pass.

Three modes (mutually exclusive):

- ``--outline``           Pass 0 (scene outline).
- ``--digest``            Pass 1 (digest). Add ``--chunked`` for the 3-call variant.
                          Add ``--scene-markers <path>`` to activate act-weighted beat targets.
- (default, no flag)      Pass 2 (story script).

Re-exports keep the public API stable for downstream tests:
``build_digest_prompt``, ``build_story_prompt``, ``TimelineEntry``,
``build_timeline_entries``, ``render_timeline``, ``load_subtitles``,
``parse_style_frontmatter``, ``normalize_inline_text``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from app.pipeline.common.script_contract import load_visual_segments

from app.pipeline.stage_2.pass_0_outline import build_outline_prompt, render_thin_timeline
from app.pipeline.stage_2.pass_1_digest_chunked import (
    CHUNK_ORDER,
    build_chunked_digest_prompts,
)
from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt
from app.pipeline.stage_2.pass_2_story import build_story_prompt
from app.pipeline.stage_2.scene_markers import (
    SceneMarkersDocument,
    load_scene_markers,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-prompt",
        description="Stage 2: build the LLM prompt for movie script writing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--outline", action="store_true",
                      help="Build the Pass 0 outline prompt (scene_markers.json producer).")
    mode.add_argument("--digest", action="store_true",
                      help="Build the Pass 1 digest prompt.")
    # Default (no flag) is story mode.

    parser.add_argument("--chunked", action="store_true",
                        help="In --digest mode, build three sibling prompts "
                             "(front/climax/tail) instead of one.")
    parser.add_argument("--scene-markers", type=Path,
                        help="Pass 0 output. Activates scene-anchored, act-weighted beat "
                             "targets in --digest mode. Required when --chunked is set.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output path. In --chunked mode, sibling .front/.climax/.tail "
                             "files are written next to this path.")
    parser.add_argument("--movie-title", default="",
                        help="Optional movie title for prompt framing.")
    parser.add_argument("--target-minutes", type=float, default=None,
                        help="Target script length in minutes of spoken narration.")
    parser.add_argument("--synopsis", type=Path,
                        help="Optional synopsis markdown.")
    parser.add_argument("--visual-segments", type=Path,
                        help="Stage 1 visual_segments.json.")
    parser.add_argument("--subtitles-txt", type=Path,
                        help="Stage 1 subtitles.txt.")
    parser.add_argument("--style", type=Path,
                        help="Style markdown file. Required in story mode; optional in "
                             "--digest mode (used to locate the genre rules file).")
    parser.add_argument("--genre",
                        help="Optional genre name. In story mode loads styles/genres/<style>/<genre>.txt "
                             "as a rhythm example. In both modes, also loads <genre>.rules.md as a "
                             "genre-specific focus rulebook when present.")
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


def _load_genre_rules_for_digest(style_path: Path | None, genre: str | None) -> str | None:
    if not (style_path and genre):
        return None
    rules_file = _find_genre_asset(style_path, genre, f"{genre}.rules.md")
    return _read_text(rules_file) if rules_file else None


def _run_outline(args) -> int:
    visual_path = _resolve_optional(args.visual_segments)
    subs_path = _resolve_optional(args.subtitles_txt)
    syn_path = _resolve_optional(args.synopsis)
    out_path = args.out.expanduser().resolve()

    if visual_path is None or subs_path is None:
        print("Error: --visual-segments and --subtitles-txt are required in --outline mode", file=sys.stderr)
        return 1
    if not visual_path.exists():
        print(f"Error: Visual segments not found: {visual_path}", file=sys.stderr)
        return 1
    if not subs_path.exists():
        print(f"Error: Subtitles not found: {subs_path}", file=sys.stderr)
        return 1
    if syn_path is not None and not syn_path.exists():
        print(f"Error: Synopsis not found: {syn_path}", file=sys.stderr)
        return 1

    visual_segments = load_visual_segments(visual_path)
    subtitles = load_subtitles(subs_path)
    thin = render_thin_timeline(visual_segments, subtitles)
    if not thin.strip():
        print("Error: The thin timeline is empty", file=sys.stderr)
        return 1

    synopsis_text = _read_text(syn_path) if syn_path else None
    prompt = build_outline_prompt(
        thin_timeline_text=thin,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt, encoding="utf-8")
    print(f"Generated outline prompt: {out_path}")
    print(f"  visual segments : {len(visual_segments)}")
    print(f"  subtitles       : {len(subtitles)}")
    return 0


def _run_digest(args) -> int:
    visual_path = _resolve_optional(args.visual_segments)
    subs_path = _resolve_optional(args.subtitles_txt)
    syn_path = _resolve_optional(args.synopsis)
    scene_path = _resolve_optional(args.scene_markers)
    style_path = _resolve_optional(args.style)
    out_path = args.out.expanduser().resolve()

    if visual_path is None or subs_path is None:
        print("Error: --visual-segments and --subtitles-txt are required in --digest mode", file=sys.stderr)
        return 1
    if not visual_path.exists() or not subs_path.exists():
        print("Error: Stage 1 inputs not found", file=sys.stderr)
        return 1
    if syn_path is not None and not syn_path.exists():
        print(f"Error: Synopsis not found: {syn_path}", file=sys.stderr)
        return 1
    if args.chunked and scene_path is None:
        print("Error: --chunked requires --scene-markers", file=sys.stderr)
        return 1

    scene_doc: SceneMarkersDocument | None = None
    if scene_path is not None:
        if not scene_path.exists():
            print(f"Error: Scene markers not found: {scene_path}", file=sys.stderr)
            return 1
        scene_doc = load_scene_markers(scene_path)

    visual_segments = load_visual_segments(visual_path)
    subtitles = load_subtitles(subs_path)
    synopsis_text = _read_text(syn_path) if syn_path else None
    genre_rules_text = _load_genre_rules_for_digest(style_path, args.genre)
    target_minutes = args.target_minutes if args.target_minutes is not None else 12.0

    if args.chunked:
        prompts = build_chunked_digest_prompts(
            scene_markers=scene_doc,
            visual_segments=visual_segments,
            subtitles=subtitles,
            movie_title=args.movie_title,
            synopsis_text=synopsis_text,
            genre_rules_text=genre_rules_text,
            target_minutes=target_minutes,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        for label in CHUNK_ORDER:
            sibling = out_path.with_suffix(f".{label}{out_path.suffix}")
            sibling.write_text(prompts[label], encoding="utf-8")
            print(f"Generated chunked digest prompt: {sibling}")
        return 0

    timeline_text = render_timeline(visual_segments, subtitles)
    if not timeline_text.strip():
        print("Error: The merged movie timeline is empty", file=sys.stderr)
        return 1
    prompt = build_digest_prompt(
        timeline_text=timeline_text,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
        genre_rules_text=genre_rules_text,
        scene_markers=scene_doc,
        target_minutes=target_minutes,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt, encoding="utf-8")
    print(f"Generated digest prompt: {out_path}")
    print(f"  visual segments : {len(visual_segments)}")
    print(f"  subtitles       : {len(subtitles)}")
    print(f"  scene markers   : {len(scene_doc.scenes) if scene_doc else 0}")
    return 0


def _run_story(args) -> int:
    style_path = _resolve_optional(args.style)
    out_path = args.out.expanduser().resolve()
    syn_path = _resolve_optional(args.synopsis)
    digest_path = _resolve_optional(args.plot_digest)

    if style_path is None:
        print("Error: --style is required in story mode", file=sys.stderr)
        return 1
    if not style_path.exists():
        print(f"Error: Style file not found: {style_path}", file=sys.stderr)
        return 1
    if syn_path is not None and not syn_path.exists():
        print(f"Error: Synopsis file not found: {syn_path}", file=sys.stderr)
        return 1

    style_raw = _read_text(style_path)
    style_meta, style_text = parse_style_frontmatter(style_raw)
    chars_per_minute = int(style_meta.get("chars_per_minute", 250))
    synopsis_text = _read_text(syn_path) if syn_path else None

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
        visual_path = _resolve_optional(args.visual_segments)
        subs_path = _resolve_optional(args.subtitles_txt)
        if visual_path is None or subs_path is None:
            print("Error: --visual-segments and --subtitles-txt are required when --plot-digest is not provided",
                  file=sys.stderr)
            return 1
        if not visual_path.exists() or not subs_path.exists():
            print("Error: Stage 1 inputs not found", file=sys.stderr)
            return 1
        visual_segments = load_visual_segments(visual_path)
        subtitles = load_subtitles(subs_path)
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
        if args.outline:
            return _run_outline(args)
        if args.digest:
            return _run_digest(args)
        return _run_story(args)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
