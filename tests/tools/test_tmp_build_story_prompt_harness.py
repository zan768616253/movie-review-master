from __future__ import annotations

import importlib.util
import tempfile

from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "tmp" / "tools" / "build_story_prompt.py"


def load_harness_module():
    spec = importlib.util.spec_from_file_location("tmp_build_story_prompt_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harness_requires_synopsis(monkeypatch) -> None:
    module = load_harness_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        movie_dir = root / "movies" / "demo"
        stage0_dir = root / "tmp" / "work" / "demo" / "stage0"
        stage1_dir = root / "tmp" / "work" / "demo" / "stage1"
        tools_dir = root / "tmp" / "work" / "demo" / "tools"
        style_path = root / "styles" / "demo-style.md"

        movie_dir.mkdir(parents=True)
        stage0_dir.mkdir(parents=True)
        stage1_dir.mkdir(parents=True)
        tools_dir.mkdir(parents=True)
        style_path.parent.mkdir(parents=True)

        style_path.write_text("# Demo Style\n", encoding="utf-8")
        (stage0_dir / "visual_segments.json").write_text("[]", encoding="utf-8")
        (stage1_dir / "subtitles.json").write_text("[]", encoding="utf-8")

        config = {
            "common": {
                "movie_slug": "demo",
                "movie_title": "Demo Movie",
                "movie_dir": str(movie_dir),
                "style_path": str(style_path),
                "video_file": "movie.mp4",
                "subtitle_file": "movie.srt",
            }
        }

        synopsis_path = movie_dir / "synopsis.md"
        paths = SimpleNamespace(
            style=style_path,
            synopsis=synopsis_path,
            visual_segments=stage0_dir / "visual_segments.json",
            subtitles_json=stage1_dir / "subtitles.json",
            story_prompt=tools_dir / "story_prompt.txt",
        )

        monkeypatch.setattr(module, "load_config", lambda _config: config)
        monkeypatch.setattr(module, "build_paths", lambda _config: paths)
        monkeypatch.setattr(module, "ensure_stage_dirs", lambda _paths: None)
        exit_code = module.run()

    assert exit_code == 1


def test_harness_passes_synopsis_to_tool(monkeypatch) -> None:
    module = load_harness_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        movie_dir = root / "movies" / "demo"
        stage0_dir = root / "tmp" / "work" / "demo" / "stage0"
        stage1_dir = root / "tmp" / "work" / "demo" / "stage1"
        tools_dir = root / "tmp" / "work" / "demo" / "tools"
        style_path = root / "styles" / "demo-style.md"
        synopsis_path = movie_dir / "synopsis.md"

        movie_dir.mkdir(parents=True)
        stage0_dir.mkdir(parents=True)
        stage1_dir.mkdir(parents=True)
        tools_dir.mkdir(parents=True)
        style_path.parent.mkdir(parents=True)

        style_path.write_text("# Demo Style\n", encoding="utf-8")
        synopsis_path.write_text("Plot and cast grounding.", encoding="utf-8")
        (stage0_dir / "visual_segments.json").write_text("[]", encoding="utf-8")
        (stage1_dir / "subtitles.json").write_text("[]", encoding="utf-8")

        config = {
            "common": {
                "movie_slug": "demo",
                "movie_title": "Demo Movie",
                "movie_dir": str(movie_dir),
                "style_path": str(style_path),
                "video_file": "movie.mp4",
                "subtitle_file": "movie.srt",
            }
        }

        paths = SimpleNamespace(
            style=style_path,
            synopsis=synopsis_path,
            visual_segments=stage0_dir / "visual_segments.json",
            subtitles_json=stage1_dir / "subtitles.json",
            story_prompt=tools_dir / "story_prompt.txt",
        )

        captured_args: list[str] = []

        monkeypatch.setattr(module, "load_config", lambda _config: config)
        monkeypatch.setattr(module, "build_paths", lambda _config: paths)
        monkeypatch.setattr(module, "ensure_stage_dirs", lambda _paths: None)
        monkeypatch.setattr(
            module,
            "build_story_prompt_main",
            lambda args: captured_args.extend(args) or 0,
        )

        exit_code = module.run()

    assert exit_code == 0
    assert "--synopsis" in captured_args
    assert str(synopsis_path.resolve()) in captured_args
