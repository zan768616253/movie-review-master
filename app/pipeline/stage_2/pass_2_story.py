"""Pass 2 story script prompt builder.

Produces the prompt that asks the LLM to write the styled retelling script
from either the raw timeline (single-pass mode) or the plot digest
(two-pass mode).
"""

from __future__ import annotations


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


def _recap_directive() -> str:
    return (
        "# Episode recap opening (REQUIRED — this is a series episode)\n"
        "This is NOT the first episode, so open with a [RECAP] block instead of [HOOK]:\n"
        "- In 2-4 short sentences, remind the viewer where the story left off, drawn from the "
        "'Previously in the series' context above. Speak in the narrator's voice — a vivid bridge, "
        "not a dry summary.\n"
        "- End the recap with ONE forward-pull line that teases what THIS episode is about.\n"
        "- The recap describes PRIOR episodes, which have NO footage in this episode. So every recap "
        "sentence is tagged with the sentinel `<refs>recap</refs>` on its own line (NOT a visual:NNN "
        "id). The editor will cut prior-episode footage there.\n"
        "- Example:\n"
        "```\n"
        "[RECAP]\n"
        "<refs>recap</refs>\n"
        "上一集，主角发现自己被诅咒缠身。\n"
        "<refs>recap</refs>\n"
        "而真正的敌人，才刚刚现身。\n"
        "```\n"
        "- After [RECAP], continue with [ACT 1 - ...] and the rest of the structure as normal. Do "
        "NOT also write a separate [HOOK] block — the recap is this episode's opener.\n"
        "- Every NON-recap sentence still obeys the hard grounding rule below (real visual:NNN ids)."
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
    prior_context_text: str | None = None,
    target_minutes: float | None = None,
    chars_per_minute: int = 250,
) -> str:
    if timeline_text is None and digest_text is None:
        raise ValueError("Either timeline_text or digest_text must be provided")

    use_digest = digest_text is not None
    recap_mode = bool(prior_context_text and prior_context_text.strip())
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

    if recap_mode:
        sections.append(
            "# Previously in the series (recap source)\n"
            "Use this to write the [RECAP] opening. It summarizes earlier episodes. Do NOT fold these "
            "prior events into this episode's main narration — they have no footage here; they belong "
            "only in the [RECAP] block (tagged <refs>recap</refs>).\n"
            "<<<SERIES_SO_FAR_START>>>\n"
            f"{prior_context_text.strip()}\n"
            "<<<SERIES_SO_FAR_END>>>"
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

    if recap_mode:
        sections.append(_recap_directive())

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

    opener_example = "[TITLE], [RECAP], [ACT 1 - SETUP]" if recap_mode else "[TITLE], [HOOK], [ACT 1 - SETUP]"
    sections.append(
        "# Output requirements\n"
        "- Output only the final script.\n"
        "- Use the act structure headers defined in the Style Rulebook "
        f"(e.g. {opener_example}, etc.). No additional sub-headings beyond those.\n"
        "- Every narration sentence is preceded by its own <refs>...</refs> line per the grounding requirement.\n"
        "- No JSON.\n"
        "- No bullet points inside act prose.\n"
        "- No analysis before or after the script.\n"
        "- Keep the script in the primary language implied by the style file unless the source material clearly requires another language."
    )

    return "\n\n".join(sections).rstrip() + "\n"
