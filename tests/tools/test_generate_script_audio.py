from __future__ import annotations

import importlib.util
import tempfile
import numpy as np

from pathlib import Path
from types import SimpleNamespace

from app.tools.generate_script_audio import (
    Chunk,
    build_voice_prompt,
    generate_chunks,
    parse_script_chunks,
    split_text_for_tts,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS_PATH = REPO_ROOT / "tmp" / "tools" / "generate_script_audio.py"


def load_harness_module():
    spec = importlib.util.spec_from_file_location("tmp_generate_script_audio_harness", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_script_chunks_plain_script_uses_structural_sections() -> None:
    script_text = """
[TITLE]
连环杀局

[HOOK]
注意看
有钱人为了活命能有多疯狂

[ACT 1 - SETUP]
老洪需要换心
永强被送进黑狱

[CLOSING]
我们下期再见
"""

    chunks = parse_script_chunks(script_text)

    assert [(chunk.section, chunk.text) for chunk in chunks] == [
        ("HOOK", "注意看\n有钱人为了活命能有多疯狂"),
        ("ACT 1 - SETUP", "老洪需要换心\n永强被送进黑狱"),
        ("CLOSING", "我们下期再见"),
    ]
    assert all(chunk.ranges == [] for chunk in chunks)


def test_parse_script_chunks_anchored_script_preserves_anchor_metadata() -> None:
    script_text = """
[TITLE]
Demo

[HOOK]
[ANCHOR ranges="00:00:01-00:00:05" characters="永强, 铁柱"]
第一句
第二句

[ACT 1 - SETUP]
[ANCHOR ranges="00:00:06-00:00:09, 00:00:10-00:00:12"]
第三句

[CLOSING]
收尾一句
"""

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 3
    assert chunks[0].section == "HOOK"
    assert chunks[0].ranges == [("00:00:01", "00:00:05")]
    assert chunks[0].characters == ["永强", "铁柱"]
    assert chunks[0].text == "第一句\n第二句"
    assert chunks[1].section == "ACT 1 - SETUP"
    assert chunks[1].ranges == [
        ("00:00:06", "00:00:09"),
        ("00:00:10", "00:00:12"),
    ]
    assert chunks[2].section == "CLOSING"
    assert chunks[2].ranges == []
    assert chunks[2].text == "收尾一句"


def test_harness_requires_script(monkeypatch) -> None:
    module = load_harness_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tools_dir = root / "tmp" / "work" / "demo" / "tools"
        style_path = root / "styles" / "demo-style.md"

        tools_dir.mkdir(parents=True)
        style_path.parent.mkdir(parents=True)
        style_path.write_text("# Demo Style\n", encoding="utf-8")

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


def test_harness_passes_voice_overrides_to_tool(monkeypatch) -> None:
    module = load_harness_module()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        movie_dir = root / "movies" / "demo"
        tools_dir = root / "tmp" / "work" / "demo" / "tools"
        output_dir = tools_dir / "audio"
        style_path = root / "styles" / "demo-style.md"
        script_path = tools_dir / "scripts.txt"
        ref_audio = root / "voice" / "speaker.mp3"
        ref_text = root / "voice" / "speaker.txt"

        movie_dir.mkdir(parents=True)
        tools_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        style_path.parent.mkdir(parents=True)
        ref_audio.parent.mkdir(parents=True)

        style_path.write_text("# Demo Style\n", encoding="utf-8")
        script_path.write_text("[HOOK]\n一句话\n", encoding="utf-8")
        ref_audio.write_bytes(b"audio")
        ref_text.write_text("参考文案\n", encoding="utf-8")

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
                    "out_dir": str(output_dir),
                    "ref_audio": str(ref_audio),
                    "ref_text": str(ref_text),
                    "tag": "demo-voice",
                    "max_chars_per_request": 180,
                }
            },
        }
        paths = SimpleNamespace(style=style_path, tools_dir=tools_dir)
        captured_args: list[str] = []

        monkeypatch.setattr(module, "load_config", lambda _config: config)
        monkeypatch.setattr(module, "build_paths", lambda _config: paths)
        monkeypatch.setattr(module, "ensure_stage_dirs", lambda _paths: None)
        monkeypatch.setattr(
            module,
            "generate_script_audio_main",
            lambda args: captured_args.extend(args) or 0,
        )

        exit_code = module.run()

    assert exit_code == 0
    assert "--script" in captured_args
    assert str(script_path) in captured_args
    assert "--output-dir" in captured_args
    assert str(output_dir.resolve()) in captured_args
    assert "--ref-audio" in captured_args
    assert str(ref_audio.resolve()) in captured_args
    assert "--ref-text" in captured_args
    assert str(ref_text.resolve()) in captured_args
    assert "--tag" in captured_args
    assert "demo-voice" in captured_args
    assert "--max-chars-per-request" in captured_args
    assert "180" in captured_args


def test_build_voice_prompt_uses_icl_transcript(tmp_path: Path) -> None:
    ref_audio = tmp_path / "ref.mp3"
    ref_audio.write_bytes(b"audio")
    ref_text = tmp_path / "ref.txt"
    ref_text.write_text("你好世界\n", encoding="utf-8")

    class FakeModel:
        def __init__(self) -> None:
            self.kwargs = None

        def create_voice_clone_prompt(self, **kwargs):
            self.kwargs = kwargs
            return object()

    model = FakeModel()

    build_voice_prompt(
        model,
        ref_audio,
        ref_text,
    )

    assert model.kwargs == {
        "ref_audio": str(ref_audio),
        "ref_text": "你好世界",
    }


def test_split_text_for_tts_keeps_requests_within_limit() -> None:
    text = "\n".join(
        [
            "第一句比较短。",
            "第二句也比较短。",
            "第三句稍微长一点但是还在可控范围内。",
            "第四句继续往下说，方便测试换段。",
        ]
    )

    requests = split_text_for_tts(text, max_chars_per_request=20)

    assert requests == [
        "第一句比较短。\n第二句也比较短。",
        "第三句稍微长一点但是还在可控范围内。",
        "第四句继续往下说，方便测试换段。",
    ]
    assert all(len(request) <= 20 for request in requests)


def test_generate_chunks_splits_long_chunk_but_keeps_manifest_granularity() -> None:
    chunk = Chunk(
        index=1,
        section="ACT 2",
        text="\n".join(
            [
                "甲" * 40 + "。",
                "乙" * 40 + "。",
                "丙" * 40 + "。",
            ]
        ),
    )

    class FakeModel:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_voice_clone(self, **kwargs):
            self.calls.append(kwargs)
            return [np.ones(24, dtype=np.float32)], 12

    model = FakeModel()
    wavs, sample_rate = generate_chunks(
        model,
        [chunk],
        voice_prompt=object(),
        max_chars_per_request=90,
    )

    assert len(wavs) == 1
    assert sample_rate == 12
    assert len(model.calls) == 2
    assert all(len(str(call["text"])) <= 90 for call in model.calls)
    assert len(wavs[0]) == 48


def test_generate_chunks_retries_with_smaller_requests_when_model_hits_cap() -> None:
    chunk = Chunk(
        index=1,
        section="ACT 3",
        text=("甲" * 45 + "。\n" + "乙" * 45 + "。"),
    )

    class FakeModel:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_voice_clone(self, **kwargs):
            self.calls.append(kwargs)
            text = str(kwargs["text"])
            max_new_tokens = int(kwargs["max_new_tokens"])
            if len(text) > 80:
                return [np.ones(max_new_tokens, dtype=np.float32)], 12
            return [np.ones(120, dtype=np.float32)], 12

    model = FakeModel()
    wavs, sample_rate = generate_chunks(
        model,
        [chunk],
        voice_prompt=object(),
        max_chars_per_request=120,
    )

    assert len(wavs) == 1
    assert sample_rate == 12
    assert len(model.calls) == 3
    assert len(str(model.calls[0]["text"])) > 80
    assert all(len(str(call["text"])) <= 80 for call in model.calls[1:])
    assert len(wavs[0]) == 240
