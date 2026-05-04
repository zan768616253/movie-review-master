"""Stage 3: concatenate selected shots into a rough cut, segmented by beat.

This stage is the first visual artifact of the new pipeline — once it
runs, the user can watch a chronological supercut of the selected
high-information shots, grouped into 30–60s narrative beats that will
each receive one narration line in Stage 4.

Inputs:
    --movie         the source movie file (.mp4 / .mkv)
    --selected      Stage 2 `selected_shots.json` (only `keep=true` rows are used)

Outputs:
    <out_dir>/rough_cut.mp4    chronological concatenation of kept shots
    <out_dir>/rough_cut.json   per-beat manifest (see RoughCutBeat below)

Beat-grouping algorithm (default greedy):
    accumulate shots until adding the next would push the running beat
    duration past `BEAT_MAX_S`. Shots longer than `BEAT_MAX_S` become
    single-shot beats.

This module is a skeleton — see plan.md Phase 2 for the implementation tasks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.common.video_encoder import resolve_encoder


# ---------------------------------------------------------------------------
# Constants — beat grouping
# ---------------------------------------------------------------------------

# Aim for this beat duration when grouping micro-shots.
BEAT_TARGET_S = 45.0

# Lower bound; anything shorter is acceptable for a single-shot tail beat.
BEAT_MIN_S = 20.0

# Hard upper bound. The greedy grouper closes the current beat before
# adding a shot that would push the total past this threshold.
BEAT_MAX_S = 60.0


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class RoughCutBeat:
    """One beat in the rough cut.

    `shot_ids` references Stage 2 / Stage 0 entries.
    `start_s` and `end_s` are positions inside the *concatenated*
    `rough_cut.mp4`, NOT source-movie timestamps.
    """

    beat_index: int
    shot_ids: list[str]
    start_s: float
    end_s: float

    @property
    def total_duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class ShotClipPlan:
    """Internal plan for extracting one micro-shot from the source movie.

    Used by the ffmpeg dispatcher to extract each kept shot before they
    are concatenated into the final rough cut.
    """

    shot_id: str
    source_start_s: float
    source_end_s: float
    extracted_path: Path


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def group_into_beats(
    kept_shots: list[dict[str, object]],
    *,
    target_s: float = BEAT_TARGET_S,
    min_s: float = BEAT_MIN_S,
    max_s: float = BEAT_MAX_S,
) -> list[list[dict[str, object]]]:
    """Group consecutive kept shots into beats of roughly `target_s` seconds.

    Default policy:
      - greedy: keep adding shots until the next would overflow `max_s`.
      - single-shot fallback: a shot longer than `max_s` becomes its own beat.

    Returns a list of beats, where each beat is a list of shot dicts in
    chronological order.

    Implementation: Phase 2 / Task 2.3 in plan.md (see also Task 2.2 for
    algorithm-tuning decisions to revisit after the first real run).
    """
    raise NotImplementedError("Phase 2 / Task 2.3 — see plan.md")


def compute_beat_positions(
    beats: list[list[dict[str, object]]],
) -> list[RoughCutBeat]:
    """Compute `start_s`/`end_s` for each beat inside the concatenated rough cut.

    Walks the beat list in order, accumulating per-shot durations to
    produce the position of each beat within the final concatenated
    output.

    Implementation: Phase 2 / Task 2.3 in plan.md.
    """
    raise NotImplementedError("Phase 2 / Task 2.3 — see plan.md")


def extract_shot(
    movie: Path,
    plan: ShotClipPlan,
    *,
    encoder: str,
) -> None:
    """Re-encode one micro-shot from the source movie via ffmpeg.

    Re-encoded (not stream-copied) so trim boundaries land on exact
    frames. Uses the resolved encoder (`h264_nvenc` on the RTX 4060
    target, `libx264` fallback).

    Implementation: Phase 2 / Task 2.3 in plan.md.
    """
    raise NotImplementedError("Phase 2 / Task 2.3 — see plan.md")


def concat_clips(clips: list[Path], output: Path, *, encoder: str) -> None:
    """Concatenate the per-shot clips into the final rough_cut.mp4.

    Uses ffmpeg's concat demuxer with a temporary list file.

    Implementation: Phase 2 / Task 2.3 in plan.md.
    """
    raise NotImplementedError("Phase 2 / Task 2.3 — see plan.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assemble-rough-cut",
        description="Stage 3: concat selected shots into a beat-segmented rough cut.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--movie", type=Path, required=True,
                        help="Source movie file.")
    parser.add_argument("--selected-shots", type=Path, required=True,
                        help="Stage 2 `selected_shots.json`.")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Directory for `rough_cut.mp4` + `rough_cut.json`.")
    parser.add_argument("--encoder", choices=["auto", "nvenc", "libx264"],
                        default="auto",
                        help="Video encoder (auto picks NVENC if available).")
    parser.add_argument("--beat-target-s", type=float, default=BEAT_TARGET_S,
                        help="Target beat duration in seconds.")
    parser.add_argument("--beat-max-s", type=float, default=BEAT_MAX_S,
                        help="Hard upper bound on beat duration.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raise NotImplementedError("Phase 2 / Task 2.3 — see plan.md")


if __name__ == "__main__":
    sys.exit(main())
