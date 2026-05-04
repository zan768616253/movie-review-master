"""Stage 8: assemble the draft review video.

Concatenates the fitted per-beat clips in `beat_index` order, burns
subtitles from the subtitle manifest, and muxes the voiceover track.
The result is `review.mp4` — a watchable draft that Stage 9 finalizes
into an upload-ready master.

Inputs:
    --fitted-dir            directory of `beat_NNN.mp4` from Stage 6
    --voiceover             Stage 5 voiceover MP3
    --subtitle-manifest     Stage 7 `subtitle_manifest.json`

Output:
    --out                   `review.mp4`

The current `app/pipeline/stage4_align_subtitles.py` survives from the
old pipeline and is the source of the subtitle manifest. It will be
renamed to `stage7_align_subtitles.py` in plan.md Phase 6 (before this
stage is implemented), so this module's import line below can already
target the new name.

This module is a skeleton — see plan.md Phase 7 for the implementation tasks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.common.video_encoder import resolve_encoder


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class RenderPlan:
    """All inputs the renderer needs in one place."""

    fitted_clips: list[Path]
    voiceover: Path
    subtitle_manifest: Path
    output: Path
    encoder: str


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def collect_fitted_clips(fitted_dir: Path) -> list[Path]:
    """Return fitted beat clips sorted by beat index.

    Filenames follow the pattern `beat_NNN.mp4`; sorting is by the
    integer extracted from the filename, not lexicographic.

    Implementation: Phase 7 / Task 7.1 in plan.md.
    """
    raise NotImplementedError("Phase 7 / Task 7.1 — see plan.md")


def write_ass_from_manifest(
    subtitle_manifest: list[dict[str, object]],
    output_ass: Path,
) -> None:
    """Materialize a libass `.ass` file from the subtitle manifest cues.

    Each cue becomes one Dialogue line. Style block is fixed to a
    readable default; future polish (font, outline, position) can be
    layered in later.

    Implementation: Phase 7 / Task 7.1 in plan.md.
    """
    raise NotImplementedError("Phase 7 / Task 7.1 — see plan.md")


def concat_fitted_clips(
    fitted_clips: list[Path],
    output: Path,
    *,
    encoder: str,
) -> None:
    """ffmpeg concat-demuxer pass over the fitted beat clips.

    Implementation: Phase 7 / Task 7.1 in plan.md.
    """
    raise NotImplementedError("Phase 7 / Task 7.1 — see plan.md")


def burn_subtitles(
    video: Path,
    ass_file: Path,
    output: Path,
    *,
    encoder: str,
) -> None:
    """Burn the libass subtitles into the video stream.

    Uses ffmpeg's `subtitles=` filter with a re-encode pass.

    Implementation: Phase 7 / Task 7.1 in plan.md.
    """
    raise NotImplementedError("Phase 7 / Task 7.1 — see plan.md")


def mux_voiceover(
    video: Path,
    voiceover: Path,
    output: Path,
) -> None:
    """Mux the voiceover MP3 onto the burned-subtitle video.

    Implementation: Phase 7 / Task 7.1 in plan.md.
    """
    raise NotImplementedError("Phase 7 / Task 7.1 — see plan.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render-video",
        description="Stage 8: concat fitted beats, burn subs, mux voiceover → review.mp4.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--fitted-dir", type=Path, required=True,
                        help="Directory of Stage 6 `beat_NNN.mp4` clips.")
    parser.add_argument("--voiceover", type=Path, required=True,
                        help="Stage 5 voiceover MP3.")
    parser.add_argument("--subtitle-manifest", type=Path, required=True,
                        help="Stage 7 `subtitle_manifest.json`.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output `review.mp4` path.")
    parser.add_argument("--encoder", choices=["auto", "nvenc", "libx264"],
                        default="auto",
                        help="Video encoder for re-encode passes.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raise NotImplementedError("Phase 7 / Task 7.1 — see plan.md")


if __name__ == "__main__":
    sys.exit(main())
