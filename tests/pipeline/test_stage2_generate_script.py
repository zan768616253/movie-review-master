import json
from pathlib import Path

from app.pipeline.stage2_generate_script import (
    build_merged_timeline,
    build_planner_prompt,
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
    assert "[ANCHOR ranges=" in prompt
    assert "chars_per_second = 5.0" in prompt
    # Style rulebook is cited verbatim between the start/end markers.
    assert "<<<STYLE_RULEBOOK_START>>>" in prompt
    assert "<<<STYLE_RULEBOOK_END>>>" in prompt
    # Both dialogue and per-shot visual entries appear in the merged
    # timeline, interleaved chronologically. Visual entries are emitted
    # as [shot:NNN] (one source shot each) rather than the legacy
    # event-level [visual:NNN].
    timeline = prompt.split("<<<TIMELINE_START>>>")[1].split("<<<TIMELINE_END>>>")[0]
    assert "[srt:001] 00:00:01.000 --> 00:00:03.000 :: 台词" in timeline
    assert "[shot:001] 00:00:05.000 --> 00:00:08.000 (3.0s)" in timeline
    assert "[srt:002] 00:00:10.000 --> 00:00:12.000 :: 第二句台词" in timeline
    assert timeline.index("[srt:001]") < timeline.index("[shot:001]")
    assert timeline.index("[shot:001]") < timeline.index("[srt:002]")
    # Movie metadata appears.
    assert "Title: Demo" in prompt
    assert "Genre: action" in prompt
    # Shot-aware contract messages are present.
    assert "Anchor ranges MUST come from these timestamps" in prompt
    assert "Each range must stay inside ONE" in prompt
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
    assert "[ANCHOR ranges=" in captured.out


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


def test_split_segment_into_shots_splits_on_inner_boundaries() -> None:
    # Stage 0 detected two inner cuts at 62.0 and 65.5 inside a [60, 70]
    # segment. The segment expands into three back-to-back source shots.
    seg = {
        "start": "00:01:00.000",
        "end": "00:01:10.000",
        "shot_boundaries_s": [62.0, 65.5],
    }
    assert split_segment_into_shots(seg) == [
        (60.0, 62.0),
        (62.0, 65.5),
        (65.5, 70.0),
    ]


def test_split_segment_into_shots_drops_flicker_subshots() -> None:
    # An inner boundary too close to the segment start would produce a
    # 0.2s flicker that the planner cannot use. Drop those.
    seg = {
        "start": "00:01:00.000",
        "end": "00:01:08.000",
        "shot_boundaries_s": [60.2, 65.0],
    }
    assert split_segment_into_shots(seg) == [(60.2, 65.0), (65.0, 68.0)]


def test_split_segment_into_shots_handles_malformed_segment() -> None:
    assert split_segment_into_shots({"start": "bad"}) == []
    assert split_segment_into_shots({"start": "00:01:00", "end": "00:00:50"}) == []


def test_build_merged_timeline_emits_one_shot_per_inner_cut(tmp_path: Path) -> None:
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
    srt = tmp_path / "movie.srt"
    srt.write_text("1\n00:00:11,000 --> 00:00:13,000\n你是谁\n", encoding="utf-8")

    timeline = build_merged_timeline(srt, visual)
    lines = [line for line in timeline.splitlines() if line.startswith("[shot:")]
    assert len(lines) == 4  # 1 from seg-A + 3 sub-shots from seg-B
    assert "[shot:001] 00:00:10.000 --> 00:00:18.000 (8.0s)" in timeline
    assert "[shot:002] 00:00:18.000 --> 00:00:22.000 (4.0s)" in timeline
    assert "[shot:003] 00:00:22.000 --> 00:00:25.500 (3.5s)" in timeline
    assert "[shot:004] 00:00:25.500 --> 00:00:30.000 (4.5s)" in timeline
    # All sub-shots inherit the parent segment's summary verbatim.
    assert timeline.count("sees villain") == 3
