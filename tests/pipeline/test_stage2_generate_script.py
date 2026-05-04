import json
from pathlib import Path

from app.pipeline.stage2_generate_script import (
    build_dialogue_block,
    build_planner_prompt,
    build_shot_menu,
    main,
    split_segment_into_shots,
)


def _write_demo_inputs(tmp_path: Path, *, with_synopsis: bool = False) -> dict[str, Path]:
    style_path = tmp_path / "style.md"
    srt_path = tmp_path / "movie.srt"
    visual_path = tmp_path / "visual_segments.json"

    style_path.write_text(
        "# style\n**TTS Budget:** `chars_per_second = 5.0`.\n",
        encoding="utf-8",
    )
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n台词\n\n"
        "2\n00:00:10,000 --> 00:00:12,000\n第二句台词\n",
        encoding="utf-8",
    )
    visual_path.write_text(
        json.dumps(
            [
                {
                    "start": "00:00:05.000",
                    "end": "00:00:08.000",
                    "summary": "hero attacks",
                    "ocr_text": "",
                    "characters": ["Hero"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    paths = {"style": style_path, "srt": srt_path, "visual": visual_path}
    if with_synopsis:
        synopsis_path = tmp_path / "synopsis.md"
        synopsis_path.write_text(
            "# Demo\n\n## Cast\n- Hero: protagonist\n", encoding="utf-8"
        )
        paths["synopsis"] = synopsis_path
    return paths


def test_build_planner_prompt_inlines_style_and_merged_timeline(tmp_path: Path) -> None:
    paths = _write_demo_inputs(tmp_path)

    prompt = build_planner_prompt(
        style_path=paths["style"],
        subtitle_srt_path=paths["srt"],
        visual_segments_path=paths["visual"],
        movie_title="Demo",
        genre="action",
        target_seconds=300.0,
    )

    # Schema and budget appear.
    assert '[ANCHOR id="chunk-' in prompt
    assert "chars_per_second = 5.0" in prompt
    # Style rulebook is cited verbatim between the start/end markers.
    assert "<<<STYLE_RULEBOOK_START>>>" in prompt
    assert "<<<STYLE_RULEBOOK_END>>>" in prompt
    # Shot menu and dialogue block live in two SEPARATE sections so the
    # planner can't accidentally pick srt timestamps as ranges.
    shot_menu = prompt.split("<<<SHOT_MENU_START>>>")[1].split("<<<SHOT_MENU_END>>>")[0]
    dialogue = prompt.split("<<<DIALOGUE_START>>>")[1].split("<<<DIALOGUE_END>>>")[0]
    assert "[shot:001] 00:00:05.000 → 00:00:08.000 (3.0s)" in shot_menu
    assert "[shot:" not in dialogue  # shot lines never appear in dialogue
    # Both demo srt lines fall outside the single demo shot, so they
    # render without an `inside shot:NNN` hint. The dedicated dialogue
    # test below covers the inside-shot case.
    assert "[srt:001] 00:00:01.000 → 00:00:03.000 :: 台词" in dialogue
    assert "[srt:002] 00:00:10.000 → 00:00:12.000 :: 第二句台词" in dialogue
    # Movie metadata appears.
    assert "Title: Demo" in prompt
    assert "Genre: action" in prompt
    # Shot-aware contract messages are present.
    assert "Every anchor range MUST be a copy of one shot's timestamps" in prompt
    assert "Each range must stay inside ONE" in prompt
    # Id constraint is reinforced.
    assert 'id="chunk-NNN"' in prompt
    # Closing rule.
    assert "[CLOSING]" in prompt
    assert "no [ANCHOR]" in prompt


def test_build_planner_prompt_includes_synopsis_when_provided(tmp_path: Path) -> None:
    paths = _write_demo_inputs(tmp_path, with_synopsis=True)

    prompt = build_planner_prompt(
        style_path=paths["style"],
        subtitle_srt_path=paths["srt"],
        visual_segments_path=paths["visual"],
        movie_title="Demo",
        genre="action",
        target_seconds=300.0,
        synopsis_path=paths["synopsis"],
    )

    synopsis_block = prompt.split("<<<SYNOPSIS_START>>>")[1].split("<<<SYNOPSIS_END>>>")[0]
    assert "Hero: protagonist" in synopsis_block
    assert "No synopsis provided" not in synopsis_block


def test_build_planner_prompt_emits_no_synopsis_placeholder(tmp_path: Path) -> None:
    paths = _write_demo_inputs(tmp_path)

    prompt = build_planner_prompt(
        style_path=paths["style"],
        subtitle_srt_path=paths["srt"],
        visual_segments_path=paths["visual"],
        movie_title="Demo",
        genre="action",
        target_seconds=300.0,
    )

    synopsis_block = prompt.split("<<<SYNOPSIS_START>>>")[1].split("<<<SYNOPSIS_END>>>")[0]
    assert "No synopsis provided" in synopsis_block


def test_build_planner_prompt_uses_style_chars_per_second(tmp_path: Path) -> None:
    paths = _write_demo_inputs(tmp_path)
    paths["style"].write_text(
        "# style\n**TTS Budget:** `chars_per_second = 4.5`.\n",
        encoding="utf-8",
    )

    prompt = build_planner_prompt(
        style_path=paths["style"],
        subtitle_srt_path=paths["srt"],
        visual_segments_path=paths["visual"],
        movie_title="Demo",
        genre="action",
        target_seconds=300.0,
    )

    assert "chars_per_second = 4.5" in prompt
    # Worked-example budget recomputes correctly: 12s × 4.5 = 54.
    assert "12 × 4.5 = 54 characters" in prompt


def test_build_planner_prompt_declares_movie_config_as_duration_authority(tmp_path: Path) -> None:
    paths = _write_demo_inputs(tmp_path)
    paths["style"].write_text(
        "# style\n"
        "2. **Cover the whole story in 99 minutes.**\n"
        "**Target Duration:** 99 minutes\n"
        "**Character-count Window:** 9999 chars\n"
        "**TTS Budget:** `chars_per_second = 5.0`.\n",
        encoding="utf-8",
    )

    prompt = build_planner_prompt(
        style_path=paths["style"],
        subtitle_srt_path=paths["srt"],
        visual_segments_path=paths["visual"],
        movie_title="Demo",
        genre="action",
        target_seconds=300.0,
    )

    assert "Review length, total narration budget, and anchor coverage come ONLY from" in prompt
    assert "target_seconds = 300" in prompt
    assert "acceptable_review_window = 210-390s" in prompt
    # Macro target = target_seconds × REAL_TTS_CPS = 300 × 6.74 = 2022;
    # min = 2022 × 0.85 = 1719. The macro formula uses real TTS speech
    # rate (not the per-anchor writing cap) because that's what governs
    # how many chars produce a given audio duration.
    assert "ALL anchors must land in 1719-2022 characters" in prompt


def test_build_planner_prompt_includes_local_budgets_and_output_gate(tmp_path: Path) -> None:
    paths = _write_demo_inputs(tmp_path)

    prompt = build_planner_prompt(
        style_path=paths["style"],
        subtitle_srt_path=paths["srt"],
        visual_segments_path=paths["visual"],
        movie_title="Demo",
        genre="action",
        target_seconds=300.0,
    )

    assert "Local writing targets — track these WHILE drafting" in prompt
    assert "Act 1 target: ~323 chars" in prompt
    assert "Act 2 target: ~485 chars" in prompt
    assert "Act 3 target: ~808 chars" in prompt
    assert "Act 4 target: ~406 chars" in prompt
    assert "keep `sum(all_anchor_seconds)` inside" in prompt
    assert "**344-485s** (target ~404s)" in prompt
    assert 'Do NOT over-cover "just in case."' in prompt
    assert "6s anchor → budget 30 chars → aim for ~26-28 chars" in prompt
    assert "8s anchor → budget 40 chars → aim for ~34-38 chars" in prompt
    assert "10s anchor → budget 50 chars → aim for ~42-48 chars" in prompt
    assert "For most anchors, did I use ~85-95% of the local budget" in prompt
    assert "# Final Output Gate" in prompt
    assert "total selected anchor coverage stays inside 344-485s" in prompt
    assert "most anchors use ~85-95% of their local budget rather than one thin sentence" in prompt


def test_main_prints_planner_prompt_and_defaults_title(tmp_path: Path, capsys) -> None:
    paths = _write_demo_inputs(tmp_path)

    exit_code = main([
        str(paths["style"]),
        str(paths["srt"]),
        str(paths["visual"]),
    ])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Title: movie" in captured.out  # default from filename stem
    assert "Genre: general" in captured.out
    assert '[ANCHOR id="chunk-' in captured.out


def test_main_reports_missing_synopsis(tmp_path: Path, capsys) -> None:
    paths = _write_demo_inputs(tmp_path)

    exit_code = main([
        str(paths["style"]),
        str(paths["srt"]),
        str(paths["visual"]),
        "--synopsis",
        str(tmp_path / "missing-synopsis.md"),
    ])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Synopsis not found" in captured.err


# --- shot-aware timeline -------------------------------------------------


def test_split_segment_into_shots_returns_one_shot_for_clean_segment() -> None:
    seg = {"start": "00:01:00.000", "end": "00:01:08.000", "shot_boundaries_s": []}
    assert split_segment_into_shots(seg) == [(60.0, 68.0)]


def test_split_segment_into_shots_splits_on_inner_boundaries_when_all_long() -> None:
    # Stage 0 detected two inner cuts inside a [60, 75] segment. All
    # three sub-shots are ≥3s, so they survive the inner-cut collapse
    # rule and are emitted individually.
    seg = {
        "start": "00:01:00.000",
        "end": "00:01:15.000",
        "shot_boundaries_s": [65.0, 70.0],
    }
    assert split_segment_into_shots(seg) == [
        (60.0, 65.0),
        (65.0, 70.0),
        (70.0, 75.0),
    ]


def test_split_segment_into_shots_collapses_when_any_subshot_under_3s() -> None:
    # Stage 0 detected two inner cuts at 62.0 and 65.5 inside a [60, 70]
    # segment. The first sub-shot is only 2s (<3s collapse threshold),
    # so the whole segment is emitted as one shot — the LLM treats
    # rapid-cut beats as one editorial unit and the validator's
    # boundary set excludes the inner cuts.
    seg = {
        "start": "00:01:00.000",
        "end": "00:01:10.000",
        "shot_boundaries_s": [62.0, 65.5],
    }
    assert split_segment_into_shots(seg) == [(60.0, 70.0)]


def test_split_segment_into_shots_drops_flicker_subshots() -> None:
    # An inner boundary too close to the segment start would produce a
    # 0.2s flicker that the planner cannot use. Drop those — and after
    # the drop both surviving sub-shots are ≥3s, so the segment splits
    # normally (no inner-cut collapse triggered).
    seg = {
        "start": "00:01:00.000",
        "end": "00:01:08.000",
        "shot_boundaries_s": [60.2, 65.0],
    }
    assert split_segment_into_shots(seg) == [(60.2, 65.0), (65.0, 68.0)]


def test_split_segment_into_shots_handles_malformed_segment() -> None:
    assert split_segment_into_shots({"start": "bad"}) == []
    assert split_segment_into_shots({"start": "00:01:00", "end": "00:00:50"}) == []


def test_build_shot_menu_emits_one_line_per_inner_cut(tmp_path: Path) -> None:
    visual = tmp_path / "visual_segments.json"
    visual.write_text(
        json.dumps(
            [
                {
                    "start": "00:00:10.000",
                    "end": "00:00:18.000",
                    "summary": "walks in",
                    "ocr_text": "",
                    "characters": ["Yuta"],
                    "shot_boundaries_s": [],
                },
                {
                    "start": "00:00:18.000",
                    "end": "00:00:30.000",
                    "summary": "sees villain",
                    "ocr_text": "",
                    "characters": ["Villain"],
                    "shot_boundaries_s": [22.0, 25.5],
                },
            ]
        ),
        encoding="utf-8",
    )

    menu = build_shot_menu(visual)
    lines = [line for line in menu.splitlines() if line.startswith("[shot:")]
    assert len(lines) == 4  # 1 from seg-A + 3 sub-shots from seg-B
    assert "[shot:001] 00:00:10.000 → 00:00:18.000 (8.0s)" in menu
    assert "[shot:002] 00:00:18.000 → 00:00:22.000 (4.0s)" in menu
    assert "[shot:003] 00:00:22.000 → 00:00:25.500 (3.5s)" in menu
    assert "[shot:004] 00:00:25.500 → 00:00:30.000 (4.5s)" in menu
    # All sub-shots inherit the parent segment's summary verbatim.
    assert menu.count("sees villain") == 3
    # Shot menu carries no srt lines — that's the whole point of splitting.
    assert "[srt:" not in menu


def test_build_dialogue_block_tags_lines_with_their_containing_shot(tmp_path: Path) -> None:
    visual = tmp_path / "visual_segments.json"
    visual.write_text(
        json.dumps(
            [
                {
                    "start": "00:00:10.000",
                    "end": "00:00:18.000",
                    "summary": "walks in",
                    "ocr_text": "",
                    "characters": ["Yuta"],
                    "shot_boundaries_s": [],
                },
                {
                    "start": "00:00:18.000",
                    "end": "00:00:30.000",
                    "summary": "talks to villain",
                    "ocr_text": "",
                    "characters": ["Villain"],
                    "shot_boundaries_s": [],
                },
            ]
        ),
        encoding="utf-8",
    )
    srt = tmp_path / "movie.srt"
    srt.write_text(
        "1\n00:00:11,000 --> 00:00:13,000\n你是谁\n\n"
        "2\n00:00:20,000 --> 00:00:22,000\n我是反派\n\n"
        "3\n00:00:40,000 --> 00:00:42,000\n声音在没有镜头的地方\n",
        encoding="utf-8",
    )

    dialogue = build_dialogue_block(srt, visual)
    # Line 1 is inside shot:001; line 2 is inside shot:002; line 3 is
    # outside any shot so no inside hint is emitted.
    assert "[srt:001 inside shot:001] 00:00:11.000 → 00:00:13.000 :: 你是谁" in dialogue
    assert "[srt:002 inside shot:002] 00:00:20.000 → 00:00:22.000 :: 我是反派" in dialogue
    assert "[srt:003] 00:00:40.000 → 00:00:42.000 :: 声音在没有镜头的地方" in dialogue
    # Dialogue block must not contain shot lines.
    assert "[shot:" not in dialogue
