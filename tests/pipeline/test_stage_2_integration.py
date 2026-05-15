from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.stage_2_build_prompt import main as stage_2_main
from app.pipeline.stage_2.post_validate import validate_script
from app.pipeline.stage_2.scene_markers import load_scene_markers


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(json.dumps([
        {"id": f"visual:{i:03d}", "start": f"00:00:{i:02d}.000",
         "end": f"00:00:{i+1:02d}.000", "summary": f"shot {i}",
         "ocr_text": "", "characters": ["Hero"]}
        for i in range(1, 11)
    ], ensure_ascii=False), encoding="utf-8")

    subtitles_path = tmp_path / "subtitles.txt"
    subtitles_path.write_text(
        "[00:00:02.000 -> 00:00:03.000] hello\n"
        "[00:00:05.000 -> 00:00:06.000] watch out\n",
        encoding="utf-8",
    )

    synopsis_path = tmp_path / "synopsis.md"
    synopsis_path.write_text("Hero overcomes adversity.", encoding="utf-8")

    style_path = tmp_path / "style.md"
    style_path.write_text("---\nchars_per_minute: 250\n---\n\n# Demo style\nShort sharp lines.\n",
                          encoding="utf-8")

    return visual_segments_path, subtitles_path, synopsis_path, style_path


def _stub_scene_markers(path: Path) -> None:
    path.write_text(json.dumps({
        "character_glossary": [
            {"original_name": "Hero", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        "scenes": [
            {"id": "scene:01", "label": "setup", "act_tag": "SETUP",
             "visual_id_range": ["visual:001", "visual:004"],
             "time_range": ["00:00:00.000", "00:00:05.000"], "hook": "setup"},
            {"id": "scene:02", "label": "climax", "act_tag": "CLIMAX",
             "visual_id_range": ["visual:005", "visual:008"],
             "time_range": ["00:00:05.000", "00:00:09.000"], "hook": "climax"},
            {"id": "scene:03", "label": "close", "act_tag": "CLOSING",
             "visual_id_range": ["visual:009", "visual:010"],
             "time_range": ["00:00:09.000", "00:00:11.000"], "hook": "close"},
        ],
    }, ensure_ascii=False), encoding="utf-8")


def test_three_pass_pipeline_end_to_end(tmp_path: Path) -> None:
    visual_p, subs_p, syn_p, style_p = _write_inputs(tmp_path)

    # Pass 0 prompt
    outline_p = tmp_path / "outline_prompt.txt"
    rc = stage_2_main([
        "--outline",
        "--visual-segments", str(visual_p),
        "--subtitles-txt", str(subs_p),
        "--synopsis", str(syn_p),
        "--out", str(outline_p),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    outline_text = outline_p.read_text(encoding="utf-8")
    assert "scene_markers.json" in outline_text or "JSON" in outline_text

    # Simulate the LLM reply by writing a hand-crafted scene_markers.json
    scene_p = tmp_path / "scene_markers.json"
    _stub_scene_markers(scene_p)
    scene_doc = load_scene_markers(scene_p)
    assert scene_doc.scenes[1].act_tag == "CLIMAX"

    # Pass 1 prompt (single mode, scene-anchored)
    digest_prompt_p = tmp_path / "digest_prompt.txt"
    rc = stage_2_main([
        "--digest",
        "--visual-segments", str(visual_p),
        "--subtitles-txt", str(subs_p),
        "--scene-markers", str(scene_p),
        "--out", str(digest_prompt_p),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    digest_text = digest_prompt_p.read_text(encoding="utf-8")
    assert "scene:02" in digest_text
    assert "CLIMAX" in digest_text and "4-6" in digest_text

    # Simulate the LLM digest reply
    plot_digest_p = tmp_path / "plot_digest.txt"
    plot_digest_p.write_text(
        "## scene:01 (SETUP)\n- 镜头: visual:001-002\n- 事件: Hero appears.\n"
        "## scene:02 (CLIMAX)\n- 镜头: visual:005-008\n- 事件: Hero wins.\n",
        encoding="utf-8",
    )

    # Pass 2 prompt
    story_prompt_p = tmp_path / "story_prompt.txt"
    rc = stage_2_main([
        "--style", str(style_p),
        "--synopsis", str(syn_p),
        "--plot-digest", str(plot_digest_p),
        "--out", str(story_prompt_p),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    assert "Hero wins" in story_prompt_p.read_text(encoding="utf-8")

    # Simulate the LLM script reply; include one valid sentence and one with bad refs.
    script_p = tmp_path / "script.txt"
    script_p.write_text(
        "[ACT 1 - SETUP]\n"
        "<refs>visual:001</refs>\n"
        "故事开场，主角登场。\n"
        "\n"
        "<refs>visual:999</refs>\n"
        "这一句的 visual ID 不存在。\n",
        encoding="utf-8",
    )

    # Post-validation
    visual_segments = json.loads(visual_p.read_text(encoding="utf-8"))
    report = validate_script(
        script_text=script_p.read_text(encoding="utf-8"),
        scene_markers=scene_doc,
        all_visual_ids={s["id"] for s in visual_segments},
    )
    assert report.total_sentences == 2
    assert len(report.flagged) == 1
    assert "visual:999" in report.flagged[0].issue
