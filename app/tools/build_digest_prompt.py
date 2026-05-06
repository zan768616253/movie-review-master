"""Build a Pass 1 prompt for plot digest extraction (two-pass workflow).

This tool generates a comprehension-focused prompt designed to be pasted
into an LLM (Gemini / DeepSeek / Qwen). The LLM produces a structured
plot digest that is then fed into build_story_prompt.py in digest mode
(Pass 2) for style-transferred script generation.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from app.pipeline.common.script_contract import load_visual_segments
from app.tools.build_story_prompt import (
    _read_text,
    load_subtitles,
    render_timeline,
)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-digest-prompt",
        description="Build a Pass 1 prompt for plot digest extraction.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--visual-segments", type=Path, required=True,
                        help="Stage 0 visual_segments.json.")
    parser.add_argument("--subtitles-txt", type=Path, required=True,
                        help="Stage 1 subtitles.txt.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output path for the digest prompt text.")
    parser.add_argument("--movie-title", default="",
                        help="Movie title for prompt framing.")
    parser.add_argument("--synopsis", type=Path,
                        help="Optional synopsis markdown.")
    parser.add_argument("--target-minutes", type=float, default=12.0,
                        help="Target review script length in minutes.")
    return parser


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

    # --- Task description ---
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

    # --- Synopsis ---
    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            f"# Synopsis for {movie_label}\n"
            "Use this as authoritative context for character names, relationships, "
            "and overall story arc.\n"
            "<<<SYNOPSIS_START>>>\n"
            f"{synopsis_text.strip()}\n"
            "<<<SYNOPSIS_END>>>"
        )

    # --- Timeline ---
    sections.append(
        "# Chronological Movie Timeline\n"
        "This timeline contains VISUAL segments (what happens on screen) and "
        "SUBTITLE segments (what characters say). Read it carefully to "
        "reconstruct the full movie.\n"
        "<<<MOVIE_TIMELINE_START>>>\n"
        f"{timeline_text.strip()}\n"
        "<<<MOVIE_TIMELINE_END>>>"
    )

    # --- Output format ---
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
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    visual_segments_path = args.visual_segments.expanduser().resolve()
    subtitles_txt_path = args.subtitles_txt.expanduser().resolve()
    out_path = args.out.expanduser().resolve()
    synopsis_path = (
        args.synopsis.expanduser().resolve() if args.synopsis else None
    )

    try:
        if not visual_segments_path.exists():
            raise FileNotFoundError(
                f"Visual segments not found: {visual_segments_path}"
            )
        if not subtitles_txt_path.exists():
            raise FileNotFoundError(
                f"Subtitles not found: {subtitles_txt_path}"
            )
        if synopsis_path is not None and not synopsis_path.exists():
            raise FileNotFoundError(f"Synopsis not found: {synopsis_path}")

        synopsis_text = _read_text(synopsis_path) if synopsis_path else None
        visual_segments = load_visual_segments(visual_segments_path)
        subtitles = load_subtitles(subtitles_txt_path)

        orig_vis = len(visual_segments)
        orig_sub = len(subtitles)

        timeline_text = render_timeline(visual_segments, subtitles)
        if not timeline_text.strip():
            raise ValueError(
                "The merged movie timeline is empty after filtering"
            )

        prompt_text = build_digest_prompt(
            timeline_text=timeline_text,
            movie_title=args.movie_title,
            synopsis_text=synopsis_text,
            target_minutes=args.target_minutes,
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(prompt_text, encoding="utf-8")
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    vis_dropped = orig_vis - len(visual_segments)
    sub_dropped = orig_sub - len(subtitles)
    print(f"Generated digest prompt: {out_path}")
    print(f"  visual segments : {len(visual_segments)} (dropped {vis_dropped} noise)")
    print(f"  subtitles       : {len(subtitles)} (dropped {sub_dropped} noise)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
