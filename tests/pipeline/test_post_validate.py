from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.stage_2.post_validate import (
    PostValidationReport,
    validate_script,
)
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument


def _make_scene(scene_id: str, vid_start: str, vid_end: str) -> SceneMarker:
    return SceneMarker(
        id=scene_id, label="x", act_tag="SETUP",
        visual_id_range=(vid_start, vid_end),
        time_range=("00:00:00.000", "00:00:10.000"),
        hook="x",
    )


def _scene_doc() -> SceneMarkersDocument:
    return SceneMarkersDocument(
        character_glossary=[],
        scenes=[
            _make_scene("scene:01", "visual:001", "visual:010"),
            _make_scene("scene:02", "visual:011", "visual:020"),
        ],
    )


def _visual_ids(ids: list[str]) -> set[str]:
    return set(ids)


def test_clean_script_produces_zero_flags() -> None:
    script = (
        "<refs>visual:001</refs>\n"
        "故事开场，主角进入校园。\n"
        "\n"
        "<refs>visual:003-005</refs>\n"
        "他遇到了里香。\n"
    )
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids([f"visual:{i:03d}" for i in range(1, 21)]),
    )
    assert isinstance(report, PostValidationReport)
    assert report.total_sentences == 2
    assert report.flagged == []


def test_flags_sentence_with_missing_refs_tag() -> None:
    script = "<refs>visual:001</refs>\n故事开场。\n这一句没有 refs。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids(["visual:001"]),
    )
    flagged_issues = [f.issue for f in report.flagged]
    assert any("missing <refs>" in issue.lower() for issue in flagged_issues)


def test_flags_ref_to_non_existent_visual_id() -> None:
    script = "<refs>visual:999</refs>\n这一句引用了不存在的 ID。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids(["visual:001"]),
    )
    assert len(report.flagged) == 1
    assert "visual:999" in report.flagged[0].issue
    assert "not in visual_segments" in report.flagged[0].issue.lower()


def test_flags_ref_outside_any_scene_visual_id_range() -> None:
    # visual:030 exists but is outside both scenes' ranges (which are 001-010 and 011-020).
    script = "<refs>visual:030</refs>\n这一句的 ID 在所有 scene 之外。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids([f"visual:{i:03d}" for i in range(1, 31)]),
    )
    assert len(report.flagged) == 1
    assert "scene" in report.flagged[0].issue.lower()


def test_range_expansion_recognises_dash_form() -> None:
    # visual:003-005 should expand to 003, 004, 005 and all be checked.
    script = "<refs>visual:003-005</refs>\n这一段引用了一个范围。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids([f"visual:{i:03d}" for i in range(1, 11)]),
    )
    assert report.flagged == []


def test_recap_sentinel_sentences_are_not_flagged() -> None:
    """A series episode opens with a [RECAP] block whose sentences cite the
    `recap` sentinel (footage comes from a prior episode). These are
    intentionally ungrounded and must not be flagged."""
    script = (
        "[RECAP]\n"
        "<refs>recap</refs>\n"
        "上一集，主角发现自己被诅咒缠身。\n"
        "<refs>recap</refs>\n"
        "而反派的真身仍未现身。\n"
        "[ACT 1 - SETUP]\n"
        "<refs>visual:001</refs>\n"
        "本集开场。\n"
    )
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids([f"visual:{i:03d}" for i in range(1, 11)]),
    )
    assert report.total_sentences == 3
    assert report.flagged == []


def test_naked_recap_sentence_without_sentinel_is_still_flagged() -> None:
    """Dropping the sentinel entirely is an error — recap prose with no <refs>
    at all is still flagged so the operator cannot silently lose grounding."""
    script = "[RECAP]\n上一集发生了很多事。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids(["visual:001"]),
    )
    assert any("missing <refs>" in f.issue.lower() for f in report.flagged)


def test_report_writes_json_file_with_expected_schema(tmp_path: Path) -> None:
    script = "<refs>visual:999</refs>\n这一句引用了不存在的 ID。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids(["visual:001"]),
    )
    out = tmp_path / "hallucination_report.json"
    report.write_json(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["total_sentences"] == 1
    assert len(payload["flagged"]) == 1
    flagged = payload["flagged"][0]
    assert "line" in flagged and "sentence" in flagged and "refs" in flagged and "issue" in flagged
