from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.transcribe import build_output_path, collect_input_files, main


@dataclass(slots=True)
class FakeSegment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
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


def test_collect_input_files_filters_and_sorts(tmp_path: Path):
    top_level = tmp_path / "a.mp3"
    top_level.write_text("audio", encoding="utf-8")

    ignored = tmp_path / "b.wav"
    ignored.write_text("audio", encoding="utf-8")

    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    nested_file = nested_dir / "c.mp3"
    nested_file.write_text("audio", encoding="utf-8")

    assert collect_input_files(tmp_path, (".mp3",), recursive=False) == [top_level]
    assert collect_input_files(tmp_path, (".mp3",), recursive=True) == [top_level, nested_file]
    assert collect_input_files(top_level, (".mp3",), recursive=True) == [top_level]


def test_build_output_path_mirrors_directory_structure(tmp_path: Path):
    source_root = tmp_path / "source"
    nested_dir = source_root / "nested"
    nested_dir.mkdir(parents=True)

    source_file = nested_dir / "clip.mp3"
    source_file.write_text("audio", encoding="utf-8")

    output_dir = tmp_path / "output"
    destination = build_output_path(
        source_file,
        input_root=source_root,
        output_dir=output_dir,
        output_suffix=".txt",
    )

    assert destination == output_dir / "nested" / "clip.txt"


def test_main_transcribes_directory_with_injected_model(tmp_path: Path):
    source_root = tmp_path / "source"
    nested_dir = source_root / "nested"
    nested_dir.mkdir(parents=True)

    first_file = source_root / "first.mp3"
    first_file.write_text("audio", encoding="utf-8")
    second_file = nested_dir / "second.mp3"
    second_file.write_text("audio", encoding="utf-8")

    output_dir = tmp_path / "transcripts"
    fake_model = FakeModel()

    exit_code = main(
        [
            str(source_root),
            "--recursive",
            "--output-dir",
            str(output_dir),
        ],
        model_factory=lambda model_size, device, compute_type: fake_model,
    )

    assert exit_code == 0
    assert (output_dir / "first.txt").read_text(encoding="utf-8") == "hello\nworld\n"
    assert (output_dir / "nested" / "second.txt").read_text(encoding="utf-8") == "hello\nworld\n"
    assert len(fake_model.calls) == 2
    first_call_path, first_call_kwargs = fake_model.calls[0]
    assert first_call_path == first_file
    assert first_call_kwargs["beam_size"] == 5
    assert first_call_kwargs["language"] == "zh"
    assert first_call_kwargs["condition_on_previous_text"] is False