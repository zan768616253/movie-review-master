from pathlib import Path

import pytest

from app.pipeline.stage3_generate_audio import (
    DEFAULT_STYLE_PATH,
    build_voice_prompt,
    main,
    parse_script_chunks,
    resolve_output_tag,
    resolve_voice_reference,
)


def test_default_style_reference_files_exist() -> None:
    voice_reference = resolve_voice_reference(DEFAULT_STYLE_PATH, None, None)

    assert DEFAULT_STYLE_PATH.exists()
    assert voice_reference.reference_dir == DEFAULT_STYLE_PATH.parent / "voice-assets" / "niu-shu" / "reference"
    assert voice_reference.audio_path.exists()
    assert voice_reference.text_path.exists()


def test_resolve_voice_reference_uses_style_stem_directory() -> None:
    voice_reference = resolve_voice_reference(Path("styles/first-person-pov.md"), None, None)

    assert voice_reference.reference_dir == Path("styles/voice-assets/first-person-pov/reference")
    assert voice_reference.audio_path == Path("styles/voice-assets/first-person-pov/reference/clone_reference.mp3")
    assert voice_reference.text_path == Path("styles/voice-assets/first-person-pov/reference/clone_reference.txt")


def test_resolve_voice_reference_prefers_explicit_overrides(tmp_path: Path) -> None:
    ref_audio = tmp_path / "custom.mp3"
    ref_text = tmp_path / "custom.txt"
    ref_audio.write_bytes(b"audio")
    ref_text.write_text("hello", encoding="utf-8")

    voice_reference = resolve_voice_reference(DEFAULT_STYLE_PATH, ref_audio, ref_text)

    assert voice_reference.audio_path == ref_audio.resolve()
    assert voice_reference.text_path == ref_text.resolve()


def test_resolve_output_tag_defaults_to_style_stem() -> None:
    assert resolve_output_tag(Path("styles/first-person-pov.md"), None) == "first-person-pov"
    assert resolve_output_tag(Path("styles/first-person-pov.md"), "custom-tag") == "custom-tag"


def test_main_uses_style_default_reference_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        '[TITLE] Demo\n[HOOK]\n[ANCHOR ranges="00:00:01.000-00:00:10.000"]\n一段旁白\n',
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.pipeline.stage3_generate_audio.load_model", lambda: object())

    def fake_build_voice_prompt(model, ref_audio, ref_text_path):
        captured["model"] = model
        captured["ref_audio"] = ref_audio
        captured["ref_text_path"] = ref_text_path
        return {"prompt": True}

    def fake_run_full_generation(model, chunks, voice_prompt, mp3_path, manifest_path):
        captured["run_model"] = model
        captured["chunks"] = chunks
        captured["voice_prompt"] = voice_prompt
        captured["mp3_path"] = mp3_path
        captured["manifest_path"] = manifest_path

    monkeypatch.setattr("app.pipeline.stage3_generate_audio.build_voice_prompt", fake_build_voice_prompt)
    monkeypatch.setattr("app.pipeline.stage3_generate_audio.run_full_generation", fake_run_full_generation)

    result = main(["--script", str(script_path), "--output-dir", str(tmp_path)])
    voice_reference = resolve_voice_reference(DEFAULT_STYLE_PATH, None, None)

    assert result == 0
    assert captured["ref_audio"] == voice_reference.audio_path
    assert captured["ref_text_path"] == voice_reference.text_path


def test_main_expands_user_script_and_output_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        '[TITLE] Demo\n[HOOK]\n[ANCHOR ranges="00:00:01.000-00:00:10.000"]\n一段旁白\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.pipeline.stage3_generate_audio.load_model", lambda: object())
    monkeypatch.setattr(
        "app.pipeline.stage3_generate_audio.build_voice_prompt",
        lambda model, ref_audio, ref_text_path: {"prompt": True},
    )

    def fake_print_chunk_summary(script_file: Path, chunks: list[object]) -> None:
        captured["script_path"] = script_file
        captured["chunk_count"] = len(chunks)

    def fake_run_full_generation(model, chunks, voice_prompt, mp3_path, manifest_path):
        captured["mp3_path"] = mp3_path
        captured["manifest_path"] = manifest_path

    monkeypatch.setattr("app.pipeline.stage3_generate_audio.print_chunk_summary", fake_print_chunk_summary)
    monkeypatch.setattr("app.pipeline.stage3_generate_audio.run_full_generation", fake_run_full_generation)

    result = main(["--script", "~/script.txt", "--output-dir", "~/stage3-out"])

    assert result == 0
    assert captured["script_path"] == script_path.resolve()
    assert captured["chunk_count"] == 1
    assert captured["mp3_path"] == (tmp_path / "stage3-out" / "voiceover_niu-shu_voiceclone.mp3").resolve()
    assert captured["manifest_path"] == (
        tmp_path / "stage3-out" / "voiceover_niu-shu_voiceclone.manifest.json"
    ).resolve()


def test_main_reports_missing_style_reference_audio(tmp_path: Path, capsys) -> None:
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        '[TITLE] Demo\n[HOOK]\n[ANCHOR ranges="00:00:01.000-00:00:10.000"]\n一段旁白\n',
        encoding="utf-8",
    )

    result = main([
        "--script",
        str(script_path),
        "--style",
        str(Path("styles/first-person-pov.md")),
        "--output-dir",
        str(tmp_path),
    ])

    captured = capsys.readouterr()
    assert result == 1
    assert "Reference audio not found:" in captured.err
    assert "styles/voice-assets/first-person-pov/reference" in captured.err
    assert "pass --ref-audio" in captured.err


def test_parse_script_chunks_handles_anchored_script_with_multi_range_and_closing() -> None:
    script_text = """
[TITLE] Demo
[HOOK]
[ANCHOR ranges="00:00:01.500-00:00:06.250" characters="Yuta|Gojo"]
一段旁白
[ACT 1 - SETUP]
[ANCHOR ranges="00:00:10.000-00:00:14.000, 00:00:20.000-00:00:24.000" characters="Yuta"]
多镜头旁白
[CLOSING]
结尾
""".strip()

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 3
    # First chunk: single-range anchor.
    assert chunks[0].ranges == [("00:00:01.500", "00:00:06.250")]
    assert chunks[0].characters == ["Yuta", "Gojo"]
    assert chunks[0].first_range_start == "00:00:01.500"
    assert chunks[0].text == "一段旁白"
    # Second chunk: multi-range anchor — both ranges round-trip.
    assert chunks[1].ranges == [
        ("00:00:10.000", "00:00:14.000"),
        ("00:00:20.000", "00:00:24.000"),
    ]
    assert chunks[1].characters == ["Yuta"]
    # Third chunk: closing — no anchor, narration still present.
    assert chunks[2].ranges == []
    assert chunks[2].characters == []
    assert chunks[2].first_range_start is None
    assert chunks[2].text == "结尾"


def test_parse_script_chunks_ignores_title_section_until_hook() -> None:
    script_text = """
[TITLE] Demo
[ANCHOR ranges="00:00:00.000-00:00:02.000"]
片名旁白，不应该被读
[HOOK]
[ANCHOR ranges="00:00:03.000-00:00:05.000"]
真正开场旁白
""".strip()

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 1
    assert chunks[0].ranges == [("00:00:03.000", "00:00:05.000")]
    assert chunks[0].text == "真正开场旁白"


def test_write_manifest_emits_new_schema(tmp_path: Path) -> None:
    from app.pipeline.stage3_generate_audio import write_manifest

    script_text = (
        "[TITLE] Demo\n"
        "[HOOK]\n"
        '[ANCHOR ranges="00:00:01.000-00:00:05.000" characters="Hero"]\n'
        "narration A\n"
        "[CLOSING]\n"
        "closing narration\n"
    )
    chunks = parse_script_chunks(script_text)
    audio_ranges = [(0.0, 2.0), (2.0, 3.5)]

    out = tmp_path / "manifest.json"
    write_manifest(chunks, audio_ranges, out)

    import json
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload[0] == {
        "index": 1,
        "ranges": [["00:00:01.000", "00:00:05.000"]],
        "characters": ["Hero"],
        "text": "narration A",
        "audio_start_s": 0.0,
        "audio_end_s": 2.0,
    }
    assert payload[1]["ranges"] == []  # closing chunk
    assert payload[1]["text"] == "closing narration"


def test_build_voice_prompt_passes_full_transcript_text(tmp_path: Path) -> None:
    class DummyModel:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create_voice_clone_prompt(self, **kwargs: object) -> dict[str, object]:
            self.calls.append(kwargs)
            return {"ok": True}

    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"audio")
    ref_text = tmp_path / "ref.txt"
    ref_text.write_text("完整参考文本", encoding="utf-8")

    model = DummyModel()
    result = build_voice_prompt(
        model,
        ref_audio,
        ref_text,
    )

    assert result == {"ok": True}
    assert model.calls == [
        {
            "ref_audio": str(ref_audio),
            "ref_text": "完整参考文本",
        }
    ]


def test_build_voice_prompt_requires_transcript_file(tmp_path: Path) -> None:
    class DummyModel:
        def create_voice_clone_prompt(self, **kwargs: object) -> dict[str, object]:
            raise AssertionError("create_voice_clone_prompt should not be called when the transcript is missing")

    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"audio")

    with pytest.raises(FileNotFoundError):
        build_voice_prompt(
            DummyModel(),
            ref_audio,
            tmp_path / "missing.txt",
        )