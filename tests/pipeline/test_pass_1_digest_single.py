from __future__ import annotations

from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument


def _make_scene(scene_id: str, act_tag: str, vid_start: str, vid_end: str) -> SceneMarker:
    return SceneMarker(
        id=scene_id, label="x", act_tag=act_tag,
        visual_id_range=(vid_start, vid_end),
        time_range=("00:00:00.000", "00:00:01.000"),
        hook="x",
    )


def test_digest_prompt_without_scene_markers_uses_legacy_flat_structure() -> None:
    prompt = build_digest_prompt(
        timeline_text="[VISUAL ...] visual:001 | x",
        movie_title="Demo",
    )
    assert "30-50" in prompt or "30 to 50" in prompt
    assert "Plot Beats" in prompt or "剧情脉络" in prompt


def test_digest_prompt_with_scene_markers_uses_scene_structure_and_act_targets() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[
            {"original_name": "Hero", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        scenes=[
            _make_scene("scene:01", "HOOK", "visual:001", "visual:010"),
            _make_scene("scene:02", "SETUP", "visual:011", "visual:030"),
            _make_scene("scene:03", "CLIMAX", "visual:031", "visual:050"),
        ],
    )
    prompt = build_digest_prompt(
        timeline_text="[VISUAL ...] visual:001 | x",
        movie_title="Demo",
        scene_markers=doc,
    )
    assert "HOOK" in prompt and "1-2" in prompt
    assert "CLIMAX" in prompt and "4-6" in prompt
    assert "scene:01" in prompt and "scene:02" in prompt and "scene:03" in prompt
    assert "Hero" in prompt
    assert "30-50" not in prompt


def test_digest_prompt_with_scene_markers_drops_legacy_no_gap_warning_for_skips() -> None:
    """When scene markers are supplied, every scene must be covered — no SKIP."""
    doc = SceneMarkersDocument(
        character_glossary=[],
        scenes=[_make_scene("scene:01", "SETUP", "visual:001", "visual:010")],
    )
    prompt = build_digest_prompt(
        timeline_text="[VISUAL ...] visual:001 | x",
        scene_markers=doc,
    )
    assert "SKIP it rather than inventing" not in prompt
    assert "every scene" in prompt.lower() or "each scene" in prompt.lower()
