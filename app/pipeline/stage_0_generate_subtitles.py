"""Stage 0 (optional): generate an SRT subtitle file from the movie's audio.

Scans a movie folder for the video file. If any ``.srt`` or ``.ass`` already
exists alongside the video, the step is a no-op (human-curated subtitles
take precedence). Otherwise, transcribes the video with ``faster-whisper``
``large-v3`` on CUDA and writes ``<video_basename>.srt`` next to the video.

Entry point: ``generate-subtitles``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

from faster_whisper import WhisperModel


DEFAULT_MODEL_SIZE = "large-v3"
DEFAULT_DEVICE = "cuda"
DEFAULT_COMPUTE_TYPE = "float16"
DEFAULT_LANGUAGE = "zh"
DEFAULT_BEAM_SIZE = 5

VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".ts")
SUBTITLE_SUFFIXES = (".srt", ".ass")


def find_video(movie_dir: Path) -> Path:
    videos = sorted(
        p for p in movie_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_SUFFIXES
    )
    if not videos:
        raise FileNotFoundError(
            f"No video file ({', '.join(VIDEO_SUFFIXES)}) found in {movie_dir}"
        )
    if len(videos) > 1:
        names = ", ".join(v.name for v in videos)
        raise ValueError(f"Multiple video files in {movie_dir}: {names}")
    return videos[0]


def find_existing_subtitle(movie_dir: Path) -> Path | None:
    for entry in sorted(movie_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() in SUBTITLE_SUFFIXES:
            return entry
    return None


def format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(output_path: Path, segments: Iterable[Any]) -> int:
    blocks: list[str] = []
    count = 0
    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        count += 1
        start = format_srt_timestamp(float(segment.start))
        end = format_srt_timestamp(float(segment.end))
        blocks.append(f"{count}\n{start} --> {end}\n{text}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(blocks), encoding="utf-8")
    return count


def normalize_language(language: str | None) -> str | None:
    if language is None:
        return None
    cleaned = language.strip()
    if not cleaned or cleaned.lower() == "auto":
        return None
    return cleaned


def build_model(model_size: str, device: str, compute_type: str) -> Any:
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def generate_subtitles(
    movie_dir: Path,
    *,
    language: str | None = DEFAULT_LANGUAGE,
    model_size: str = DEFAULT_MODEL_SIZE,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
) -> Path:
    """Generate an SRT next to the video, or return the existing subtitle if present."""
    existing = find_existing_subtitle(movie_dir)
    if existing is not None:
        print(f"Found existing subtitle, skipping generation: {existing}")
        return existing

    video_path = find_video(movie_dir)
    output_path = video_path.with_suffix(".srt")

    print(f"Loading Whisper {model_size} on {device} ({compute_type})...")
    model = build_model(model_size, device, compute_type)

    lang = normalize_language(language)
    print(f"Transcribing {video_path.name} (language={lang or 'auto'})...")
    segments, _info = model.transcribe(
        str(video_path),
        beam_size=DEFAULT_BEAM_SIZE,
        condition_on_previous_text=False,
        language=lang,
    )

    line_count = write_srt(output_path, segments)
    print(f"Wrote {line_count} subtitle entries to {output_path}")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-subtitles",
        description=(
            "Stage 0 (optional): generate an SRT from the movie's audio via "
            "faster-whisper. Skips when a .srt or .ass already exists in the "
            "movie folder."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "movie_dir",
        type=Path,
        help="Path to the movie folder containing the video file.",
    )
    parser.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help='Language code (e.g. "zh", "en"), or "auto" to let Whisper detect.',
    )
    parser.add_argument("--model-size", default=DEFAULT_MODEL_SIZE)
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--compute-type", default=DEFAULT_COMPUTE_TYPE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    movie_dir = args.movie_dir.expanduser().resolve()

    if not movie_dir.exists():
        print(f"Error: movie folder not found: {movie_dir}", file=sys.stderr)
        return 1
    if not movie_dir.is_dir():
        print(f"Error: not a directory: {movie_dir}", file=sys.stderr)
        return 1

    try:
        generate_subtitles(
            movie_dir,
            language=args.language,
            model_size=args.model_size,
            device=args.device,
            compute_type=args.compute_type,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
