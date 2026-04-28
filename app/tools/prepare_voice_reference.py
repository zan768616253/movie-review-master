"""
Prepare canonical Stage 3 voice-clone reference assets for ICL usage.

conda run -n py312_machine_learning --no-capture-output python -m app.tools.prepare_voice_reference [clone_reference.full.mp3](http://_vscodecontentref_/4) --style [niu-shu.md](http://_vscodecontentref_/5) --start 00:00:00 --end 00:01:30
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from app.pipeline.common.script_contract import probe_media_duration, timestamp_to_seconds
from app.tools.transcribe_audio import (
    DEFAULT_DEVICE,
    DEFAULT_MODEL_SIZE,
    build_model,
    normalize_language,
    transcribe_file,
)
from app.tools.voice_analysis import analyze


REFERENCE_AUDIO_FILENAME = "clone_reference.mp3"
REFERENCE_TEXT_FILENAME = "clone_reference.txt"
REFERENCE_ANALYSIS_FILENAME = "clone_reference.analysis.json"
TRANSCRIBE_MODEL_SIZE = DEFAULT_MODEL_SIZE
TRANSCRIBE_DEVICE = DEFAULT_DEVICE
TRANSCRIBE_LANGUAGE = "zh"
REFERENCE_TARGET_SECONDS = 90.0
DEFAULT_OUTPUT_SAMPLE_RATE = 24000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prepare-voice-reference",
        description="Prepare a canonical short reference bundle for Stage 3 ICL voice cloning.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("source_audio", type=Path, help="Audio file containing the desired reference voice.")
    parser.add_argument(
        "--style",
        type=Path,
        required=True,
        help="Style .md file whose styles/voice-assets/<style>/reference directory will receive clone_reference.*.",
    )
    parser.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="Optional plain-text transcript matching the selected clip. If omitted, the prepared clip is auto-transcribed.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Optional clip start time in seconds or HH:MM:SS(.mmm). Required when the source file is longer than the ICL target.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Optional clip end time in seconds or HH:MM:SS(.mmm). If omitted with --start, the clip extends up to the built-in 90-second ICL target.",
    )
    return parser


def resolve_reference_dir(style_path: Path) -> Path:
    return style_path.parent / "voice-assets" / style_path.stem / "reference"


def parse_optional_timecode(raw: str | None) -> float | None:
    if raw is None:
        return None

    cleaned = raw.strip()
    if not cleaned:
        return None

    return timestamp_to_seconds(cleaned)


def resolve_clip_window(
    source_duration_s: float | None,
    start_s: float | None,
    end_s: float | None,
) -> tuple[float | None, float | None]:
    if end_s is not None and start_s is None:
        raise ValueError("--end requires --start")

    if start_s is None:
        if source_duration_s is None:
            raise ValueError(
                "Unable to determine source duration. Pass a short source clip or provide --start/--end explicitly."
            )
        if source_duration_s > REFERENCE_TARGET_SECONDS:
            raise ValueError(
                f"Source audio is {source_duration_s:.1f}s, longer than the ICL target of "
                f"{REFERENCE_TARGET_SECONDS:.1f}s. Pass --start/--end or trim the clip first."
            )
        return None, None

    if start_s < 0:
        raise ValueError("--start must be greater than or equal to 0")

    resolved_end_s = end_s
    if resolved_end_s is None:
        resolved_end_s = start_s + REFERENCE_TARGET_SECONDS

    if source_duration_s is not None:
        if start_s >= source_duration_s:
            raise ValueError(
                f"--start ({start_s:.3f}s) must be smaller than the source duration ({source_duration_s:.3f}s)."
            )
        resolved_end_s = min(resolved_end_s, source_duration_s)

    if resolved_end_s <= start_s:
        raise ValueError("Resolved clip end must be greater than --start")

    clip_duration_s = resolved_end_s - start_s
    if clip_duration_s > REFERENCE_TARGET_SECONDS:
        raise ValueError(
            f"Selected clip is {clip_duration_s:.1f}s, longer than the ICL target of "
            f"{REFERENCE_TARGET_SECONDS:.1f}s. Pick a shorter region."
        )

    return start_s, resolved_end_s


def run_ffmpeg_extract(
    source_audio: Path,
    output_audio: Path,
    start_s: float | None,
    end_s: float | None,
    run_cmd: Callable[..., Any],
) -> None:
    output_audio.parent.mkdir(parents=True, exist_ok=True)

    command = ["ffmpeg", "-y", "-loglevel", "error"]
    if start_s is not None:
        command.extend(["-ss", f"{start_s:.3f}"])

    command.extend(["-i", str(source_audio)])

    if start_s is not None and end_s is not None:
        command.extend(["-t", f"{end_s - start_s:.3f}"])

    command.extend(
        [
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(DEFAULT_OUTPUT_SAMPLE_RATE),
            "-f",
            "mp3",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "192k",
            str(output_audio),
        ]
    )
    run_cmd(command, check=True)


def write_reference_transcript(
    prepared_audio_path: Path,
    output_text_path: Path,
    transcript_path: Path | None,
    *,
    model_size: str,
    device: str,
    language: str | None,
    model_factory: Callable[[str, str], Any],
    transcribe_file_fn: Callable[[Path, Path, Any, str | None], int],
) -> None:
    output_text_path.parent.mkdir(parents=True, exist_ok=True)

    if transcript_path is not None:
        text = transcript_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Transcript is empty: {transcript_path}")
        output_text_path.write_text(text + "\n", encoding="utf-8")
        return

    model = model_factory(model_size, device)
    line_count = transcribe_file_fn(prepared_audio_path, output_text_path, model, language)
    if line_count <= 0:
        raise ValueError(f"Auto-transcription produced no usable lines for {prepared_audio_path}")


def build_analysis_payload(
    analysis_result: dict[str, Any],
    *,
    style_path: Path,
    source_audio_path: Path,
    source_transcript_path: Path | None,
    clip_start_s: float | None,
    clip_end_s: float | None,
) -> dict[str, Any]:
    payload = dict(analysis_result)
    payload.update(
        {
            "style_path": str(style_path),
            "source_audio_path": str(source_audio_path),
            "source_transcript_path": str(source_transcript_path) if source_transcript_path is not None else None,
            "clip_start_s": round(clip_start_s, 3) if clip_start_s is not None else None,
            "clip_end_s": round(clip_end_s, 3) if clip_end_s is not None else None,
            "prepared_for_stage3_icl": True,
            "reference_target_seconds": REFERENCE_TARGET_SECONDS,
            "recommended_for_icl": (analysis_result.get("total_duration_s") or 0) <= REFERENCE_TARGET_SECONDS,
        }
    )
    return payload


def main(
    argv: Sequence[str] | None = None,
    *,
    model_factory: Callable[[str, str], Any] = build_model,
    transcribe_file_fn: Callable[[Path, Path, Any, str | None], int] = transcribe_file,
    analyze_fn: Callable[[Path, Path], dict[str, Any]] = analyze,
    probe_duration_fn: Callable[[Path], float | None] = probe_media_duration,
    run_cmd: Callable[..., Any] = subprocess.run,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    source_audio = args.source_audio.expanduser().resolve()
    style_path = args.style.expanduser().resolve()
    transcript_path = args.transcript.expanduser().resolve() if args.transcript else None

    try:
        if not source_audio.exists():
            raise FileNotFoundError(f"Source audio not found: {source_audio}")
        if not style_path.exists():
            raise FileNotFoundError(f"Style file not found: {style_path}")
        if transcript_path is not None and not transcript_path.exists():
            raise FileNotFoundError(f"Transcript not found: {transcript_path}")

        source_duration_s = probe_duration_fn(source_audio)
        clip_start_s, clip_end_s = resolve_clip_window(
            source_duration_s,
            parse_optional_timecode(args.start),
            parse_optional_timecode(args.end),
        )

        reference_dir = resolve_reference_dir(style_path)
        output_audio_path = reference_dir / REFERENCE_AUDIO_FILENAME
        output_text_path = reference_dir / REFERENCE_TEXT_FILENAME
        output_analysis_path = reference_dir / REFERENCE_ANALYSIS_FILENAME
        tmp_audio_path = reference_dir / f"{REFERENCE_AUDIO_FILENAME}.tmp"

        run_ffmpeg_extract(source_audio, tmp_audio_path, clip_start_s, clip_end_s, run_cmd)
        tmp_audio_path.replace(output_audio_path)

        language = normalize_language(TRANSCRIBE_LANGUAGE)
        write_reference_transcript(
            output_audio_path,
            output_text_path,
            transcript_path,
            model_size=TRANSCRIBE_MODEL_SIZE,
            device=TRANSCRIBE_DEVICE,
            language=language,
            model_factory=model_factory,
            transcribe_file_fn=transcribe_file_fn,
        )

        analysis_result = analyze_fn(output_audio_path, output_text_path)
        payload = build_analysis_payload(
            analysis_result,
            style_path=style_path,
            source_audio_path=source_audio,
            source_transcript_path=transcript_path,
            clip_start_s=clip_start_s,
            clip_end_s=clip_end_s,
        )
        output_analysis_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    measured_duration_s = payload.get("total_duration_s")
    print(f"Prepared ICL reference for {style_path.stem}:")
    print(f"  audio: {output_audio_path}")
    print(f"  transcript: {output_text_path}")
    print(f"  analysis: {output_analysis_path}")
    if measured_duration_s is not None:
        print(f"  duration: {measured_duration_s:.1f}s")
    elif source_duration_s is not None:
        print(f"  duration: {source_duration_s:.1f}s (source probe)")
    return 0


if __name__ == "__main__":
    sys.exit(main())