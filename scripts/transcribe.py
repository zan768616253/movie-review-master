"""Transcribe audio files into plain-text transcript files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


DEFAULT_MODEL_SIZE = "large-v3"
DEFAULT_DEVICE = "cuda"
DEFAULT_BEAM_SIZE = 5
DEFAULT_LANGUAGE = "zh"
DEFAULT_OUTPUT_SUFFIX = ".txt"
DEFAULT_EXTENSIONS = (".mp3",)


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
    parser.add_argument("--model-size", default=DEFAULT_MODEL_SIZE, help="Whisper model name or local path")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Device for faster-whisper, such as cuda or cpu")
    parser.add_argument("--compute-type", default=None, help="Optional faster-whisper compute type")
    parser.add_argument("--beam-size", type=int, default=DEFAULT_BEAM_SIZE, help="Beam size for decoding")
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help='Language code to force, or "auto" to let Whisper detect it',
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Recurse into subdirectories when input_path is a directory",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=list(DEFAULT_EXTENSIONS),
        metavar="EXT",
        help="File extensions to include when scanning a directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory for generated transcript files",
    )
    return parser


def normalize_language(language: str | None) -> str | None:
    if language is None:
        return None

    cleaned = language.strip()
    if not cleaned or cleaned.lower() == "auto":
        return None

    return cleaned


def normalize_extensions(extensions: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []

    for extension in extensions:
        cleaned = extension.strip().lower()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        if cleaned not in normalized:
            normalized.append(cleaned)

    if not normalized:
        raise ValueError("At least one file extension must be provided")

    return tuple(normalized)


def choose_compute_type(device: str, compute_type: str | None) -> str:
    if compute_type:
        return compute_type
    if "cuda" in device.lower():
        return "float16"
    return "int8"


def collect_input_files(input_path: Path, extensions: Sequence[str], recursive: bool) -> list[Path]:
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    if input_path.is_file():
        return [input_path]

    if not input_path.is_dir():
        raise ValueError(f"Input path is not a file or directory: {input_path}")

    allowed_extensions = {extension.lower() for extension in extensions}
    iterator = input_path.rglob("*") if recursive else input_path.iterdir()

    return sorted(
        path
        for path in iterator
        if path.is_file() and path.suffix.lower() in allowed_extensions
    )


def build_output_path(
    source_path: Path,
    *,
    input_root: Path | None,
    output_dir: Path | None,
    output_suffix: str = DEFAULT_OUTPUT_SUFFIX,
) -> Path:
    if output_dir is None:
        return source_path.with_suffix(output_suffix)

    if input_root is None:
        return output_dir / source_path.with_suffix(output_suffix).name

    return output_dir / source_path.relative_to(input_root).with_suffix(output_suffix)


def build_model(model_size: str, device: str, compute_type: str | None) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - dependency issue
        raise RuntimeError("faster-whisper is required to run transcribe.py") from exc

    return WhisperModel(
        model_size,
        device=device,
        compute_type=choose_compute_type(device, compute_type),
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
    beam_size: int,
    language: str | None,
) -> int:
    kwargs: dict[str, object] = {
        "beam_size": beam_size,
        "condition_on_previous_text": False,
    }
    if language is not None:
        kwargs["language"] = language

    segments, _info = model.transcribe(str(source_path), **kwargs)
    return write_transcript(output_path, segments)


def main(
    argv: Sequence[str] | None = None,
    *,
    model_factory: Callable[[str, str, str | None], Any] = build_model,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        extensions = normalize_extensions(args.extensions)
        language = normalize_language(args.language)
        compute_type = choose_compute_type(args.device, args.compute_type)
        input_path = args.input_path.expanduser()
        output_dir = args.output_dir.expanduser() if args.output_dir is not None else None
        source_files = collect_input_files(input_path, extensions, args.recursive)
        if not source_files:
            raise ValueError(f"No matching audio files found in {input_path}")
        model = model_factory(args.model_size, args.device, compute_type)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    input_root = input_path if input_path.is_dir() else None
    failures = 0

    for source_path in source_files:
        output_path = build_output_path(
            source_path,
            input_root=input_root,
            output_dir=output_dir,
        )

        if output_path == source_path:
            print(f"Error: refusing to overwrite input file in place: {source_path}", file=sys.stderr)
            failures += 1
            continue

        try:
            line_count = transcribe_file(
                source_path,
                output_path,
                model,
                args.beam_size,
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