from pathlib import Path

import pytest

from app.pipeline.stage3_generate_audio import (
    DEFAULT_REF_AUDIO,
    DEFAULT_REF_TEXT,
    build_voice_prompt,
    main,
    parse_script_chunks,
    prepare_reference_audio_for_prompt,
    resolve_voice_clone_mode,
)


def test_default_reference_files_exist() -> None:
    assert DEFAULT_REF_AUDIO.exists()
    assert DEFAULT_REF_TEXT.exists()


def test_main_allows_dry_run_without_explicit_reference_paths(tmp_path: Path) -> None:
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        "[TITLE] Demo\n[SCENE: 00:00:01 - 00:00:10]\n一段旁白\n",
        encoding="utf-8",
    )

    result = main(["--script", str(script_path), "--output-dir", str(tmp_path), "--dry-run"])

    assert result == 0


def test_parse_script_chunks_supports_grounded_scene_attributes() -> None:
    script_text = """
[TITLE] Demo
[HOOK]
[SCENE start=00:00:01.500 end=00:00:06.250 source=srt confidence=0.97 evidence=srt:12 characters="Yuta|Gojo"]
一段旁白
[SCENE source=ungrounded confidence=0.20 evidence=none characters="Yuta"]
另一段旁白
[CLOSING]
结尾
""".strip()

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 3
    assert chunks[0].scene_start == "00:00:01.500"
    assert chunks[0].scene_end == "00:00:06.250"
    assert chunks[0].scene_source == "srt"
    assert chunks[0].scene_confidence == 0.97
    assert chunks[0].scene_evidence == "srt:12"
    assert chunks[0].scene_characters == ["Yuta", "Gojo"]
    assert chunks[1].scene_start is None
    assert chunks[1].scene_source == "ungrounded"
    assert chunks[1].scene_characters == ["Yuta"]
    assert chunks[2].scene_start is None
    assert chunks[2].scene_source is None


def test_main_rejects_grounding_prompt_instead_of_final_script(tmp_path: Path, capsys) -> None:
    script_path = tmp_path / "script.txt"
    script_path.write_text(
        """
# Role
alignment editor

<<<BEATS_START>>>
[TITLE] Demo
[HOOK]
[BEAT 1] 第一段
<<<BEATS_END>>>

<<<SRT_REFERENCE_START>>>
[srt:001] 00:00:01.000 --> 00:00:03.000 :: 台词
<<<SRT_REFERENCE_END>>>
""".strip(),
        encoding="utf-8",
    )

    result = main(["--script", str(script_path), "--output-dir", str(tmp_path), "--dry-run"])

    captured = capsys.readouterr()
    assert result == 1
    assert "looks like the Stage 2 grounding prompt" in captured.err


def test_resolve_voice_clone_mode_auto_falls_back_to_x_vector_for_long_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.pipeline.stage3_generate_audio.probe_audio_duration",
        lambda _path: 682.15,
    )

    mode = resolve_voice_clone_mode(Path("dummy.mp3"), "auto", 30.0)

    assert mode == "x-vector"


def test_resolve_voice_clone_mode_auto_keeps_icl_for_short_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.pipeline.stage3_generate_audio.probe_audio_duration",
        lambda _path: 12.5,
    )

    mode = resolve_voice_clone_mode(Path("dummy.mp3"), "auto", 30.0)

    assert mode == "icl"


def test_prepare_reference_audio_for_prompt_trims_long_xvector_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref_audio = tmp_path / "ref.mp3"
    ref_audio.write_bytes(b"dummy")
    ffmpeg_calls: list[list[str]] = []

    monkeypatch.setattr(
        "app.pipeline.stage3_generate_audio.probe_audio_duration",
        lambda _path: 682.15,
    )

    def fake_run(command: list[str], check: bool) -> None:
        assert check is True
        ffmpeg_calls.append(command)
        Path(command[-1]).write_bytes(b"trimmed")

    monkeypatch.setattr("app.pipeline.stage3_generate_audio.subprocess.run", fake_run)

    prepared_ref_audio, duration_s = prepare_reference_audio_for_prompt(
        ref_audio,
        "x-vector",
        30.0,
        tmp_path,
    )

    assert duration_s == 682.15
    assert prepared_ref_audio == tmp_path / "ref.xvector_30s.wav"
    assert ffmpeg_calls
    assert ffmpeg_calls[0][-1] == str(prepared_ref_audio)


def test_build_voice_prompt_ignores_missing_transcript_in_xvector_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyModel:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create_voice_clone_prompt(self, **kwargs: object) -> dict[str, object]:
            self.calls.append(kwargs)
            return {"ok": True}

    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"audio")
    trimmed_audio = tmp_path / "trimmed.wav"
    trimmed_audio.write_bytes(b"trimmed")

    monkeypatch.setattr(
        "app.pipeline.stage3_generate_audio.resolve_voice_clone_mode",
        lambda _ref_audio, _requested_mode, _max_seconds: "x-vector",
    )
    monkeypatch.setattr(
        "app.pipeline.stage3_generate_audio.prepare_reference_audio_for_prompt",
        lambda _ref_audio, _resolved_mode, _max_seconds, _scratch_dir: (trimmed_audio, 682.15),
    )

    model = DummyModel()
    result = build_voice_prompt(
        model,
        ref_audio,
        tmp_path / "missing.txt",
        tmp_path,
    )

    assert result == {"ok": True}
    assert model.calls == [
        {
            "ref_audio": str(trimmed_audio),
            "ref_text": None,
            "x_vector_only_mode": True,
        }
    ]