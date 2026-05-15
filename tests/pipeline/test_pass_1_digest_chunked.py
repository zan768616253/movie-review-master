from __future__ import annotations

from app.pipeline.stage_2.pass_1_digest_chunked import (
    CHUNK_ORDER,
    build_chunked_digest_prompts,
    concatenate_digest_chunks,
    partition_scenes,
)
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument


def _make_scene(scene_id: str, act_tag: str, vid_start: str, vid_end: str) -> SceneMarker:
    return SceneMarker(
        id=scene_id, label="x", act_tag=act_tag,
        visual_id_range=(vid_start, vid_end),
        time_range=("00:00:00.000", "00:00:01.000"),
        hook="x",
    )


def test_partition_scenes_groups_by_chunk_order() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[],
        scenes=[
            _make_scene("scene:01", "HOOK",       "visual:001", "visual:005"),
            _make_scene("scene:02", "SETUP",      "visual:006", "visual:015"),
            _make_scene("scene:03", "ESCALATION", "visual:016", "visual:030"),
            _make_scene("scene:04", "CLIMAX",     "visual:031", "visual:050"),
            _make_scene("scene:05", "CLIMAX",     "visual:051", "visual:060"),
            _make_scene("scene:06", "RESOLUTION", "visual:061", "visual:070"),
            _make_scene("scene:07", "CLOSING",    "visual:071", "visual:075"),
        ],
    )

    front, climax, tail = partition_scenes(doc)
    assert [s.id for s in front] == ["scene:01", "scene:02", "scene:03"]
    assert [s.id for s in climax] == ["scene:04", "scene:05"]
    assert [s.id for s in tail] == ["scene:06", "scene:07"]


def test_build_chunked_digest_prompts_returns_three_prompts_each_with_chunk_label() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[
            {"original_name": "Hero", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        scenes=[
            _make_scene("scene:01", "SETUP",  "visual:001", "visual:010"),
            _make_scene("scene:02", "CLIMAX", "visual:011", "visual:020"),
            _make_scene("scene:03", "CLOSING", "visual:021", "visual:025"),
        ],
    )
    visual_segments = [
        {"id": f"visual:{i:03d}", "start": f"00:00:{i:02d}.000",
         "end": f"00:00:{i+1:02d}.000", "summary": "x",
         "ocr_text": "", "characters": []}
        for i in range(1, 26)
    ]

    prompts = build_chunked_digest_prompts(
        scene_markers=doc, visual_segments=visual_segments, subtitles=[],
        movie_title="Demo",
    )
    assert set(prompts.keys()) == set(CHUNK_ORDER)
    # Each chunk's prompt contains its own scene ids and not other chunks'.
    assert "scene:01" in prompts["front"]
    assert "scene:02" not in prompts["front"]
    assert "scene:02" in prompts["climax"]
    assert "scene:03" not in prompts["climax"]
    # Character glossary appears in every chunk (no name drift).
    for prompt in prompts.values():
        assert "Hero" in prompt
    # Per-tag beat targets present in every chunk (delegated to single-mode builder).
    for prompt in prompts.values():
        assert "CLIMAX" in prompt and "4-6" in prompt


def test_concatenate_digest_chunks_preserves_chunk_order() -> None:
    replies = {
        "tail":   "## tail content\n",
        "front":  "## front content\n",
        "climax": "## climax content\n",
    }
    out = concatenate_digest_chunks(replies)
    front_pos = out.index("front content")
    climax_pos = out.index("climax content")
    tail_pos = out.index("tail content")
    assert front_pos < climax_pos < tail_pos
