"""Transcribe audio files into plain-text transcript files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from faster_whisper import WhisperModel


DEFAULT_MODEL_SIZE = "large-v3"
DEFAULT_DEVICE = "cuda"
DEFAULT_OUTPUT_SUFFIX = ".txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="transcribe",
        description="Transcribe one audio file or a directory of audio files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input_path",
        nargs="?",
        type=Path,
        help="Audio file or directory to transcribe",
    )
    parser.add_argument(
        "--language",
        default="zh",
        help='Language code to force, or "auto" to let Whisper detect it',
    )
    return parser


def normalize_language(language: str | None) -> str | None:
    if language is None:
        return None

    cleaned = language.strip()
    if not cleaned or cleaned.lower() == "auto":
        return None

    return cleaned


def collect_input_files(input_path: Path) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    if input_path.is_file():
        return [input_path]

    if not input_path.is_dir():
        raise ValueError(f"Input path is not a file or directory: {input_path}")

    return sorted(input_path.rglob("*.mp3"))


def choose_compute_type(device: str) -> str:
    if "cuda" in device.lower():
        return "float16"
    return "int8"


def build_model(model_size: str, device: str) -> Any:
    return WhisperModel(
        model_size,
        device=device,
        compute_type=choose_compute_type(device),
    )


def write_transcript(output_path: Path, segments: Iterable[Any]) -> int:
    lines = [str(segment.text).strip() for segment in segments]
    lines = [line for line in lines if line]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def transcribe_file(
    source_path: Path,
    output_path: Path,
    model: Any,
    language: str | None,
) -> int:
    kwargs: dict[str, object] = {
        "beam_size": 5,
        "condition_on_previous_text": False,
    }
    if language is not None:
        kwargs["language"] = language

    segments, _info = model.transcribe(str(source_path), **kwargs)
    return write_transcript(output_path, segments)


def main(
    argv: Sequence[str] | None = None,
    *,
    model_factory: Callable[[str, str], Any] = build_model,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        language = normalize_language(args.language)
        input_path = args.input_path.expanduser()
        source_files = collect_input_files(input_path)
        if not source_files:
            raise ValueError(f"No matching .mp3 files found in {input_path}")

        pending_files = []
        for source_path in source_files:
            output_path = source_path.with_suffix(DEFAULT_OUTPUT_SUFFIX)
            if output_path.exists():
                print(f"Skipping existing transcript {output_path}")
                continue
            pending_files.append(source_path)

        if not pending_files:
            print(f"All transcripts already exist for {input_path}; nothing to do.")
            return 0

        model = model_factory(DEFAULT_MODEL_SIZE, DEFAULT_DEVICE)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    failures = 0
    for source_path in pending_files:
        output_path = source_path.with_suffix(DEFAULT_OUTPUT_SUFFIX)

        try:
            line_count = transcribe_file(
                source_path,
                output_path,
                model,
                language,
            )
        except Exception as exc:
            print(f"Error processing {source_path}: {exc}", file=sys.stderr)
            failures += 1
            continue

        print(f"Wrote {line_count} lines to {output_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
