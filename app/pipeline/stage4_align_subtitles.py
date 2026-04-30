"""Stage 4: derive timed subtitle cues from the Stage 3 voiceover.

This stage fixes the old "one narration chunk = one subtitle event" contract.
It reads the Stage 3 voice manifest plus the real concatenated voiceover audio,
splits each narration chunk into shorter subtitle cues, and places cue
boundaries on actual pauses detected in the audio.

The result is a dedicated subtitle manifest consumed by the render stage:

    [
      {
        "index": 1,
        "chunk_index": 3,
        "text": "注意看，眼前这个弱不禁风的男人叫小帅，",
        "start_s": 0.0,
        "end_s": 2.14
      },
      ...
    ]

The implementation is deliberately simple and deterministic:

1. Split narration text by punctuation into readable subtitle cues.
2. Run ``ffmpeg silencedetect`` once on the voiceover MP3.
3. For each Stage 3 chunk, derive speech windows from the detected silences.
4. Map cue texts onto those windows, preserving chronological order.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.pipeline.common.json_io import dump_json, load_json


DEFAULT_SUBTITLE_MANIFEST_NAME = "subtitle_manifest.json"
DEFAULT_MAX_CUE_CHARS = 28
DEFAULT_SILENCE_NOISE_DB = -35.0
DEFAULT_MIN_SILENCE_S = 0.18
DEFAULT_MIN_SPEECH_S = 0.12
STRONG_BREAK_CHARS = set("。！？!?；;")
SOFT_BREAK_CHARS = set("，、：:,")


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def split_on_break_chars(text: str, break_chars: set[str]) -> list[str]:
    units: list[str] = []
    current: list[str] = []
    for ch in text:
        current.append(ch)
        if ch in break_chars:
            chunk = "".join(current).strip()
            if chunk:
                units.append(chunk)
            current = []
    tail = "".join(current).strip()
    if tail:
        units.append(tail)
    return units


def hard_wrap_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    if text and text[-1] in (STRONG_BREAK_CHARS | SOFT_BREAK_CHARS) and len(text) <= max_chars + 2:
        return [text]
    return [text[i:i + max_chars].strip() for i in range(0, len(text), max_chars) if text[i:i + max_chars].strip()]


def merge_tiny_units(units: list[str], max_chars: int) -> list[str]:
    if not units:
        return []
    merged: list[str] = []
    for unit in units:
        if (
            merged
            and len(unit) <= 4
            and unit[-1] not in STRONG_BREAK_CHARS
            and len(merged[-1]) + len(unit) <= max_chars
        ):
            merged[-1] += unit
            continue
        merged.append(unit)
    return merged


def split_subtitle_text(text: str, max_chars: int = DEFAULT_MAX_CUE_CHARS) -> list[str]:
    """Split narration into short subtitle cues.

    We prefer strong punctuation first, then softer comma-like punctuation,
    and only fall back to hard character-count wrapping when no better break
    exists.
    """
    normalized = collapse_whitespace(text)
    if not normalized:
        return []

    cues: list[str] = []
    strong_units = split_on_break_chars(normalized, STRONG_BREAK_CHARS) or [normalized]
    for strong_unit in strong_units:
        if len(strong_unit) <= max_chars:
            cues.append(strong_unit)
            continue

        soft_units = split_on_break_chars(strong_unit, SOFT_BREAK_CHARS) or [strong_unit]
        for soft_unit in soft_units:
            if len(soft_unit) <= max_chars:
                cues.append(soft_unit)
            else:
                cues.extend(hard_wrap_text(soft_unit, max_chars))

    return merge_tiny_units(cues, max_chars)


def detect_silence_intervals(
    audio_path: Path,
    *,
    noise_db: float = DEFAULT_SILENCE_NOISE_DB,
    min_silence_s: float = DEFAULT_MIN_SILENCE_S,
) -> list[tuple[float, float]]:
    """Run ``ffmpeg silencedetect`` and return ``(start_s, end_s)`` intervals."""
    cmd = [
        "ffmpeg",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=n={noise_db}dB:d={min_silence_s}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    intervals: list[tuple[float, float]] = []
    start_s: float | None = None

    for line in proc.stderr.splitlines():
        if "silencedetect" not in line:
            continue
        for token in line.split():
            if token.startswith("silence_start:"):
                try:
                    start_s = float(token.split(":", 1)[1])
                except ValueError:
                    start_s = None
            elif token.startswith("silence_end:") and start_s is not None:
                try:
                    end_s = float(token.split(":", 1)[1])
                except ValueError:
                    start_s = None
                    continue
                if end_s > start_s:
                    intervals.append((start_s, end_s))
                start_s = None
    return intervals


def clip_intervals(
    intervals: list[tuple[float, float]],
    start_s: float,
    end_s: float,
) -> list[tuple[float, float]]:
    clipped: list[tuple[float, float]] = []
    for interval_start, interval_end in intervals:
        clipped_start = max(start_s, interval_start)
        clipped_end = min(end_s, interval_end)
        if clipped_end > clipped_start:
            clipped.append((clipped_start, clipped_end))
    return clipped


def build_speech_segments(
    chunk_start_s: float,
    chunk_end_s: float,
    silence_intervals: list[tuple[float, float]],
    *,
    min_speech_s: float = DEFAULT_MIN_SPEECH_S,
) -> list[tuple[float, float]]:
    """Return chunk-local speech spans by subtracting silence intervals."""
    silences = clip_intervals(silence_intervals, chunk_start_s, chunk_end_s)
    if not silences:
        return [(chunk_start_s, chunk_end_s)]

    segments: list[tuple[float, float]] = []
    cursor = chunk_start_s
    for silence_start, silence_end in silences:
        if silence_start - cursor >= min_speech_s:
            segments.append((cursor, silence_start))
        cursor = max(cursor, silence_end)
    if chunk_end_s - cursor >= min_speech_s:
        segments.append((cursor, chunk_end_s))
    return segments or [(chunk_start_s, chunk_end_s)]


def choose_natural_windows(
    speech_segments: list[tuple[float, float]],
    desired_count: int,
) -> list[tuple[float, float]]:
    """Merge speech segments into ``desired_count`` windows using the longest pauses."""
    if not speech_segments:
        return []
    if desired_count <= 1 or len(speech_segments) == 1:
        return [(speech_segments[0][0], speech_segments[-1][1])]

    gaps: list[tuple[float, int]] = []
    for index in range(len(speech_segments) - 1):
        gap_duration = speech_segments[index + 1][0] - speech_segments[index][1]
        gaps.append((gap_duration, index))

    split_after = sorted(index for _gap, index in sorted(gaps, reverse=True)[: desired_count - 1])
    windows: list[tuple[float, float]] = []
    group_start = 0
    for index in split_after:
        group = speech_segments[group_start:index + 1]
        windows.append((group[0][0], group[-1][1]))
        group_start = index + 1
    tail_group = speech_segments[group_start:]
    windows.append((tail_group[0][0], tail_group[-1][1]))
    return windows


def allocate_cue_counts(cue_count: int, windows: list[tuple[float, float]]) -> list[int]:
    """Allocate one or more cue texts to each natural timing window."""
    counts = [1] * len(windows)
    while sum(counts) < cue_count:
        best_index = max(
            range(len(windows)),
            key=lambda index: (windows[index][1] - windows[index][0]) / counts[index],
        )
        counts[best_index] += 1
    return counts


def split_window_for_cues(
    window: tuple[float, float],
    cue_texts: list[str],
) -> list[tuple[float, float]]:
    start_s, end_s = window
    if len(cue_texts) == 1:
        return [(start_s, end_s)]

    total_duration = max(0.0, end_s - start_s)
    weights = [max(1, len(text.strip("，。！？!?；;：:、"))) for text in cue_texts]
    total_weight = sum(weights)
    cursor = start_s
    spans: list[tuple[float, float]] = []
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            cue_end = end_s
        else:
            cue_end = cursor + total_duration * (weight / total_weight)
        spans.append((round(cursor, 3), round(cue_end, 3)))
        cursor = cue_end
    return spans


def align_chunk_subtitles(
    chunk_index: int,
    text: str,
    chunk_start_s: float,
    chunk_end_s: float,
    silence_intervals: list[tuple[float, float]],
    *,
    max_chars: int = DEFAULT_MAX_CUE_CHARS,
) -> list[dict[str, object]]:
    cue_texts = split_subtitle_text(text, max_chars=max_chars)
    if not cue_texts:
        return []

    speech_segments = build_speech_segments(chunk_start_s, chunk_end_s, silence_intervals)
    window_count = min(len(cue_texts), len(speech_segments))
    windows = choose_natural_windows(speech_segments, window_count) or [(chunk_start_s, chunk_end_s)]
    cue_counts = allocate_cue_counts(len(cue_texts), windows)

    cues: list[dict[str, object]] = []
    cue_offset = 0
    for window, count in zip(windows, cue_counts):
        texts_for_window = cue_texts[cue_offset:cue_offset + count]
        for cue_text, (start_s, end_s) in zip(texts_for_window, split_window_for_cues(window, texts_for_window)):
            cues.append({
                "chunk_index": chunk_index,
                "text": cue_text,
                "start_s": start_s,
                "end_s": end_s,
            })
        cue_offset += count

    if cues:
        cues[0]["start_s"] = round(chunk_start_s, 3)
        cues[-1]["end_s"] = round(chunk_end_s, 3)
    return cues


def load_voice_manifest(path: Path) -> list[dict[str, object]]:
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid manifest JSON in {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"Manifest payload must be a JSON array: {path}")

    entries: list[dict[str, object]] = []
    for index, entry in enumerate(payload, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest entry {index} must be a JSON object: {path}")
        missing = [field for field in ("index", "text", "audio_start_s", "audio_end_s") if field not in entry]
        if missing:
            raise ValueError(
                f"Manifest entry {index} missing required fields {', '.join(missing)}: {path}"
            )
        entries.append(entry)
    return entries


def write_subtitle_manifest(
    manifest_entries: list[dict[str, object]],
    out_path: Path,
) -> None:
    payload = []
    for cue_index, entry in enumerate(manifest_entries, 1):
        payload.append({
            "index": cue_index,
            "chunk_index": int(entry["chunk_index"]), # type: ignore
            "text": str(entry["text"]),
            "start_s": round(float(entry["start_s"]), 3), # type: ignore
            "end_s": round(float(entry["end_s"]), 3), # type: ignore
        })
    dump_json(out_path, payload)


def default_output_path(voiceover_path: Path) -> Path:
    return voiceover_path.parent / DEFAULT_SUBTITLE_MANIFEST_NAME


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="align-subtitles",
        description="Stage 4: split Stage 3 narration into timed subtitle cues.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Stage 3 voice manifest JSON.")
    parser.add_argument("--voiceover", type=Path, required=True,
                        help="Stage 3 voiceover MP3.")
    parser.add_argument("--output", type=Path,
                        help="Subtitle manifest path. Defaults next to the voiceover.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    args.manifest = args.manifest.expanduser().resolve()
    args.voiceover = args.voiceover.expanduser().resolve()
    if args.output is not None:
        args.output = args.output.expanduser().resolve()
    else:
        args.output = default_output_path(args.voiceover)

    if not args.manifest.exists():
        print(f"Manifest not found: {args.manifest}", file=sys.stderr)
        return 1
    if not args.voiceover.exists():
        print(f"Voiceover not found: {args.voiceover}", file=sys.stderr)
        return 1

    try:
        manifest = load_voice_manifest(args.manifest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    silence_intervals = detect_silence_intervals(args.voiceover)

    subtitle_entries: list[dict[str, object]] = []
    for entry in manifest:
        subtitle_entries.extend(
            align_chunk_subtitles(
                int(entry["index"]), # type: ignore
                str(entry["text"]),
                float(entry["audio_start_s"]), # type: ignore
                float(entry["audio_end_s"]), # type: ignore
                silence_intervals,
            )
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_subtitle_manifest(subtitle_entries, args.output)

    print(f"[done] {args.output}")
    print(f"[done] {len(subtitle_entries)} subtitle cues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
