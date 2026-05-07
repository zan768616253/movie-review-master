from __future__ import annotations

import importlib.util
import json
import tempfile

from pathlib import Path
from types import SimpleNamespace

from app.tools.generate_audio_subtitles import (
    build_proportional_timed_chunks,
    main,
    split_text_into_cues,
)
from app.tools.generate_script_audio import parse_script_chunks


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "tmp" / "tools" / "generate_audio_subtitles.py"


def load_harness_module():
    spec = importlib.util.spec_from_file_location("tmp_generate_audio_subtitles_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_split_text_into_cues_respects_max_chars() -> None:
    cues = split_text_into_cues("注意看，有人来了。快跑，不然来不及了。", max_chars_per_cue=6)

    assert cues == [
        "注意看，",
        "有人来了。",
        "快跑，",
        "不然来不及了。",
    ]


def test_build_proportional_timed_chunks_uses_script_weights() -> None:
    chunks = parse_script_chunks(
        """
[HOOK]
你好

[ACT 1]
这一句更长一点
"""
    )

    timed_chunks = build_proportional_timed_chunks(chunks, total_audio_s=10.0)

    assert len(timed_chunks) == 2
    assert timed_chunks[0].start_s == 0.0
    assert round(timed_chunks[0].end_s, 3) == 2.222
    assert round(timed_chunks[1].start_s, 3) == 2.222
    assert round(timed_chunks[1].end_s, 3) == 10.0


def test_main_writes_srt_using_manifest_timing(tmp_path: Path) -> None:
    script_path = tmp_path / "scripts.txt"
    script_path.write_text(
        """
[HOOK]
注意看，有人来了。

[CLOSING]
我们下期再见。
""".strip()
        + "\n",
        encoding="utf-8",
    )
    audio_path = tmp_path / "voiceover_demo.mp3"
    audio_path.write_bytes(b"audio")
    manifest_path = tmp_path / "voiceover_demo.manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "index": 1,
                    "text": "注意看，有人来了。",
                    "audio_start_s": 0.0,
                    "audio_end_s": 1.25,
                },
                {
                    "index": 2,
                    "text": "我们下期再见。",
                    "audio_start_s": 1.25,
                    "audio_end_s": 2.5,
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "voiceover_demo.srt"

    exit_code = main(
        [
            "--script",
            str(script_path),
            "--audio",
            str(audio_path),
            "--manifest",
            str(manifest_path),
            "--out",
            str(output_path),
            "--max-chars-per-cue",
            "50",
        ],
        probe_duration_fn=lambda _path: (_ for _ in ()).throw(AssertionError("probe should not run")),
    )

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == (
        "1\n"
        "00:00:00,000 --> 00:00:01,250\n"
        "注意看，有人来了。\n\n"
        "2\n"
        "00:00:01,250 --> 00:00:02,500\n"
        "我们下期再见。\n"
    )


def test_main_falls_back_to_audio_duration_when_manifest_missing(tmp_path: Path) -> None:
    script_path = tmp_path / "scripts.txt"
    script_path.write_text(
        """
[HOOK]
你好

[ACT 1]
这一句更长一点
""".strip()
        + "\n",
        encoding="utf-8",
    )
    audio_path = tmp_path / "voiceover_demo.mp3"
    audio_path.write_bytes(b"audio")
    output_path = tmp_path / "voiceover_demo.vtt"

    exit_code = main(
        [
            "--script",
            str(script_path),
            "--audio",
            str(audio_path),
            "--out",
            str(output_path),
            "--format",
            "vtt",
            "--max-chars-per-cue",
            "50",
        ],
        probe_duration_fn=lambda _path: 10.0,
    )

    assert exit_code == 0
    written = output_path.read_text(encoding="utf-8")
    assert written.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:02.222" in written
    assert "00:00:02.222 --> 00:00:10.000" in written


def test_harness_requires_audio(monkeypatch) -> None:
    module = load_harness_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tools_dir = root / "tmp" / "work" / "demo" / "tools"
        style_path = root / "styles" / "demo-style.md"
        script_path = tools_dir / "scripts.txt"

        tools_dir.mkdir(parents=True)
        style_path.parent.mkdir(parents=True)
        style_path.write_text("# Demo Style\n", encoding="utf-8")
        script_path.write_text("[HOOK]\n一句话\n", encoding="utf-8")

        config = {
            "common": {
                "movie_slug": "demo",
                "movie_title": "Demo Movie",
                "movie_dir": str(root / "movies" / "demo"),
                "style_path": str(style_path),
                "video_file": "movie.mp4",
                "subtitle_file": "movie.srt",
            }
        }
        paths = SimpleNamespace(style=style_path, tools_dir=tools_dir)

        monkeypatch.setattr(module, "load_config", lambda _config: config)
        monkeypatch.setattr(module, "build_paths", lambda _config: paths)
        monkeypatch.setattr(module, "ensure_stage_dirs", lambda _paths: None)

        exit_code = module.run()

    assert exit_code == 1


def test_harness_passes_manifest_and_overrides(monkeypatch) -> None:
    module = load_harness_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        movie_dir = root / "movies" / "demo"
        tools_dir = root / "tmp" / "work" / "demo" / "tools"
        audio_dir = tools_dir / "audio"
        style_path = root / "styles" / "demo-style.md"
        script_path = tools_dir / "scripts.txt"
        audio_path = audio_dir / "voiceover_demo-voice.mp3"
        manifest_path = audio_dir / "voiceover_demo-voice.manifest.json"

        movie_dir.mkdir(parents=True)
        tools_dir.mkdir(parents=True)
        audio_dir.mkdir(parents=True)
        style_path.parent.mkdir(parents=True)

        style_path.write_text("# Demo Style\n", encoding="utf-8")
        script_path.write_text("[HOOK]\n一句话\n", encoding="utf-8")
        audio_path.write_bytes(b"audio")
        manifest_path.write_text("[]", encoding="utf-8")

        config = {
            "common": {
                "movie_slug": "demo",
                "movie_title": "Demo Movie",
                "movie_dir": str(movie_dir),
                "style_path": str(style_path),
                "video_file": "movie.mp4",
                "subtitle_file": "movie.srt",
            },
            "tools": {
                "generate_script_audio": {
                    "out_dir": str(audio_dir),
                    "tag": "demo-voice",
                },
                "generate_audio_subtitles": {
                    "format": "vtt",
                    "max_chars_per_cue": 30,
                },
            },
        }
        paths = SimpleNamespace(style=style_path, tools_dir=tools_dir)
        captured_args: list[str] = []

        monkeypatch.setattr(module, "load_config", lambda _config: config)
        monkeypatch.setattr(module, "build_paths", lambda _config: paths)
        monkeypatch.setattr(module, "ensure_stage_dirs", lambda _paths: None)
        monkeypatch.setattr(
            module,
            "generate_audio_subtitles_main",
            lambda args: captured_args.extend(args) or 0,
        )

        exit_code = module.run()

    assert exit_code == 0
    assert "--script" in captured_args
    assert str(script_path) in captured_args
    assert "--audio" in captured_args
    assert str(audio_path.resolve()) in captured_args
    assert "--manifest" in captured_args
    assert str(manifest_path.resolve()) in captured_args
    assert "--format" in captured_args
    assert "vtt" in captured_args
    assert "--max-chars-per-cue" in captured_args
    assert "30" in captured_args
