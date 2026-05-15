from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline.stage_2.scene_markers import (
    ACT_TAGS,
    SceneMarker,
    SceneMarkersDocument,
    load_scene_markers,
)


def _write_doc(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "scene_markers.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_act_tags_are_the_six_documented_values() -> None:
    assert ACT_TAGS == ("HOOK", "SETUP", "ESCALATION", "CLIMAX", "RESOLUTION", "CLOSING")


def test_load_scene_markers_parses_a_minimal_valid_document(tmp_path: Path) -> None:
    path = _write_doc(tmp_path, {
        "character_glossary": [
            {"original_name": "乙骨忧太", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        "scenes": [
            {
                "id": "scene:01",
                "label": "校园偶遇",
                "act_tag": "SETUP",
                "visual_id_range": ["visual:001", "visual:031"],
                "time_range": ["00:00:01.201", "00:03:42.500"],
                "hook": "孤独高中生被诅咒纠缠",
            },
        ],
    })
    doc = load_scene_markers(path)
    assert isinstance(doc, SceneMarkersDocument)
    assert len(doc.scenes) == 1
    scene = doc.scenes[0]
    assert isinstance(scene, SceneMarker)
    assert scene.id == "scene:01"
    assert scene.act_tag == "SETUP"
    assert scene.visual_id_range == ("visual:001", "visual:031")
    assert doc.character_glossary[0]["original_name"] == "乙骨忧太"


def test_load_scene_markers_rejects_unknown_act_tag(tmp_path: Path) -> None:
    path = _write_doc(tmp_path, {
        "character_glossary": [],
        "scenes": [
            {
                "id": "scene:01",
                "label": "x",
                "act_tag": "TURNING_POINT",
                "visual_id_range": ["visual:001", "visual:001"],
                "time_range": ["00:00:00.000", "00:00:01.000"],
                "hook": "x",
            },
        ],
    })
    with pytest.raises(ValueError, match="act_tag"):
        load_scene_markers(path)


def test_load_scene_markers_rejects_overlapping_visual_id_ranges(tmp_path: Path) -> None:
    path = _write_doc(tmp_path, {
        "character_glossary": [],
        "scenes": [
            {
                "id": "scene:01", "label": "a", "act_tag": "SETUP",
                "visual_id_range": ["visual:001", "visual:010"],
                "time_range": ["00:00:00.000", "00:01:00.000"], "hook": "a",
            },
            {
                "id": "scene:02", "label": "b", "act_tag": "ESCALATION",
                "visual_id_range": ["visual:008", "visual:020"],
                "time_range": ["00:00:50.000", "00:02:00.000"], "hook": "b",
            },
        ],
    })
    with pytest.raises(ValueError, match="overlap"):
        load_scene_markers(path)


def test_load_scene_markers_rejects_touching_visual_id_ranges(tmp_path: Path) -> None:
    """End of scene:01 == start of scene:02 means the same visual is claimed twice."""
    path = _write_doc(tmp_path, {
        "character_glossary": [],
        "scenes": [
            {
                "id": "scene:01", "label": "a", "act_tag": "SETUP",
                "visual_id_range": ["visual:001", "visual:010"],
                "time_range": ["00:00:00.000", "00:01:00.000"], "hook": "a",
            },
            {
                "id": "scene:02", "label": "b", "act_tag": "ESCALATION",
                "visual_id_range": ["visual:010", "visual:020"],
                "time_range": ["00:01:00.000", "00:02:00.000"], "hook": "b",
            },
        ],
    })
    with pytest.raises(ValueError, match="overlap"):
        load_scene_markers(path)


def test_scenes_by_act_tag_groups_correctly() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[],
        scenes=[
            SceneMarker("scene:01", "a", "SETUP", ("visual:001", "visual:010"), ("00:00:00.000", "00:01:00.000"), "a"),
            SceneMarker("scene:02", "b", "CLIMAX", ("visual:011", "visual:020"), ("00:01:00.000", "00:02:00.000"), "b"),
            SceneMarker("scene:03", "c", "CLIMAX", ("visual:021", "visual:030"), ("00:02:00.000", "00:03:00.000"), "c"),
        ],
    )
    by_tag = doc.scenes_by_act_tag()
    assert [s.id for s in by_tag["CLIMAX"]] == ["scene:02", "scene:03"]
    assert [s.id for s in by_tag["SETUP"]] == ["scene:01"]
