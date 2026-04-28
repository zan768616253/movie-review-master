"""Smoke tests for the per-step harness scripts under tmp/.

These tests import each `tmp/step_*.py` and `tmp/run_all.py` module to
verify they don't reference paths or constants that no longer exist on
the central `_common.py`. They do not execute any pipeline stage — they
just catch the regression class where renaming a path field in
`_common.py` silently breaks one of the wrappers (the Stage 2 overhaul
shipped exactly such a regression on develop, hence this test).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


TMP_ROOT = Path(__file__).resolve().parents[2] / "tmp"


def _reload(module_name: str):
    if str(TMP_ROOT) not in sys.path:
        sys.path.insert(0, str(TMP_ROOT))
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)


def test_common_module_imports() -> None:
    _reload("_common")


def test_each_step_module_imports() -> None:
    for module_name in (
        "step_00_index_visuals",
        "step_01_parse_subtitles",
        "step_02_generate_script",
        "step_03_generate_audio",
        "step_04_video_processor",
        "step_05_render_video",
        "run_all",
    ):
        _reload(module_name)
