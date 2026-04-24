import json
import tempfile
from pathlib import Path

from app.pipeline.stage4_video_processor import (
    build_scene_clip_plan,
    load_visual_segments,
    parse_scene_markers,
)


def test_parse_scene_markers_supports_grounded_scene_attributes(tmp_path: Path) -> None:
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        "\n".join(
            [
                "[TITLE] Demo",
                "[SCENE start=00:00:05.000 end=00:00:08.000 source=visual confidence=0.91 evidence=visual:002 characters=\"Yuta|Gojo\"]",
                "[BROLL: 00:00:10.000-00:00:12.000]",
                "旁白",
                "[SCENE source=ungrounded confidence=0.10 evidence=none]",
                "另一段旁白",
            ]
        ),
        encoding="utf-8",
    )

    scenes = parse_scene_markers(script_path)

    assert len(scenes) == 2
    assert scenes[0].marker_source == "visual"
    assert scenes[0].marker_evidence == "visual:002"
    assert scenes[0].marker_characters == ["Yuta", "Gojo"]
    assert scenes[0].broll == [("00:00:10.000", "00:00:12.000")]
    assert scenes[1].is_ungrounded is True


def test_build_scene_clip_plan_adds_handles_and_extends_to_visual_boundary() -> None:
    scene = parse_scene_markers_from_text(
        "[SCENE start=00:00:05.000 end=00:00:08.000 source=visual evidence=visual:002]"
    )[0]
    visual_segments = [
        {
            "id": "visual:001",
            "start": "00:00:01.000",
            "end": "00:00:04.000",
            "summary": "setup",
        },
        {
            "id": "visual:002",
            "start": "00:00:05.000",
            "end": "00:00:09.500",
            "summary": "fight",
        },
    ]

    plan = build_scene_clip_plan(scene, handle_seconds=1.5, visual_segments=visual_segments)

    assert plan is not None
    assert plan.extracted_start == "00:00:03.500"
    assert plan.extracted_end == "00:00:09.500"
    assert plan.pre_handle_s == 1.5
    assert plan.post_handle_s == 1.5


def test_load_visual_segments_assigns_default_ids(tmp_path: Path) -> None:
    visual_path = tmp_path / "visual_segments.json"
    visual_path.write_text(
        json.dumps([{"start": "00:00:01.000", "end": "00:00:02.000", "summary": "a"}]),
        encoding="utf-8",
    )

    segments = load_visual_segments(visual_path)

    assert segments[0]["id"] == "visual:001"


def parse_scene_markers_from_text(text: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "script.txt"
        path.write_text(text, encoding="utf-8")
        return parse_scene_markers(path)