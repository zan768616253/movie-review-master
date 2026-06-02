"""End-to-end series wiring: drive workbench/step_2 through two episodes.

Exercises the full glue — config synthesis (_common), prior-context assembly +
承上启下 harvest (series_context), and the Stage 2 CLI builders — without any
real LLM, video, or network. Episode work dirs and the continuity file are
redirected into tmp_path by monkeypatching `_common.WORK_ROOT` and
`_common.load_active_config`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_DIR = REPO_ROOT / "workbench"
sys.path.insert(0, str(WORKBENCH_DIR))

import _common  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "workbench_step_2_series_integration", WORKBENCH_DIR / "step_2_build_prompt.py"
)
step_2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step_2)


_SCENE_MARKERS = {
    "character_glossary": [
        {"original_name": "主角", "role": "protagonist", "first_seen_scene": "scene:01"},
    ],
    "scenes": [
        {"id": "scene:01", "label": "开场", "act_tag": "SETUP",
         "visual_id_range": ["visual:001", "visual:001"],
         "time_range": ["00:00:00.000", "00:00:04.000"], "hook": "主角登场"},
    ],
}
_VISUAL_SEGMENTS = [
    {"id": "visual:001", "start": "00:00:00.000", "end": "00:00:04.000",
     "summary": "主角登场", "ocr_text": "", "characters": ["主角"]},
]


def _digest_with_carryover(carryover: str) -> str:
    return (
        "## 剧情脉络\n- 主角登场。\n\n"
        f"## 承上启下 (Continuity Carryover)\n{carryover}\n"
    )


def _make_series_cfg(series_dir: Path, style_path: Path, active_episode: int) -> dict:
    return {
        "common": {
            "series_slug": "demo_series",
            "series_dir": str(series_dir),
            "series_title": "Demo 系列",
            "style_path": str(style_path),
            "active_episode": active_episode,
            "digest_mode": "single",
            "target_seconds": 720.0,
        },
        "episodes": [
            {"episode_no": 1, "title": "第1集", "video_file": "EP01.mp4", "subtitle_file": "EP01.ass"},
            {"episode_no": 2, "title": "第2集", "video_file": "EP02.mp4", "subtitle_file": "EP02.ass"},
        ],
    }


def _stage1_inputs(paths) -> None:
    paths.stage1_dir.mkdir(parents=True, exist_ok=True)
    paths.visual_segments.write_text(json.dumps(_VISUAL_SEGMENTS, ensure_ascii=False), encoding="utf-8")
    paths.subtitles_text.write_text("", encoding="utf-8")
    paths.scene_markers.write_text(json.dumps(_SCENE_MARKERS, ensure_ascii=False), encoding="utf-8")


def test_series_two_episode_flow(tmp_path, monkeypatch) -> None:
    series_dir = tmp_path / "movies" / "demo_series"
    series_dir.mkdir(parents=True, exist_ok=True)
    (series_dir / "synopsis.md").write_text("一个关于诅咒的故事。", encoding="utf-8")
    style_path = tmp_path / "niu-shu.md"
    style_path.write_text("# Demo Style\nUse hard hooks.\n", encoding="utf-8")

    monkeypatch.setattr(_common, "WORK_ROOT", tmp_path / "work")

    def use_episode(active_episode: int):
        cfg = _make_series_cfg(series_dir, style_path, active_episode)
        monkeypatch.setattr(_common, "load_active_config", lambda: (cfg, True))
        return _common.resolve_run_context()

    # --- Episode 1: HOOK opener, no prior context; carryover harvested ---
    ctx1 = use_episode(1)
    _stage1_inputs(ctx1.paths)
    ctx1.paths.plot_digest.write_text(
        _digest_with_carryover("本集结束时，主角踏上旅程，敌人尚未现身。"), encoding="utf-8"
    )
    # scene_markers + plot_digest filled, script empty → story step.
    assert step_2.run([]) == 0
    story1 = ctx1.paths.story_prompt.read_text(encoding="utf-8")
    assert "Episode recap opening" not in story1
    assert "[RECAP]" not in story1

    series_md = ctx1.series_context_path.read_text(encoding="utf-8")
    assert "第 1 集" in series_md
    assert "本集结束时，主角踏上旅程" in series_md

    # --- Episode 2: digest gets prior context; story opens with [RECAP] ---
    ctx2 = use_episode(2)
    _stage1_inputs(ctx2.paths)

    # plot_digest empty → digest step. Prior context (ep1) must be injected.
    assert step_2.run([]) == 0
    digest2 = ctx2.paths.digest_prompt.read_text(encoding="utf-8")
    assert "Previously in the series" in digest2
    assert "本集结束时，主角踏上旅程" in digest2   # ep1 carryover threaded in
    assert "承上启下" in digest2                    # ep2 also emits its own carryover

    # Fill ep2 digest, advance to story.
    ctx2.paths.plot_digest.write_text(
        _digest_with_carryover("第二集结束时，主角第一次直面敌人。"), encoding="utf-8"
    )
    assert step_2.run([]) == 0
    story2 = ctx2.paths.story_prompt.read_text(encoding="utf-8")
    assert "[RECAP]" in story2
    assert "<refs>recap</refs>" in story2
    assert "本集结束时，主角踏上旅程" in story2     # ep1 recap source present

    series_md2 = ctx2.series_context_path.read_text(encoding="utf-8")
    assert "第 1 集" in series_md2 and "第 2 集" in series_md2


def test_recap_script_passes_post_validation() -> None:
    """A hand-written episode-2 script: recap lines use the sentinel, the body
    cites a real visual id. post-validation must flag nothing."""
    from app.pipeline.stage_2.post_validate import validate_script
    from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument

    doc = SceneMarkersDocument(
        character_glossary=[],
        scenes=[SceneMarker("scene:01", "x", "SETUP", ("visual:001", "visual:010"),
                            ("00:00:00.000", "00:00:10.000"), "x")],
    )
    script = (
        "[RECAP]\n"
        "<refs>recap</refs>\n"
        "上一集，主角踏上旅程。\n"
        "[ACT 1 - SETUP]\n"
        "<refs>visual:001</refs>\n"
        "本集开场，主角抵达新城市。\n"
    )
    report = validate_script(
        script_text=script,
        scene_markers=doc,
        all_visual_ids={f"visual:{i:03d}" for i in range(1, 11)},
    )
    assert report.total_sentences == 2
    assert report.flagged == []
