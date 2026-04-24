import json
from pathlib import Path

from app.pipeline.stage2_generate_script import (
    build_grounding_prompt,
    build_writer_prompt,
)


def test_build_writer_prompt_uses_two_pass_contract(tmp_path: Path) -> None:
    style_path = tmp_path / "style.md"
    plot_path = tmp_path / "movie.txt"
    srt_path = tmp_path / "movie.srt"

    style_path.write_text("# style", encoding="utf-8")
    plot_path.write_text("剧情概要", encoding="utf-8")
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n台词\n",
        encoding="utf-8",
    )

    prompt = build_writer_prompt(
        style_path=style_path,
        subtitle_text_path=plot_path,
        subtitle_srt_path=srt_path,
        movie_title="Demo",
        genre="action",
    )

    assert "[BEAT 1]" in prompt
    assert "Do not output any [SCENE] or [BROLL] markers" in prompt
    assert "剧情概要" in prompt
    assert "台词" in prompt


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
                    "is_action": True,
                    "confidence": 0.93,
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
    assert "[SCENE start=HH:MM:SS.mmm end=HH:MM:SS.mmm source=srt|visual" in prompt
    assert "[SCENE source=ungrounded confidence=0.00 evidence=none]" in prompt