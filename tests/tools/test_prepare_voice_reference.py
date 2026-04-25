from __future__ import annotations

import json
from pathlib import Path

from app.tools.prepare_voice_reference import main


def make_style(tmp_path: Path) -> tuple[Path, Path]:
    styles_dir = tmp_path / "styles"
    styles_dir.mkdir()
    style_path = styles_dir / "demo-style.md"
    style_path.write_text("# Demo Style\n", encoding="utf-8")
    reference_dir = styles_dir / "voice-assets" / "demo-style" / "reference"
    return style_path, reference_dir


def test_main_prepares_reference_bundle_with_explicit_transcript(tmp_path: Path) -> None:
    style_path, reference_dir = make_style(tmp_path)
    source_audio = tmp_path / "source.wav"
    source_audio.write_bytes(b"audio")
    transcript_path = tmp_path / "source.txt"
    transcript_path.write_text("  你好世界  \n", encoding="utf-8")

    ffmpeg_calls: list[list[str]] = []

    def fake_run(command: list[str], check: bool) -> None:
        assert check is True
        ffmpeg_calls.append(command)
        Path(command[-1]).write_bytes(b"prepared")

    def fake_analyze(audio_path: Path, text_path: Path) -> dict[str, object]:
        assert audio_path == reference_dir / "clone_reference.mp3"
        assert text_path == reference_dir / "clone_reference.txt"
        return {
            "audio_path": str(audio_path),
            "transcript_path": str(text_path),
            "total_duration_s": 6.2,
            "sample_rate": 24000,
        }

    exit_code = main(
        [
            str(source_audio),
            "--style",
            str(style_path),
            "--transcript",
            str(transcript_path),
        ],
        analyze_fn=fake_analyze,
        probe_duration_fn=lambda _path: 6.2,
        run_cmd=fake_run,
    )

    assert exit_code == 0
    assert (reference_dir / "clone_reference.mp3").read_bytes() == b"prepared"
    assert (reference_dir / "clone_reference.txt").read_text(encoding="utf-8") == "你好世界\n"

    payload = json.loads((reference_dir / "clone_reference.analysis.json").read_text(encoding="utf-8"))
    assert payload["prepared_for_stage3_icl"] is True
    assert payload["reference_target_seconds"] == 90.0
    assert payload["recommended_for_icl"] is True
    assert payload["source_audio_path"] == str(source_audio.resolve())
    assert payload["source_transcript_path"] == str(transcript_path.resolve())
    assert ffmpeg_calls
    assert ffmpeg_calls[0][0] == "ffmpeg"


def test_main_rejects_long_source_without_clip_window(tmp_path: Path, capsys) -> None:
    style_path, _reference_dir = make_style(tmp_path)
    source_audio = tmp_path / "long.wav"
    source_audio.write_bytes(b"audio")

    exit_code = main(
        [
            str(source_audio),
            "--style",
            str(style_path),
        ],
        probe_duration_fn=lambda _path: 120.0,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Pass --start/--end or trim the clip first." in captured.err


def test_main_extracts_clip_and_auto_transcribes_when_transcript_missing(tmp_path: Path) -> None:
    style_path, reference_dir = make_style(tmp_path)
    source_audio = tmp_path / "movie.wav"
    source_audio.write_bytes(b"audio")
    fake_model = object()
    ffmpeg_calls: list[list[str]] = []
    model_factory_calls: list[tuple[str, str]] = []
    transcribe_calls: list[tuple[Path, Path, object, str | None]] = []

    def fake_run(command: list[str], check: bool) -> None:
        assert check is True
        ffmpeg_calls.append(command)
        Path(command[-1]).write_bytes(b"prepared")

    def fake_model_factory(model_size: str, device: str) -> object:
        model_factory_calls.append((model_size, device))
        return fake_model

    def fake_transcribe_file(audio_path: Path, output_path: Path, model: object, language: str | None) -> int:
        transcribe_calls.append((audio_path, output_path, model, language))
        output_path.write_text("自动转写\n", encoding="utf-8")
        return 1

    def fake_analyze(audio_path: Path, text_path: Path) -> dict[str, object]:
        assert audio_path == reference_dir / "clone_reference.mp3"
        assert text_path == reference_dir / "clone_reference.txt"
        return {
            "audio_path": str(audio_path),
            "transcript_path": str(text_path),
            "total_duration_s": 8.0,
            "sample_rate": 24000,
        }

    exit_code = main(
        [
            str(source_audio),
            "--style",
            str(style_path),
            "--start",
            "00:01:05",
        ],
        model_factory=fake_model_factory,
        transcribe_file_fn=fake_transcribe_file,
        analyze_fn=fake_analyze,
        probe_duration_fn=lambda _path: 120.0,
        run_cmd=fake_run,
    )

    assert exit_code == 0
    assert model_factory_calls == [("large-v3", "cuda")]
    assert len(transcribe_calls) == 1
    prepared_audio_path, output_text_path, model, language = transcribe_calls[0]
    assert prepared_audio_path == reference_dir / "clone_reference.mp3"
    assert output_text_path == reference_dir / "clone_reference.txt"
    assert model is fake_model
    assert language == "zh"
    assert (reference_dir / "clone_reference.txt").read_text(encoding="utf-8") == "自动转写\n"

    assert len(ffmpeg_calls) == 1
    command = ffmpeg_calls[0]
    assert command[command.index("-ss") + 1] == "65.000"
    assert command[command.index("-t") + 1] == "55.000"
