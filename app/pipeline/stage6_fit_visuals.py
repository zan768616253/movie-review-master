"""Stage 6: trim/extend each rough-cut beat to match its TTS duration.

The keystone of the new architecture. After Stage 5 the audio durations
are known per beat; this stage shapes the rough cut so each beat's video
length equals its `audio_end_s − audio_start_s`.

Default fitting strategy (v1):

- **TTS shorter than video** (the common case): trim from the *tail* of
  the *least-important* micro-shot. v1 heuristic for "least important" =
  the last micro-shot in the beat.
- **TTS longer than video**: hold on the last micro-shot's last frame
  for the overrun seconds. v1 fallback only — note in plan.md if this
  looks visually static.
- **TTS within ±0.5s of video**: no trim, take the rough cut as-is.

Future strategies (deferred until v1 reveals the real failure modes):
slow-motion stretching, B-roll cutaway from unused selected shots,
proportional trim distributed across all micro-shots, loop-static-shot.

Inputs:
    --rough-cut-manifest    Stage 3 `rough_cut.json`
    --rough-cut-video       Stage 3 `rough_cut.mp4`
    --voiceover-manifest    Stage 5 voiceover manifest

Outputs:
    <out_dir>/fitted/beat_NNN.mp4   one fitted clip per beat

This module is a skeleton — see plan.md Phase 5 for the implementation tasks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A beat is "already fitted" if its video duration is within this tolerance
# of its audio duration. Below the tolerance we still trim or hold;
# inside the tolerance we take the rough cut as-is.
FIT_TOLERANCE_S = 0.5


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class FitOperation:
    """One per-beat fit plan.

    `source_start_s` / `source_end_s` are positions inside the rough-cut
    video. `hold_extra_s > 0` means freeze the final frame for that many
    seconds after `source_end_s` to fill an audio overrun. `0.0` means
    no hold.
    """

    beat_index: int
    source_start_s: float
    source_end_s: float
    hold_extra_s: float
    output_path: Path

    @property
    def fitted_duration_s(self) -> float:
        return (self.source_end_s - self.source_start_s) + self.hold_extra_s


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def compute_fit_plan(
    beats: list[dict[str, object]],
    voiceover_manifest: list[dict[str, object]],
    *,
    tolerance_s: float = FIT_TOLERANCE_S,
) -> list[FitOperation]:
    """Decide trim/hold operations per beat from rough-cut + voiceover durations.

    For each beat:
      - look up its audio duration in the voiceover manifest
      - compare to the rough-cut beat duration
      - choose: trim from tail, hold last frame, or no-op (within tolerance)

    The output `output_path` is a placeholder; callers fill it in with
    the actual on-disk path.

    Implementation: Phase 5 / Task 5.2 in plan.md.
    """
    raise NotImplementedError("Phase 5 / Task 5.2 — see plan.md")


def execute_fit(rough_cut_video: Path, op: FitOperation) -> None:
    """Apply one FitOperation via ffmpeg, writing `op.output_path`.

    For a trim: extract the slice `[source_start_s, source_end_s]` from
    `rough_cut_video` and re-encode.

    For a hold: extract the slice, then append a frozen tail using
    `tpad=stop_mode=clone:stop_duration={hold_extra_s}`.

    Implementation: Phase 5 / Task 5.2 in plan.md.
    """
    raise NotImplementedError("Phase 5 / Task 5.2 — see plan.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fit-visuals",
        description="Stage 6: trim/extend each rough-cut beat to match its TTS duration.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--rough-cut-manifest", type=Path, required=True,
                        help="Stage 3 `rough_cut.json`.")
    parser.add_argument("--rough-cut-video", type=Path, required=True,
                        help="Stage 3 `rough_cut.mp4`.")
    parser.add_argument("--voiceover-manifest", type=Path, required=True,
                        help="Stage 5 voiceover manifest JSON.")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Directory for `fitted/beat_NNN.mp4` outputs.")
    parser.add_argument("--encoder", choices=["auto", "nvenc", "libx264"],
                        default="auto",
                        help="Video encoder.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raise NotImplementedError("Phase 5 / Task 5.2 — see plan.md")


if __name__ == "__main__":
    sys.exit(main())
