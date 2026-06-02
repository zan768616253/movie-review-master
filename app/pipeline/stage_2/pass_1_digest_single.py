"""Pass 1 single-mode digest prompt builder.

When ``scene_markers`` is provided, the digest is required to be organized by
scene with strict per-tag beat targets (the recommended path that pre-shapes
the digest for the niu-shu act-balance invariant in styles/niu-shu.md §4.0).

Without scene markers, falls back to the legacy flat "30-50 beats in
chronological order" structure for backward compatibility.
"""

from __future__ import annotations

from app.pipeline.stage_2.scene_markers import SceneMarkersDocument

# Series carryover instruction, appended to the digest output when the harness
# requests it (every series episode). Harvested into series_context.md and
# injected as background into the next episode.
_CARRYOVER_SECTION = (
    "## 承上启下 (Continuity Carryover) — 写给下一集\n"
    "用 3-5 句中文总结本集结束时的故事状态：主要角色各自的处境、尚未解决的悬念、"
    "以及留给下一集的钩子。这是观众进入下一集前必须记住的内容。"
    "（这一段是给系列下一集用的背景，不需要镜头号 visual:NNN。）"
)

# Per-tag beat targets — these are the act-balance safeguards.
_ACT_BEAT_TARGETS: tuple[tuple[str, str], ...] = (
    ("HOOK",       "1-2"),
    ("SETUP",      "1-2"),
    ("ESCALATION", "2-3"),
    ("CLIMAX",     "4-6"),
    ("RESOLUTION", "2-3"),
    ("CLOSING",    "1"),
)


def _scene_anchored_beats_section(scene_markers: SceneMarkersDocument) -> str:
    targets_table = "\n".join(
        f"- `{tag}`: {beats} beats per scene" for tag, beats in _ACT_BEAT_TARGETS
    )

    glossary_lines = "\n".join(
        f"- {entry.get('original_name', '?')}: {entry.get('role', '?')} "
        f"(first seen in {entry.get('first_seen_scene', '?')})"
        for entry in scene_markers.character_glossary
    ) or "- (none provided)"

    scene_lines = "\n".join(
        f"- {s.id} [{s.act_tag}] {s.visual_id_range[0]}–{s.visual_id_range[1]}: {s.label}"
        for s in scene_markers.scenes
    )

    return (
        "## 角色表 (Character Table) — already supplied\n"
        "The Pass 0 character glossary below is authoritative for names. Use it; do not invent "
        "new characters or rename existing ones in the digest:\n"
        f"{glossary_lines}\n\n"
        "## 剧情脉络 (Plot Beats) — organize BY SCENE\n"
        "Pass 0 has already identified the scene structure. Write beats GROUPED UNDER each scene's "
        "id, in scene order. Every scene listed below must have at least one beat — no scene "
        "may be skipped, because every scene's footage exists in the timeline.\n\n"
        "**Per-tag beat targets (HARD — count your beats against these):**\n"
        f"{targets_table}\n\n"
        "Higher beat counts on CLIMAX-tagged scenes are mandatory; this is the scaffolding that lets "
        "the downstream story script keep ACT 3 longer than ACT 2 (the act-balance invariant in "
        "`styles/niu-shu.md` §4.0). Compress SETUP brutally; linger on CLIMAX.\n\n"
        "**For EACH beat under a scene:**\n"
        "- 镜头: Comma-separated visual_segment IDs from THAT scene's `visual_id_range` ONLY "
        "(e.g. `visual:031, visual:033-035`). REQUIRED. Do not cite IDs outside the scene.\n"
        "- 事件: What happens (2-3 sentences). Describe ONLY what the cited segments show.\n"
        "- 因果: Why this happens / what it causes.\n"
        "- 台词: Key dialogue if any (quote verbatim).\n"
        "- 情绪: Emotional register.\n\n"
        "## Scene list (write beats under each, in order):\n"
        f"{scene_lines}"
    )


def build_digest_prompt(
    *,
    timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_rules_text: str | None = None,
    scene_markers: SceneMarkersDocument | None = None,
    prior_context_text: str | None = None,
    request_carryover: bool = False,
    target_minutes: float = 12.0,
) -> str:
    """Assemble the Pass 1 digest prompt.

    When ``scene_markers`` is provided, the digest is required to be organized by scene with
    strict per-tag beat targets (recommended path). Without scene markers, the legacy flat
    "30-50 beats in chronological order" structure is used (backward compat).

    Series support (both default to off, so movie prompts are unchanged):

    - ``prior_context_text`` — "story so far" from earlier episodes, injected as
      no-footage background (episodes ≥ 2).
    - ``request_carryover`` — when True, append the ``## 承上启下`` instruction so the
      digest ends with a short summary the harness harvests for the next episode.
    """
    movie_label = movie_title.strip() or "Unknown movie"
    use_scenes = scene_markers is not None and len(scene_markers.scenes) > 0

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

    if prior_context_text is not None and prior_context_text.strip():
        sections.append(
            "# Previously in the series\n"
            "Background from earlier episodes. Use it ONLY to recognize returning characters "
            "(keep their established names) and to understand ongoing threads. These events are "
            "NOT in this episode's timeline — do NOT create beats for them and do NOT cite footage "
            "(visual:NNN) for them. Your digest covers THIS episode only.\n"
            "<<<SERIES_SO_FAR_START>>>\n"
            f"{prior_context_text.strip()}\n"
            "<<<SERIES_SO_FAR_END>>>"
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

    if use_scenes:
        output_format = (
            f"# Output Format: Plot Digest for {movie_label}\n"
            "Write the entire digest in Chinese. Be detailed — the reviewer cannot "
            "watch the movie, so your digest is their only source.\n\n"
            + _scene_anchored_beats_section(scene_markers)
            + "\n\n"
            "## 权力结构 (Power Map)\n"
            "Describe who controls what, who deceives whom, and how power shifts.\n\n"
            "## 名场面 (Reviewable Moments) — 10-15 entries\n"
            "Movie-reviewer gold: striking images, ironic situations, satisfying revenge, "
            "shocking reveals, action choreography, emotional gut-punches. For each, list "
            "supporting `镜头: visual:NNN` ids and 2-4 sentences of vivid detail.\n\n"
            "## 核心矛盾 (Core Conflict & Themes)\n"
            "- What is this movie really about? (1-2 sentences)\n"
            "- What is the central irony or contradiction?\n\n"
            "## 结局 (Full Ending)\n"
            "Describe the climax resolution, every main character's final fate, and the "
            "emotional aftertaste."
        )
    else:
        # Legacy structure preserved for backward compat (no scene markers supplied).
        output_format = (
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

    if request_carryover:
        output_format = output_format + "\n\n" + _CARRYOVER_SECTION

    sections.append(output_format)
    return "\n\n".join(sections).rstrip() + "\n"
