import json
from pathlib import Path

from app.pipeline.stage2_generate_script import (
    build_grounding_prompt,
    build_writer_prompt,
    main,
)


def test_build_writer_prompt_uses_merged_timeline(tmp_path: Path) -> None:
    style_path = tmp_path / "style.md"
    srt_path = tmp_path / "movie.srt"
    visual_path = tmp_path / "visual_segments.json"

    style_path.write_text("# style", encoding="utf-8")
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

    prompt = build_writer_prompt(
        style_path=style_path,
        subtitle_srt_path=srt_path,
        visual_segments_path=visual_path,
        movie_title="Demo",
        genre="action",
    )

    assert "[BEAT 1]" in prompt
    assert "Do not output any [SCENE] or [BROLL] markers" in prompt
    # Both dialogue and visual events appear in the merged timeline
    assert "[srt:001] 00:00:01.000 --> 00:00:03.000 :: 台词" in prompt
    assert "[srt:002] 00:00:10.000 --> 00:00:12.000 :: 第二句台词" in prompt
    assert "[visual:001] 00:00:05.000 --> 00:00:08.000 :: chars=Hero | hero attacks" in prompt
    # Events are interleaved in chronological order: srt:001 < visual:001 < srt:002
    timeline_section = prompt.split("<<<TIMELINE_START>>>")[1].split("<<<TIMELINE_END>>>")[0]
    assert timeline_section.index("[srt:001]") < timeline_section.index("[visual:001]")
    assert timeline_section.index("[visual:001]") < timeline_section.index("[srt:002]")


def test_build_grounding_prompt_serializes_srt_and_visual_references(tmp_path: Path) -> None:
    beats_path = tmp_path / "beats.txt"
    srt_path = tmp_path / "movie.srt"
    visual_path = tmp_path / "visual_segments.json"

    beats_path.write_text("[TITLE] Demo\n[HOOK]\n[BEAT 1]\n第一段\n", encoding="utf-8")
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,500\n这是台词\n",
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

    prompt = build_grounding_prompt(beats_path, srt_path, visual_path, "Demo")

    assert "[srt:001] 00:00:01.000 --> 00:00:03.500 :: 这是台词" in prompt
    assert "[visual:001] 00:00:05.000 --> 00:00:08.000" in prompt
    assert "chars=Hero" in prompt
    assert "summary=hero attacks" in prompt
    # Removed columns should not leak into the reference block.
    assert "| action=" not in prompt
    assert "| confidence=" not in prompt
    assert "[SCENE start=HH:MM:SS.mmm end=HH:MM:SS.mmm source=srt|visual" in prompt
    assert "[SCENE source=ungrounded confidence=0.00 evidence=none]" in prompt


def test_main_writer_subcommand_defaults_movie_title_and_genre(tmp_path: Path, capsys) -> None:
    style_path = tmp_path / "style.md"
    srt_path = tmp_path / "movie.srt"
    visual_path = tmp_path / "visual_segments.json"

    style_path.write_text("# style", encoding="utf-8")
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n台词\n",
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

    exit_code = main(["writer", str(style_path), str(srt_path), str(visual_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Title: movie" in captured.out
    assert "Genre: general" in captured.out


def test_main_grounder_subcommand_defaults_movie_title(tmp_path: Path, capsys) -> None:
    beats_path = tmp_path / "beats.txt"
    srt_path = tmp_path / "movie.srt"
    visual_path = tmp_path / "visual_segments.json"

    beats_path.write_text("[TITLE] Demo\n[HOOK]\n[BEAT 1]\n第一段\n", encoding="utf-8")
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,500\n这是台词\n",
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

    exit_code = main(["grounder", str(beats_path), str(srt_path), str(visual_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Title: movie" in captured.out