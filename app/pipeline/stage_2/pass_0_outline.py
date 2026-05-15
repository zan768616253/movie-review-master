"""Pass 0 — scene outline prompt + thin-timeline view.

Pass 0 ingests a compressed view of the timeline (the prose ``summary`` field is
dropped per the spec; every other field stays) plus subtitles, and asks the LLM
to produce ``scene_markers.json`` matching the schema in
:mod:`app.pipeline.stage_2.scene_markers`.
"""

from __future__ import annotations

from app.pipeline.common.script_contract import (
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.stage_2.timeline import normalize_inline_text


def _thin_visual_line(index: int, segment: dict[str, object]) -> str:
    seg_id = str(segment.get("id") or f"visual:{index + 1:03d}")
    start = str(segment["start"])
    end = str(segment["end"])
    chars = segment.get("characters") or []
    chars_str = ", ".join(normalize_inline_text(c) for c in chars if normalize_inline_text(c)) or "-"
    ocr = normalize_inline_text(segment.get("ocr_text")) or "-"
    return f"{seg_id} | {start}-{end} | chars: {chars_str} | ocr: {ocr}"


def _thin_subtitle_line(subtitle: dict[str, object]) -> str | None:
    text = normalize_inline_text(subtitle.get("text"))
    if not text:
        return None
    start_raw = subtitle["start"]
    end_raw = subtitle["end"]
    if isinstance(start_raw, (int, float)):
        start = seconds_to_timestamp(float(start_raw))
    else:
        start = str(start_raw)
    if isinstance(end_raw, (int, float)):
        end = seconds_to_timestamp(float(end_raw))
    else:
        end = str(end_raw)
    speaker = normalize_inline_text(subtitle.get("speaker"))
    body = f"{speaker}: {text}" if speaker else text
    return f"SUB | {start}-{end} | {body}"


def render_thin_timeline(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> str:
    """Compact one-line-per-item view, lossless except for the visual `summary`."""
    lines: list[tuple[float, int, str]] = []
    for index, segment in enumerate(visual_segments):
        start_s = timestamp_to_seconds(str(segment["start"]))
        lines.append((start_s, 0, _thin_visual_line(index, segment)))
    for subtitle in subtitles:
        raw = subtitle["start"]
        start_s = float(raw) if isinstance(raw, (int, float)) else timestamp_to_seconds(str(raw))
        thin = _thin_subtitle_line(subtitle)
        if thin is None:
            continue
        lines.append((start_s, 1, thin))
    lines.sort(key=lambda t: (t[0], t[1]))
    return "\n".join(line for _, _, line in lines)


def build_outline_prompt(
    *,
    thin_timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
) -> str:
    """Assemble the Pass 0 prompt that asks the LLM for scene_markers.json."""
    movie_label = movie_title.strip() or "Unknown movie"
    sections: list[str] = []

    sections.append(
        "# Task\n"
        f"You are reading a compressed timeline of the movie {movie_label}. Your job is to "
        "produce a JSON document describing the movie's scene structure — the SCAFFOLDING that a "
        "downstream digester will use to write the plot digest, and that an editor will use to find "
        "footage. Quality of every downstream step depends on the accuracy of this scaffold."
    )

    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            f"# Synopsis for {movie_label}\n"
            "Authoritative for character names, relationships, and overall arc. "
            "May reference off-screen plot points — those are fine here (Pass 0 only); "
            "downstream passes will not invent footage from them.\n"
            "<<<SYNOPSIS_START>>>\n"
            f"{synopsis_text.strip()}\n"
            "<<<SYNOPSIS_END>>>"
        )

    sections.append(
        "# Compressed timeline (thin view)\n"
        "Every visual_segment is represented once. The prose `summary` field has been removed "
        "to save space — use characters, OCR text, and subtitle dialogue to infer what is happening.\n"
        "<<<THIN_TIMELINE_START>>>\n"
        f"{thin_timeline_text.strip()}\n"
        "<<<THIN_TIMELINE_END>>>"
    )

    sections.append(
        "# Output format: scene_markers.json\n"
        "Return ONE JSON object with two keys: `character_glossary` and `scenes`. No prose, no "
        "code fences, no comments.\n\n"
        "## character_glossary (array)\n"
        "One entry per important on-screen character (max 10). Each entry:\n"
        "- `original_name`: the character's name as it appears in the movie\n"
        "- `role`: one of `protagonist | antagonist | ally | victim | mentor | rival | minor`\n"
        "- `first_seen_scene`: the `id` of the scene where they first appear (see scenes below)\n\n"
        "## scenes (array of 15-25 entries)\n"
        "Each entry:\n"
        "- `id`: `scene:NN` (zero-padded sequential, starting at 01)\n"
        "- `label`: one-line Chinese label (max 20 chars)\n"
        "- `act_tag`: EXACTLY one of `HOOK`, `SETUP`, `ESCALATION`, `CLIMAX`, `RESOLUTION`, `CLOSING`\n"
        "- `visual_id_range`: `[\"visual:NNN\", \"visual:MMM\"]` (inclusive, first and last visual_segment in the scene)\n"
        "- `time_range`: `[\"HH:MM:SS.SSS\", \"HH:MM:SS.SSS\"]` (matching the visual_id_range's times)\n"
        "- `hook`: one-line description of why this scene matters\n\n"
        "## Hard rules\n"
        "- Every visual_segment must fall into exactly ONE scene. No gaps. No overlaps.\n"
        "- Exactly one scene tagged `HOOK` — the strongest opening candidate (not necessarily the first scene).\n"
        "- At least 3 scenes tagged `CLIMAX` — the decisive confrontation can span multiple scenes.\n"
        "- 15 to 25 scenes total. Shorter movies get fewer; epics get more.\n"
        "- The act_tag distribution should roughly match: HOOK ~3-5% of runtime, SETUP 15-20%, "
        "ESCALATION 25-30%, CLIMAX 35-40%, RESOLUTION 10-15%, CLOSING 2-4%.\n"
        "- Do NOT invent scenes that have no visual_segments backing them.\n"
        "- Do NOT output anything other than the JSON object."
    )

    return "\n\n".join(sections).rstrip() + "\n"
