from __future__ import annotations

from app.pipeline.stage_2.pass_0_outline import (
    build_outline_prompt,
    render_thin_timeline,
)


def test_thin_timeline_drops_visual_summary_but_keeps_id_time_chars_ocr() -> None:
    segments = [
        {
            "id": "visual:001",
            "start": "00:00:00.000",
            "end": "00:00:05.000",
            "summary": "the hero enters the warehouse — VERY LONG PROSE",
            "ocr_text": "EXIT",
            "characters": ["Hero", "Boss"],
        },
    ]
    subtitles = [
        {"start": 1.5, "end": 2.1, "text": "有人来了", "speaker": "Boss"},
    ]
    rendered = render_thin_timeline(segments, subtitles)

    # The summary text MUST NOT appear in the thin view.
    assert "VERY LONG PROSE" not in rendered
    # ID, time, characters, OCR all preserved.
    assert "visual:001" in rendered
    assert "00:00:00.000" in rendered
    assert "Hero" in rendered and "Boss" in rendered
    assert "EXIT" in rendered
    # Subtitles still appear (they are already compact).
    assert "有人来了" in rendered


def test_thin_timeline_keeps_every_visual_segment() -> None:
    segments = [
        {"id": f"visual:{i:03d}", "start": f"00:00:{i:02d}.000", "end": f"00:00:{i+1:02d}.000",
         "summary": "x", "ocr_text": "", "characters": []}
        for i in range(10)
    ]
    rendered = render_thin_timeline(segments, [])
    for i in range(10):
        assert f"visual:{i:03d}" in rendered


def test_build_outline_prompt_includes_required_sections_and_act_tags() -> None:
    prompt = build_outline_prompt(
        thin_timeline_text="visual:001 | 00:00:00.000-00:00:05.000 | chars: Hero | ocr: -",
        movie_title="Test Movie",
        synopsis_text="A simple story.",
    )
    # Schema instructions present.
    assert "scene_markers.json" in prompt or "JSON" in prompt
    # All six act-tags documented.
    for tag in ("HOOK", "SETUP", "ESCALATION", "CLIMAX", "RESOLUTION", "CLOSING"):
        assert tag in prompt
    # Hard rules from the spec.
    assert "no gaps" in prompt.lower() or "no overlap" in prompt.lower()
    assert "15" in prompt and "25" in prompt  # 15-25 scenes
    # Movie title threads through.
    assert "Test Movie" in prompt
    # Synopsis is included.
    assert "A simple story." in prompt


def test_build_outline_prompt_works_without_synopsis() -> None:
    prompt = build_outline_prompt(
        thin_timeline_text="visual:001 | 00:00:00.000-00:00:05.000 | chars: - | ocr: -",
        movie_title="Test Movie",
    )
    assert "Test Movie" in prompt
    assert "<<<SYNOPSIS_START>>>" not in prompt
