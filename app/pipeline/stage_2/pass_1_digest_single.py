"""Pass 1 single-mode digest prompt builder.

Today's behaviour: produces a chronological digest prompt from the full
timeline. Task 7 of the multi-pass plan adds scene-marker awareness and
act-weighted beat targets without changing the import path.
"""

from __future__ import annotations


def build_digest_prompt(
    *,
    timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_rules_text: str | None = None,
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

    if genre_rules_text is not None and genre_rules_text.strip():
        sections.append(
            "# Genre focus\n"
            "Read this before the timeline. It tells you which beats deserve "
            "extra detail in the digest and which can be compressed.\n"
            "<<<GENRE_RULES_START>>>\n"
            f"{genre_rules_text.strip()}\n"
            "<<<GENRE_RULES_END>>>"
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
        "- 镜头: Comma-separated visual_segment IDs from the timeline that show this beat "
        "(e.g. `visual:031, visual:033-035`). REQUIRED. The reviewer uses these IDs to ground "
        "every sentence — a beat without 镜头 cannot be safely retold.\n"
        "- 事件: What happens (2-3 sentences, vivid and specific). Describe ONLY what the cited "
        "visual segments actually show; do not extrapolate beyond them.\n"
        "- 因果: Why this happens / what it causes (the causal chain)\n"
        "- 台词: Key dialogue if any (quote the most impactful lines verbatim)\n"
        "- 情绪: Emotional register (tension / humor / horror / tenderness / etc.)\n\n"
        "IMPORTANT: Be detailed enough that someone who has never seen the movie "
        "can retell the FULL story. Each major scene transition should be a "
        "separate beat. Do NOT merge multiple scenes into one vague beat. "
        "If a stretch of the timeline has no clear footage, SKIP it rather than inventing a beat.\n\n"
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
        "For each moment, include the supporting visual_segment IDs (镜头: visual:NNN, ...) "
        "followed by 2-4 sentences of vivid detail describing ONLY what those segments show.\n\n"
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
