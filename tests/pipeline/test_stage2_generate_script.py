import json
from pathlib import Path

from app.pipeline.stage2_generate_script import (
    build_planner_prompt,
    main,
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
    # Both dialogue and visual events appear in the merged timeline,
    # interleaved chronologically.
    timeline = prompt.split("<<<TIMELINE_START>>>")[1].split("<<<TIMELINE_END>>>")[0]
    assert "[srt:001] 00:00:01.000 --> 00:00:03.000 :: 台词" in timeline
    assert "[visual:001] 00:00:05.000 --> 00:00:08.000" in timeline
    assert "[srt:002] 00:00:10.000 --> 00:00:12.000 :: 第二句台词" in timeline
    assert timeline.index("[srt:001]") < timeline.index("[visual:001]")
    assert timeline.index("[visual:001]") < timeline.index("[srt:002]")
    # Movie metadata appears.
    assert "Title: Demo" in prompt
    assert "Genre: action" in prompt
    assert "Prefer fewer longer holds over many tiny snippets." in prompt
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
