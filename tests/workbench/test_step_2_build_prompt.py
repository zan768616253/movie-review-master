"""Tests for the workbench step_2 wrapper's auto-detect logic.

`workbench/` is not a Python package (no `__init__.py`); load the module by file
path so the existing `sys.path.insert(0, ...)` line inside `step_2_build_prompt.py`
can resolve its sibling `_common` import the same way the CLI does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_DIR = REPO_ROOT / "workbench"

# Make `_common` importable for step_2_build_prompt's bare `from _common import ...`.
sys.path.insert(0, str(WORKBENCH_DIR))

_spec = importlib.util.spec_from_file_location(
    "workbench_step_2_build_prompt",
    WORKBENCH_DIR / "step_2_build_prompt.py",
)
step_2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(step_2)


def test_detect_next_step_returns_outline_when_scene_markers_missing(tmp_path: Path) -> None:
    assert step_2.detect_next_step(
        scene_markers=tmp_path / "scene_markers.json",
        plot_digest=tmp_path / "plot_digest.txt",
        script=tmp_path / "script.txt",
    ) == "outline"


def test_detect_next_step_returns_outline_when_scene_markers_empty(tmp_path: Path) -> None:
    scene_markers = tmp_path / "scene_markers.json"
    scene_markers.write_text("", encoding="utf-8")
    assert step_2.detect_next_step(
        scene_markers=scene_markers,
        plot_digest=tmp_path / "plot_digest.txt",
        script=tmp_path / "script.txt",
    ) == "outline"


def test_detect_next_step_returns_outline_when_scene_markers_whitespace_only(tmp_path: Path) -> None:
    """A touched-but-empty placeholder file must not count as filled."""
    scene_markers = tmp_path / "scene_markers.json"
    scene_markers.write_text("   \n\n   ", encoding="utf-8")
    assert step_2.detect_next_step(
        scene_markers=scene_markers,
        plot_digest=tmp_path / "plot_digest.txt",
        script=tmp_path / "script.txt",
    ) == "outline"


def test_detect_next_step_returns_digest_when_scene_markers_filled(tmp_path: Path) -> None:
    scene_markers = tmp_path / "scene_markers.json"
    scene_markers.write_text('{"scenes": []}', encoding="utf-8")
    assert step_2.detect_next_step(
        scene_markers=scene_markers,
        plot_digest=tmp_path / "plot_digest.txt",
        script=tmp_path / "script.txt",
    ) == "digest"


def test_detect_next_step_returns_story_when_digest_filled(tmp_path: Path) -> None:
    scene_markers = tmp_path / "scene_markers.json"
    scene_markers.write_text('{"scenes": []}', encoding="utf-8")
    plot_digest = tmp_path / "plot_digest.txt"
    plot_digest.write_text("## Plot beats", encoding="utf-8")
    assert step_2.detect_next_step(
        scene_markers=scene_markers,
        plot_digest=plot_digest,
        script=tmp_path / "script.txt",
    ) == "story"


def test_detect_next_step_treats_touched_script_as_blocking(tmp_path: Path) -> None:
    """`_run_story` pre-creates `script.txt` empty; that must not count as 'done'."""
    scene_markers = tmp_path / "scene_markers.json"
    scene_markers.write_text('{"scenes": []}', encoding="utf-8")
    plot_digest = tmp_path / "plot_digest.txt"
    plot_digest.write_text("## Plot beats", encoding="utf-8")
    script = tmp_path / "script.txt"
    script.touch()
    assert step_2.detect_next_step(
        scene_markers=scene_markers,
        plot_digest=plot_digest,
        script=script,
    ) == "story"


def test_detect_next_step_returns_done_when_all_filled(tmp_path: Path) -> None:
    scene_markers = tmp_path / "scene_markers.json"
    scene_markers.write_text('{"scenes": []}', encoding="utf-8")
    plot_digest = tmp_path / "plot_digest.txt"
    plot_digest.write_text("## Plot beats", encoding="utf-8")
    script = tmp_path / "script.txt"
    script.write_text("[ACT 1 - SETUP]\n故事开场。", encoding="utf-8")
    assert step_2.detect_next_step(
        scene_markers=scene_markers,
        plot_digest=plot_digest,
        script=script,
    ) == "done"
