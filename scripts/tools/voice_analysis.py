"""One-off voice analysis utility for TTS reference samples.

Given a reference audio file and its transcript, compute:
    - duration, sample rate, channels (via librosa)
    - speaking rate in Chinese chars per second (transcript / voiced time)
    - pause distribution (count, mean, median, max) via librosa silence detection
    - pitch stats (mean/std/min/max F0) via librosa.pyin
    - energy (RMS) mean + variance

Writes JSON output next to the audio file so the generation script can reuse it.

What this file produces
- pitch (see `pitch_stats()`): simple pitch numbers that describe how high
    or low the voice is. You get an average pitch (`f0_mean_hz`), how much
    pitch varies (`f0_std_hz`), and rough minimum/maximum values
    (`f0_min_hz` = 5th percentile, `f0_max_hz` = 95th percentile). If the
    audio has no voiced frames, these fields will be `None`.
- energy (see `energy_stats()`): measures loudness using RMS energy per frame.
    Returns `rms_mean` (average loudness), `rms_std` (loudness variability),
    and `rms_cv` (relative variability = std / mean).
- full result (returned by `analyze()` and written as JSON): one dictionary
    that contains:
        * file info: `audio_path`, `transcript_path`
        * audio info: `sample_rate`
        * transcript info: `chinese_char_count`, `speaking_rate_chars_per_sec`
        * pause info: `voiced_duration_s`, `total_duration_s`, `pause_count`,
            `pause_mean_s`, `pause_median_s`, `pause_max_s`, `pause_total_s`
        * pitch info: `f0_mean_hz`, `f0_std_hz`, `f0_min_hz`, `f0_max_hz`
        * energy info: `rms_mean`, `rms_std`, `rms_cv`
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np


def count_chinese_chars(text: str) -> int:
    """Count CJK Unified Ideographs (commonly considered 'Chinese' characters).

    Args:
        text: Input string to scan.

    Returns:
        int: Number of characters in the Unicode range U+4E00..U+9FFF.
    """
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def pause_stats(y: np.ndarray, sr: float, top_db: float = 30.0, min_pause_s: float = 0.3) -> dict:
    """Compute pause / voiced-segment statistics from an audio signal.

    Uses `librosa.effects.split()` to find non-silent intervals (voiced segments)
    and derives pause durations between those intervals.

    Args:
        y: Audio time series (mono).
        sr: Sample rate of `y`.
        top_db: The threshold (in decibels) below reference to consider as silence.
        min_pause_s: Minimum gap length (seconds) to count as a pause.

    Returns:
        dict: {
            "voiced_duration_s": total seconds classified as voiced,
            "total_duration_s": total audio duration (s),
            "pause_count": number of detected pauses >= `min_pause_s`,
            "pause_mean_s": mean pause length (s) or None,
            "pause_median_s": median pause length (s) or None,
            "pause_max_s": maximum pause length (s) or None,
            "pause_total_s": sum of all pause durations (s)
        }
    """
    intervals = librosa.effects.split(y, top_db=top_db)
    total_duration = len(y) / sr
    voiced_duration = sum((e - s) for s, e in intervals) / sr
    silence_gaps = []
    prev_end = 0
    for s, e in intervals:
        if s > prev_end:
            gap_s = (s - prev_end) / sr
            if gap_s >= min_pause_s:
                silence_gaps.append(gap_s)
        prev_end = e
    if total_duration > prev_end / sr:
        tail = total_duration - prev_end / sr
        if tail >= min_pause_s:
            silence_gaps.append(tail)
    return {
        "voiced_duration_s": round(voiced_duration, 2),
        "total_duration_s": round(total_duration, 2),
        "pause_count": len(silence_gaps),
        "pause_mean_s": round(float(np.mean(silence_gaps)), 3) if silence_gaps else None,
        "pause_median_s": round(float(np.median(silence_gaps)), 3) if silence_gaps else None,
        "pause_max_s": round(float(np.max(silence_gaps)), 3) if silence_gaps else None,
        "pause_total_s": round(float(np.sum(silence_gaps)), 3),
    }


def pitch_stats(y: np.ndarray, sr: float) -> dict:
    """Estimate pitch (fundamental frequency) statistics using `librosa.pyin`.

    This attempts to extract frame-level F0 (Hz). Voiced frames are selected and
    summary statistics are computed. The 5th and 95th percentiles are used for
    min/max to reduce sensitivity to outliers.

    Args:
        y: Audio time series (mono).
        sr: Sample rate of `y`.

    Returns:
        dict: {
            "f0_mean_hz": mean F0 over voiced frames (Hz) or None,
            "f0_std_hz": std deviation of F0 (Hz) or None,
            "f0_min_hz": 5th percentile of F0 (Hz) or None,
            "f0_max_hz": 95th percentile of F0 (Hz) or None
        }
    """
    f0, voiced_flag, _ = librosa.pyin(
        y,
        fmin=float(librosa.note_to_hz("C2")),
        fmax=float(librosa.note_to_hz("C5")),
        sr=sr,
    )
    voiced_f0 = f0[voiced_flag & ~np.isnan(f0)]
    if len(voiced_f0) == 0:
        return {"f0_mean_hz": None, "f0_std_hz": None, "f0_min_hz": None, "f0_max_hz": None}
    return {
        "f0_mean_hz": round(float(np.mean(voiced_f0)), 1),
        "f0_std_hz": round(float(np.std(voiced_f0)), 1),
        "f0_min_hz": round(float(np.percentile(voiced_f0, 5)), 1),
        "f0_max_hz": round(float(np.percentile(voiced_f0, 95)), 1),
    }


def energy_stats(y: np.ndarray) -> dict:
    """Compute RMS-based energy statistics.

    The energy is computed per-frame using `librosa.feature.rms`. We return
    the mean, standard deviation and coefficient of variation (std/mean).

    Args:
        y: Audio time series (mono).

    Returns:
        dict: {
            "rms_mean": mean RMS value,
            "rms_std": RMS standard deviation,
            "rms_cv": coefficient of variation (std / mean) or 0 if mean == 0
        }
    """
    rms = librosa.feature.rms(y=y).flatten()
    return {
        "rms_mean": round(float(np.mean(rms)), 4),
        "rms_std": round(float(np.std(rms)), 4),
        "rms_cv": round(float(np.std(rms) / np.mean(rms)) if np.mean(rms) > 0 else 0, 3),
    }


def analyze(audio_path: Path, transcript_path: Path) -> dict:
    """Run the full analysis for a single audio + transcript pair.

    Steps:
      - Load audio with `librosa.load` (preserve original sample rate).
      - Count Chinese characters in the transcript.
      - Compute pause, pitch and energy statistics.
      - Compute a simple speaking rate as characters per voiced second.

    Args:
        audio_path: Path to the audio file.
        transcript_path: Path to the transcript text file.

    Returns:
        dict: A merged dictionary containing paths, sample rate, character count,
        speaking rate, pause statistics, pitch statistics and energy statistics.
    """
    y, sr = librosa.load(str(audio_path), sr=None, mono=True)
    transcript = transcript_path.read_text(encoding="utf-8")
    chars = count_chinese_chars(transcript)

    pauses = pause_stats(y, sr)
    pitch = pitch_stats(y, sr)
    energy = energy_stats(y)

    speaking_rate = round(chars / pauses["voiced_duration_s"], 2) if pauses["voiced_duration_s"] else None

    return {
        "audio_path": str(audio_path),
        "transcript_path": str(transcript_path),
        "sample_rate": sr,
        "chinese_char_count": chars,
        "speaking_rate_chars_per_sec": speaking_rate,
        **pauses,
        **pitch,
        **energy,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="voice-analysis")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--transcript", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    audio_path = args.audio.expanduser().resolve()
    transcript_path = (
        args.transcript.expanduser().resolve()
        if args.transcript
        else audio_path.with_suffix(".txt")
    )
    if not audio_path.exists():
        print(f"Audio not found: {audio_path}", file=sys.stderr)
        return 1
    if not transcript_path.exists():
        print(f"Transcript not found: {transcript_path}", file=sys.stderr)
        return 1

    result = analyze(audio_path, transcript_path)
    out_path = args.out or audio_path.with_suffix(".analysis.json")
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    for k, v in result.items():
        print(f"{k}: {v}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
