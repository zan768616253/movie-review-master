"""Pass 1 chunked-mode digest orchestrator.

Produces three sub-prompts (front-buildup, climax, tail) when invoked, each
delegating to :func:`app.pipeline.stage_2.pass_1_digest_single.build_digest_prompt`
with a filtered scene-markers document and timeline slice. No
prompt-construction logic lives here — only partitioning and orchestration.
"""

from __future__ import annotations

from typing import Mapping

from app.pipeline.common.script_contract import timestamp_to_seconds
from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument
from app.pipeline.stage_2.timeline import render_timeline

CHUNK_ORDER: tuple[str, ...] = ("front", "climax", "tail")

# Which act tags belong to each chunk.
_FRONT_TAGS = frozenset({"HOOK", "SETUP", "ESCALATION"})
_CLIMAX_TAGS = frozenset({"CLIMAX"})
_TAIL_TAGS = frozenset({"RESOLUTION", "CLOSING"})


def partition_scenes(
    scene_markers: SceneMarkersDocument,
) -> tuple[list[SceneMarker], list[SceneMarker], list[SceneMarker]]:
    front: list[SceneMarker] = []
    climax: list[SceneMarker] = []
    tail: list[SceneMarker] = []
    for scene in scene_markers.scenes:
        if scene.act_tag in _FRONT_TAGS:
            front.append(scene)
        elif scene.act_tag in _CLIMAX_TAGS:
            climax.append(scene)
        elif scene.act_tag in _TAIL_TAGS:
            tail.append(scene)
        else:  # pragma: no cover — scene_markers.load enforces tag membership
            raise ValueError(f"unexpected act_tag {scene.act_tag!r} in {scene.id!r}")
    return front, climax, tail


def _visual_id_to_int(visual_id: str) -> int:
    return int(visual_id.split(":", 1)[1])


def _filter_visuals_to_scenes(
    visual_segments: list[dict[str, object]],
    scenes: list[SceneMarker],
) -> list[dict[str, object]]:
    if not scenes:
        return []
    allowed_ranges = [
        (_visual_id_to_int(s.visual_id_range[0]), _visual_id_to_int(s.visual_id_range[1]))
        for s in scenes
    ]
    out: list[dict[str, object]] = []
    for index, seg in enumerate(visual_segments):
        seg_id = str(seg.get("id") or f"visual:{index + 1:03d}")
        seg_num = _visual_id_to_int(seg_id)
        if any(lo <= seg_num <= hi for lo, hi in allowed_ranges):
            out.append(seg)
    return out


def _filter_subtitles_to_time_span(
    subtitles: list[dict[str, object]],
    scenes: list[SceneMarker],
) -> list[dict[str, object]]:
    if not scenes:
        return []
    spans = [
        (timestamp_to_seconds(s.time_range[0]), timestamp_to_seconds(s.time_range[1]))
        for s in scenes
    ]
    out: list[dict[str, object]] = []
    for sub in subtitles:
        raw = sub["start"]
        start_s = float(raw) if isinstance(raw, (int, float)) else timestamp_to_seconds(str(raw))
        if any(lo <= start_s <= hi for lo, hi in spans):
            out.append(sub)
    return out


def build_chunked_digest_prompts(
    *,
    scene_markers: SceneMarkersDocument,
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_rules_text: str | None = None,
    prior_context_text: str | None = None,
    request_carryover: bool = False,
    target_minutes: float = 12.0,
) -> dict[str, str]:
    """Build the three chunked Pass 1 prompts. Returns a dict keyed by CHUNK_ORDER.

    ``prior_context_text`` (series episodes ≥ 2) is threaded into every chunk so
    returning characters stay consistent. ``request_carryover`` only attaches the
    ``承上启下`` instruction to the ``tail`` chunk, so the concatenated digest ends
    with exactly one carryover section.
    """
    front, climax, tail = partition_scenes(scene_markers)
    chunks: list[tuple[str, list[SceneMarker]]] = [
        ("front", front), ("climax", climax), ("tail", tail),
    ]
    out: dict[str, str] = {}
    for label, scenes in chunks:
        chunk_doc = SceneMarkersDocument(
            character_glossary=scene_markers.character_glossary,
            scenes=scenes,
        )
        chunk_visuals = _filter_visuals_to_scenes(visual_segments, scenes)
        chunk_subtitles = _filter_subtitles_to_time_span(subtitles, scenes)
        chunk_timeline = render_timeline(chunk_visuals, chunk_subtitles) if scenes else ""
        chunk_movie_title = f"{movie_title} (chunk: {label})" if movie_title else f"(chunk: {label})"
        out[label] = build_digest_prompt(
            timeline_text=chunk_timeline,
            movie_title=chunk_movie_title,
            synopsis_text=synopsis_text,
            genre_rules_text=genre_rules_text,
            scene_markers=chunk_doc,
            prior_context_text=prior_context_text,
            request_carryover=request_carryover and label == "tail",
            target_minutes=target_minutes,
        )
    return out


def concatenate_digest_chunks(replies: Mapping[str, str]) -> str:
    """Join the three chunked-digest replies in canonical CHUNK_ORDER."""
    parts: list[str] = []
    for label in CHUNK_ORDER:
        body = replies.get(label, "").strip()
        if body:
            parts.append(body)
    return "\n\n".join(parts) + ("\n" if parts else "")
