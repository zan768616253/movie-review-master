from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.transcribe import collect_input_files, main


@dataclass
class FakeSegment:
    start: float
    end: float
    text: str


@dataclass
class FakeInfo:
    language: str = "zh"
    duration: float = 0.0


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, dict[str, object]]] = []

    def transcribe(self, audio_path: str, **kwargs):
        self.calls.append((Path(audio_path), kwargs))
        segments = iter(
            [
                FakeSegment(0.0, 1.2, " hello "),
                FakeSegment(1.2, 2.5, "world"),
            ]
        )
        return segments, FakeInfo()


def test_collect_input_files_recursively_finds_mp3(tmp_path: Path):
    top_level = tmp_path / "a.mp3"
    top_level.write_text("audio", encoding="utf-8")

    ignored = tmp_path / "b.wav"
    ignored.write_text("audio", encoding="utf-8")

    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "c.mp3"
    nested_file.write_text("audio", encoding="utf-8")

    # Should find both mp3 files but ignore wav
    assert collect_input_files(tmp_path) == [top_level, nested_file]
    
    # Passing a single file works too
    assert collect_input_files(top_level) == [top_level]





def test_main_transcribes_directory_with_injected_model(tmp_path: Path):
    source_root = tmp_path / "source"
    nested_dir = source_root / "nested"
    nested_dir.mkdir(parents=True)

    first_file = source_root / "first.mp3"
    first_file.write_text("audio", encoding="utf-8")
    second_file = nested_dir / "second.mp3"
    second_file.write_text("audio", encoding="utf-8")

    fake_model = FakeModel()

    exit_code = main(
        [
            str(source_root),
        ],
        model_factory=lambda model_size, device: fake_model,
    )

    assert exit_code == 0
    # Transcripts should be next to the mp3 files
    assert (source_root / "first.txt").read_text(encoding="utf-8") == "hello\nworld\n"
    assert (nested_dir / "second.txt").read_text(encoding="utf-8") == "hello\nworld\n"
    assert len(fake_model.calls) == 2
    first_call_path, first_call_kwargs = fake_model.calls[0]
    assert first_call_path == first_file
    assert first_call_kwargs["beam_size"] == 5
    assert first_call_kwargs["language"] == "zh"
    assert first_call_kwargs["condition_on_previous_text"] is False