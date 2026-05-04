import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from app.pipeline.common.script_contract import (
    AnchorMarker,
    AnchorValidation,
    ScriptValidation,
    StructureIssue,
)


def _load_tmp_step2_module():
    module_path = Path(__file__).resolve().parents[2] / "tmp" / "step_02_generate_script.py"
    spec = importlib.util.spec_from_file_location("tmp_step_02_generate_script", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_write_validation_feedback_inlines_shot_menu_and_forbids_optional_rewrites(
    tmp_path: Path,
) -> None:
    module = _load_tmp_step2_module()

    anchored_script = tmp_path / "anchored_script.txt"
    anchored_script.write_text(
        "\n".join(
            [
                "[TITLE]",
                "Demo",
                "",
                "[ACT 1]",
                '[ANCHOR id="chunk-002" ranges="00:00:03.000-00:00:06.000"]',
                "This narration now overruns the local budget and needs repair.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    style_path = tmp_path / "style.md"
    style_path.write_text("# style\n**TTS Budget:** `chars_per_second = 5.0`.\n", encoding="utf-8")
    visual_segments = tmp_path / "visual_segments.json"
    visual_segments.write_text(
        json.dumps(
            [
                {
                    "start": "00:00:03.000",
                    "end": "00:00:06.000",
                    "summary": "hero storms into the room",
                    "ocr_text": "",
                    "characters": ["Hero"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    paths = SimpleNamespace(
        anchored_script=anchored_script,
        style=style_path,
        synopsis=tmp_path / "synopsis.md",
        visual_segments=visual_segments,
        stage2_dir=tmp_path,
    )

    chunk = AnchorValidation(
        index=1,
        anchor=AnchorMarker(
            id="chunk-002",
            ranges=[("00:00:03.000", "00:00:06.000")],
            raw='[ANCHOR id="chunk-002" ranges="00:00:03.000-00:00:06.000"]',
        ),
        narration_chars=61,
        budget_chars=15,
        overrun_ratio=61 / 15,
        severity="fail",
    )
    result = ScriptValidation(
        chunks=[chunk],
        issues=[
            StructureIssue(
                severity="fail",
                code="range_provenance",
                message="timestamps do not match a legal source shot",
                chunk_id="chunk-002",
            )
        ],
    )

    feedback_path = module.write_validation_feedback(paths, result, 5.0)
    prompt = feedback_path.read_text(encoding="utf-8")

    shot_menu = prompt.split("<<<SHOT_MENU_START>>>")[1].split("<<<SHOT_MENU_END>>>")[0]
    assert "[shot:001] 00:00:03.000 → 00:00:06.000 (3.0s) :: chars=Hero | hero storms into the room" in shot_menu
    assert "do NOT need any separate upload to fix this prompt" in prompt
    assert "Only change anchors or script text required to resolve the listed validator failures." in prompt
    assert "Do not do optional rewrites, polish passes, or style improvements outside the invalid parts." in prompt
    assert "Pick a [shot:NNN] from the inlined shot menu" in prompt
    assert "I will upload `visual_segments.json` separately in this chat." not in prompt
