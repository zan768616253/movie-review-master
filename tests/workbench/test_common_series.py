"""Tests for series-config resolution in workbench/_common.py.

`workbench/` is not a package; put it on sys.path so the bare `import _common`
(used by the step scripts) resolves the same way the CLI does.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKBENCH_DIR = REPO_ROOT / "workbench"
sys.path.insert(0, str(WORKBENCH_DIR))

import _common  # noqa: E402


def _series_cfg() -> dict:
    return {
        "common": {
            "series_slug": "jjk_s3",
            "series_dir": "movies/咒术回战第三季",
            "series_title": "咒术回战 第三季",
            "style_path": "styles/niu-shu.md",
            "genre": "Action",
            "active_episode": 2,
            "digest_mode": "single",
            "target_seconds": 720.0,
        },
        "episodes": [
            {"episode_no": 1, "video_file": "EP01.mp4", "subtitle_file": "EP01.ass"},
            {
                "episode_no": 2,
                "title": "第2集 承",
                "video_file": "EP02.mp4",
                "subtitle_file": "EP02.ass",
                "synopsis_file": "EP02.synopsis.md",
            },
        ],
        "tools": {"generate_script_audio": {"temperature": 0.7}},
    }


def _movie_cfg() -> dict:
    return {
        "common": {
            "movie_slug": "demo",
            "movie_dir": "movies/demo",
            "movie_title": "Demo",
            "video_file": "demo.mp4",
            "subtitle_file": "demo.srt",
            "style_path": "styles/niu-shu.md",
        }
    }


def test_is_series_config_distinguishes_series_from_movie() -> None:
    assert _common.is_series_config(_series_cfg()) is True
    assert _common.is_series_config(_movie_cfg()) is False


def test_active_episode_no() -> None:
    assert _common.active_episode_no(_series_cfg()) == 2


def test_episode_entry_unknown_raises_with_number() -> None:
    import pytest

    with pytest.raises(ValueError, match="99"):
        _common.episode_entry(_series_cfg(), 99)


def test_series_episode_common_synthesizes_movie_shaped_config() -> None:
    cfg = _common.series_episode_common(_series_cfg(), 2)
    common = cfg["common"]
    assert common["movie_slug"] == "jjk_s3/ep02"
    assert common["movie_dir"] == "movies/咒术回战第三季"
    assert common["movie_title"] == "第2集 承"
    assert common["video_file"] == "EP02.mp4"
    assert common["subtitle_file"] == "EP02.ass"
    assert common["style_path"] == "styles/niu-shu.md"
    assert common["genre"] == "Action"
    assert common["digest_mode"] == "single"
    assert common["target_seconds"] == 720.0
    assert common["synopsis_file"] == "EP02.synopsis.md"
    # tools carry through; episodes are dropped.
    assert cfg["tools"]["generate_script_audio"]["temperature"] == 0.7
    assert "episodes" not in cfg


def test_series_episode_common_title_fallback_when_episode_has_no_title() -> None:
    cfg = _common.series_episode_common(_series_cfg(), 1)
    assert cfg["common"]["movie_title"] == "咒术回战 第三季 第1集"


def test_build_paths_for_episode_nests_under_series_slug() -> None:
    cfg = _common.series_episode_common(_series_cfg(), 2)
    paths = _common.build_paths(cfg)
    assert paths.visual_segments.as_posix().endswith("work/jjk_s3/ep02/stage1/visual_segments.json")
    assert paths.stage2_dir.as_posix().endswith("work/jjk_s3/ep02/stage2")
    # Per-episode synopsis override is honored.
    assert paths.synopsis.as_posix().endswith("movies/咒术回战第三季/EP02.synopsis.md")


def test_build_paths_defaults_to_series_synopsis_when_no_override() -> None:
    cfg = _common.series_episode_common(_series_cfg(), 1)
    paths = _common.build_paths(cfg)
    assert paths.synopsis.as_posix().endswith("movies/咒术回战第三季/synopsis.md")


def test_build_paths_movie_synopsis_unchanged() -> None:
    paths = _common.build_paths(_movie_cfg())
    assert paths.synopsis.as_posix().endswith("movies/demo/synopsis.md")


def test_series_context_file_lives_at_series_root() -> None:
    path = _common.series_context_file(_series_cfg())
    assert path.as_posix().endswith("work/jjk_s3/series_context.md")
