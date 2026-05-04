"""Stage 5: TTS each beat's narration line and emit a voiceover + manifest.

For each beat in `narration.json`, run Qwen3-TTS Voice Clone on the
configured style's reference audio + transcript. Concatenate the per-beat
audio into one MP3, loudness-normalize, and emit a manifest that records
where each beat starts and ends inside the concatenated track.

Field names in the manifest are preserved verbatim from the legacy
contract so the surviving subtitle-alignment module works without
modification:

    [
      { "index": 1, "text": "...", "audio_start_s": 0.0, "audio_end_s": 4.82 },
      ...
    ]

Engine recovery: the Qwen3-TTS engine code (model loading, generation,
audio concat, normalization) lives in git history at the parent commit
of the `stage3_generate_audio.py` deletion. See plan.md Phase 3 / Task 3.1
for the recovery procedure. The engine code should be reused verbatim;
only the input parser changes (anchored chunks → narration.json).

This module is a skeleton — see plan.md Phase 3 for the implementation tasks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
REPO_ROOT = Path(__file__).resolve().parents[2]
STYLES_DIR = REPO_ROOT / "styles"
DEFAULT_STYLE_PATH = STYLES_DIR / "niu-shu.md"
REFERENCE_AUDIO_FILENAME = "clone_reference.mp3"
REFERENCE_TEXT_FILENAME = "clone_reference.txt"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class VoiceoverManifestEntry:
    """One entry in the voiceover manifest.

    Field names match the legacy contract verbatim. `index` corresponds
    to the `beat_index` from `narration.json` / `rough_cut.json`.
    """

    index: int
    text: str
    audio_start_s: float
    audio_end_s: float


@dataclass(frozen=True)
class VoiceReference:
    """Resolved Qwen3 voice-clone reference triple."""

    style_path: Path
    audio_path: Path
    text_path: Path


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def resolve_voice_reference(
    style_path: Path,
    *,
    ref_audio: Path | None = None,
    ref_text: Path | None = None,
) -> VoiceReference:
    """Resolve the voice-clone reference from style or explicit overrides.

    Default: `styles/voice-assets/<style-stem>/reference/clone_reference.{mp3,txt}`.
    Overrides via `--ref-audio` / `--ref-text` win when supplied. Raises
    if any required path is missing.

    Implementation: Phase 3 / Task 3.3 in plan.md.
    """
    raise NotImplementedError("Phase 3 / Task 3.3 — see plan.md")


def synthesize_one(
    text: str,
    *,
    voice_reference: VoiceReference,
    output_path: Path,
) -> float:
    """Run Qwen3-TTS on one narration line and return its duration in seconds.

    Recovers the engine code from git history; see plan.md Task 3.1.

    Implementation: Phase 3 / Task 3.3 in plan.md.
    """
    raise NotImplementedError("Phase 3 / Task 3.3 — see plan.md")


def concat_voiceover(
    per_beat_audio: list[Path],
    output_mp3: Path,
) -> None:
    """Concatenate per-beat MP3s into one normalized voiceover.

    Loudness normalization happens here (legacy implementation in git
    history applied EBU R128 via ffmpeg loudnorm).

    Implementation: Phase 3 / Task 3.3 in plan.md.
    """
    raise NotImplementedError("Phase 3 / Task 3.3 — see plan.md")


def build_voiceover_manifest(
    narration: list[dict[str, object]],
    per_beat_durations: list[float],
) -> list[VoiceoverManifestEntry]:
    """Build the manifest entries from narration text + measured durations.

    Walks the narration list in order; cumulative sum of per-beat
    durations becomes `audio_start_s`/`audio_end_s`.

    Implementation: Phase 3 / Task 3.3 in plan.md.
    """
    raise NotImplementedError("Phase 3 / Task 3.3 — see plan.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-audio",
        description="Stage 5: TTS each narration line and emit voiceover + manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--narration", type=Path, required=True,
                        help="Stage 4 `narration.json`.")
    parser.add_argument("--style", type=Path, default=DEFAULT_STYLE_PATH,
                        help="Style markdown file (used to resolve the default voice reference).")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Directory for the voiceover MP3 and manifest.")
    parser.add_argument("--ref-audio", type=Path,
                        help="Explicit voice-clone reference audio (overrides style default).")
    parser.add_argument("--ref-text", type=Path,
                        help="Explicit voice-clone reference transcript (overrides style default).")
    parser.add_argument("--tag", type=str,
                        help="Output filename tag. Defaults to the style filename stem.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raise NotImplementedError("Phase 3 / Task 3.3 — see plan.md")


if __name__ == "__main__":
    sys.exit(main())
