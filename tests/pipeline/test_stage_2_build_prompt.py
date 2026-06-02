from __future__ import annotations

import json

from pathlib import Path

from app.pipeline.stage_2_build_prompt import (
    build_digest_prompt,
    build_story_prompt as build_prompt,
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
    assert "Use this synopsis ONLY to look up character names and relationships" in prompt
    assert "synopsis, when provided, is ONLY for clarifying character names and relationships" in prompt
    assert "Grounding requirement" in prompt
    assert "<refs>visual:031, visual:033-035</refs>" in prompt
    assert "DROP that sentence" in prompt
    assert "Every narration sentence is preceded by its own <refs>...</refs> line" in prompt
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


def test_build_prompt_injects_genre_rules_when_provided() -> None:
    prompt = build_prompt(
        style_text="# Demo Style",
        timeline_text="[VISUAL 00:00:00.000 -> 00:00:02.000] visual:001 | opening image",
        movie_title="Demo Movie",
        genre_rules_text="# Action focus\nPrioritize fight choreography over flat scene listing.",
    )

    assert "# Genre focus" in prompt
    assert "<<<GENRE_RULES_START>>>" in prompt
    assert "Prioritize fight choreography" in prompt
    # Genre focus must sit between the style rulebook and the genre example (when present)
    assert prompt.index("<<<STYLE_RULEBOOK_END>>>") < prompt.index("<<<GENRE_RULES_START>>>")


def test_build_prompt_omits_genre_rules_section_when_absent() -> None:
    prompt = build_prompt(
        style_text="# Demo Style",
        timeline_text="[VISUAL 00:00:00.000 -> 00:00:02.000] visual:001 | opening image",
        movie_title="Demo Movie",
    )

    assert "# Genre focus" not in prompt
    assert "<<<GENRE_RULES_START>>>" not in prompt


def test_build_digest_prompt_injects_genre_rules_before_timeline() -> None:
    prompt = build_digest_prompt(
        timeline_text="[VISUAL 00:00:00.000 -> 00:00:02.000] visual:001 | opening image",
        movie_title="Demo Movie",
        genre_rules_text="# Action focus\nDigest must prioritise fight beats.",
    )

    assert "# Genre focus" in prompt
    assert "Digest must prioritise fight beats." in prompt
    assert prompt.index("<<<GENRE_RULES_END>>>") < prompt.index("<<<MOVIE_TIMELINE_START>>>")


def test_main_loads_genre_rules_file(tmp_path: Path) -> None:
    style_path = tmp_path / "demo-style.md"
    style_path.write_text("# Demo Style\n", encoding="utf-8")

    rules_dir = tmp_path / "genres" / "demo-style"
    rules_dir.mkdir(parents=True)
    (rules_dir / "Action.rules.md").write_text(
        "# Action focus\nUNIQUE_RULES_MARKER fight emphasis.\n",
        encoding="utf-8",
    )

    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(
        json.dumps(
            [
                {
                    "start": "00:00:00.000",
                    "end": "00:00:04.000",
                    "summary": "a fight breaks out",
                    "ocr_text": "",
                    "characters": ["Hero"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    subtitles_txt_path = tmp_path / "subtitles.txt"
    subtitles_txt_path.write_text(
        "[00:00:01.000 -> 00:00:02.000] 来啊\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "story_prompt.txt"
    exit_code = main(
        [
            "--style",
            str(style_path),
            "--visual-segments",
            str(visual_segments_path),
            "--subtitles-txt",
            str(subtitles_txt_path),
            "--movie-title",
            "Demo",
            "--genre",
            "Action",
            "--out",
            str(output_path),
        ]
    )

    assert exit_code == 0
    written = output_path.read_text(encoding="utf-8")
    assert "UNIQUE_RULES_MARKER fight emphasis." in written
    assert "<<<GENRE_RULES_START>>>" in written


def test_main_builds_outline_prompt_when_outline_flag_set(tmp_path: Path) -> None:
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(json.dumps([
        {"start": "00:00:00.000", "end": "00:00:04.000", "summary": "x",
         "ocr_text": "", "characters": []}
    ]), encoding="utf-8")
    subtitles_txt_path = tmp_path / "subtitles.txt"
    subtitles_txt_path.write_text("[00:00:01.000 -> 00:00:02.000] hello\n", encoding="utf-8")

    output_path = tmp_path / "outline_prompt.txt"
    rc = main([
        "--outline",
        "--visual-segments", str(visual_segments_path),
        "--subtitles-txt", str(subtitles_txt_path),
        "--out", str(output_path),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    written = output_path.read_text(encoding="utf-8")
    assert "scene_markers.json" in written or "JSON" in written
    assert "CLIMAX" in written  # act-tag inventory must be in the prompt


def test_main_builds_chunked_digest_writes_three_files(tmp_path: Path) -> None:
    # Minimal valid scene_markers.json.
    scene_markers_path = tmp_path / "scene_markers.json"
    scene_markers_path.write_text(json.dumps({
        "character_glossary": [],
        "scenes": [
            {"id": "scene:01", "label": "a", "act_tag": "SETUP",
             "visual_id_range": ["visual:001", "visual:001"],
             "time_range": ["00:00:00.000", "00:00:04.000"], "hook": "a"},
            {"id": "scene:02", "label": "b", "act_tag": "CLIMAX",
             "visual_id_range": ["visual:002", "visual:002"],
             "time_range": ["00:00:04.000", "00:00:08.000"], "hook": "b"},
            {"id": "scene:03", "label": "c", "act_tag": "CLOSING",
             "visual_id_range": ["visual:003", "visual:003"],
             "time_range": ["00:00:08.000", "00:00:12.000"], "hook": "c"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(json.dumps([
        {"id": "visual:001", "start": "00:00:00.000", "end": "00:00:04.000",
         "summary": "x", "ocr_text": "", "characters": []},
        {"id": "visual:002", "start": "00:00:04.000", "end": "00:00:08.000",
         "summary": "y", "ocr_text": "", "characters": []},
        {"id": "visual:003", "start": "00:00:08.000", "end": "00:00:12.000",
         "summary": "z", "ocr_text": "", "characters": []},
    ]), encoding="utf-8")
    subtitles_txt_path = tmp_path / "subtitles.txt"
    subtitles_txt_path.write_text("", encoding="utf-8")

    out_path = tmp_path / "digest_prompt.txt"
    rc = main([
        "--digest", "--chunked",
        "--scene-markers", str(scene_markers_path),
        "--visual-segments", str(visual_segments_path),
        "--subtitles-txt", str(subtitles_txt_path),
        "--out", str(out_path),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    front = tmp_path / "digest_prompt.front.txt"
    climax = tmp_path / "digest_prompt.climax.txt"
    tail = tmp_path / "digest_prompt.tail.txt"
    assert front.is_file() and climax.is_file() and tail.is_file()
    assert "scene:01" in front.read_text(encoding="utf-8")
    assert "scene:02" in climax.read_text(encoding="utf-8")
    assert "scene:03" in tail.read_text(encoding="utf-8")


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

    subtitles_txt_path = tmp_path / "subtitles.txt"
    subtitles_txt_path.write_text(
        "[00:00:01.000 -> 00:00:02.000] 门后有人\n",
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
            "--subtitles-txt",
            str(subtitles_txt_path),
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


def _write_minimal_timeline_inputs(tmp_path: Path) -> tuple[Path, Path]:
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(json.dumps([
        {"id": "visual:001", "start": "00:00:00.000", "end": "00:00:04.000",
         "summary": "x", "ocr_text": "", "characters": []},
    ]), encoding="utf-8")
    subtitles_txt_path = tmp_path / "subtitles.txt"
    subtitles_txt_path.write_text("", encoding="utf-8")
    return visual_segments_path, subtitles_txt_path


def test_main_digest_prior_context_and_carryover(tmp_path: Path) -> None:
    visual_segments_path, subtitles_txt_path = _write_minimal_timeline_inputs(tmp_path)
    prior_path = tmp_path / "prior_context.md"
    prior_path.write_text("第 1 集 回顾：主角发现了诅咒。", encoding="utf-8")

    out_path = tmp_path / "digest_prompt.txt"
    rc = main([
        "--digest",
        "--visual-segments", str(visual_segments_path),
        "--subtitles-txt", str(subtitles_txt_path),
        "--prior-context", str(prior_path),
        "--series-carryover",
        "--out", str(out_path),
        "--movie-title", "Demo EP2",
    ])
    assert rc == 0
    written = out_path.read_text(encoding="utf-8")
    assert "Previously in the series" in written
    assert "第 1 集 回顾：主角发现了诅咒。" in written
    assert "承上启下" in written


def test_main_story_prior_context_emits_recap(tmp_path: Path) -> None:
    style_path = tmp_path / "niu-shu.md"
    style_path.write_text("# Demo Style\nUse hard hooks.\n", encoding="utf-8")
    digest_path = tmp_path / "plot_digest.txt"
    digest_path.write_text("## 剧情脉络\n- beat one\n", encoding="utf-8")
    prior_path = tmp_path / "prior_context.md"
    prior_path.write_text("第 1 集 回顾：黑帮大佬重生回到十六岁。", encoding="utf-8")

    out_path = tmp_path / "story_prompt.txt"
    rc = main([
        "--style", str(style_path),
        "--plot-digest", str(digest_path),
        "--prior-context", str(prior_path),
        "--out", str(out_path),
        "--movie-title", "Demo EP2",
    ])
    assert rc == 0
    written = out_path.read_text(encoding="utf-8")
    assert "[RECAP]" in written
    assert "第 1 集 回顾：黑帮大佬重生回到十六岁。" in written
    assert "<refs>recap</refs>" in written


def test_main_story_without_prior_context_has_no_recap(tmp_path: Path) -> None:
    style_path = tmp_path / "niu-shu.md"
    style_path.write_text("# Demo Style\n", encoding="utf-8")
    digest_path = tmp_path / "plot_digest.txt"
    digest_path.write_text("## 剧情脉络\n- beat one\n", encoding="utf-8")

    out_path = tmp_path / "story_prompt.txt"
    rc = main([
        "--style", str(style_path),
        "--plot-digest", str(digest_path),
        "--out", str(out_path),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    written = out_path.read_text(encoding="utf-8")
    assert "Episode recap opening" not in written
