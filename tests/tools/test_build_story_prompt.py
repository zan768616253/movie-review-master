from __future__ import annotations

import json

from pathlib import Path

from app.tools.build_story_prompt import (
    build_prompt,
    build_timeline_entries,
    main,
    render_timeline,
)


def test_build_timeline_entries_interleaves_visuals_and_subtitles() -> None:
    visual_segments = [
        {
            "id": "visual:001",
            "start": "00:00:00.000",
            "end": "00:00:05.000",
            "summary": "the hero enters the warehouse",
            "ocr_text": "",
            "characters": ["Hero"],
        },
        {
            "id": "visual:002",
            "start": "00:00:08.000",
            "end": "00:00:11.000",
            "summary": "the metal door slams shut",
            "ocr_text": "EXIT",
            "characters": [],
        },
    ]
    subtitles = [
        {"start": 1.5, "end": 2.1, "text": "有人来了", "speaker": None, "style": None},
        {"start": 8.0, "end": 8.8, "text": "快跑", "speaker": "Boss", "style": None},
    ]

    rendered = [entry.render() for entry in build_timeline_entries(visual_segments, subtitles)]

    assert rendered == [
        "[VISUAL 00:00:00.000 -> 00:00:05.000] visual:001 | the hero enters the warehouse | characters: Hero",
        "[SUBTITLE 00:00:01.500 -> 00:00:02.100] 有人来了",
        "[VISUAL 00:00:08.000 -> 00:00:11.000] visual:002 | the metal door slams shut | on-screen text: EXIT",
        "[SUBTITLE 00:00:08.000 -> 00:00:08.800] Boss: 快跑",
    ]


def test_build_prompt_emphasizes_deep_style_transfer() -> None:
    prompt = build_prompt(
        style_text="# Demo Style\nFast, sharp, and judgmental.",
        timeline_text="[VISUAL 00:00:00.000 -> 00:00:02.000] visual:001 | opening image",
        movie_title="Demo Movie",
        synopsis_text="A criminal conspiracy traps the protagonist.",
    )

    assert "Do not merely borrow wording, catchphrases" in prompt
    assert "soul: narrator mindset, value system, pace, rhythm, humor" in prompt
    assert "Write one complete script for Demo Movie" in prompt
    assert "best high-level guide to plot continuity, character identity, relationships, and motive" in prompt
    assert "Treat this synopsis as authoritative high-level context" in prompt
    assert "<<<STYLE_RULEBOOK_START>>>" in prompt
    assert "<<<SYNOPSIS_START>>>" in prompt
    assert "<<<MOVIE_TIMELINE_START>>>" in prompt
    assert "- Output only the final script." in prompt
    assert "- No JSON." in prompt


def test_render_timeline_normalizes_multiline_text() -> None:
    visual_segments = [
        {
            "start": "00:00:00.000",
            "end": "00:00:03.000",
            "summary": "hero looks up\nand freezes",
            "ocr_text": "warning\nzone",
            "characters": ["Hero", "Guard"],
        }
    ]
    subtitles = [{"start": 0.8, "end": 1.2, "text": "别动\n马上停下", "speaker": None, "style": None}]

    timeline = render_timeline(visual_segments, subtitles)

    assert "hero looks up / and freezes" in timeline
    assert "on-screen text: warning / zone" in timeline
    assert "别动 / 马上停下" in timeline


def test_main_writes_prompt_file(tmp_path: Path) -> None:
    style_path = tmp_path / "demo-style.md"
    style_path.write_text("# Demo Style\nUse hard hooks.\n", encoding="utf-8")

    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(
        json.dumps(
            [
                {
                    "start": "00:00:00.000",
                    "end": "00:00:04.000",
                    "summary": "a woman opens a hidden door",
                    "ocr_text": "",
                    "characters": ["Woman"],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    subtitles_json_path = tmp_path / "subtitles.json"
    subtitles_json_path.write_text(
        json.dumps(
            [{"start": 1.0, "end": 2.0, "text": "门后有人", "speaker": None, "style": None}],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    synopsis_path = tmp_path / "synopsis.md"
    synopsis_path.write_text("A hidden family secret drives the plot.", encoding="utf-8")

    output_path = tmp_path / "story_prompt.txt"
    exit_code = main(
        [
            "--style",
            str(style_path),
            "--visual-segments",
            str(visual_segments_path),
            "--subtitles-json",
            str(subtitles_json_path),
            "--synopsis",
            str(synopsis_path),
            "--movie-title",
            "Secret Door",
            "--out",
            str(output_path),
        ]
    )

    assert exit_code == 0
    written = output_path.read_text(encoding="utf-8")
    assert "Write one complete script for Secret Door" in written
    assert "A hidden family secret drives the plot." in written
    assert "a woman opens a hidden door" in written
    assert "门后有人" in written
