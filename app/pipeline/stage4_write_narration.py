"""Stage 4: write one narration line per rough-cut beat.

This is the second manual stage in the new pipeline. Two-mode CLI:

- **prompt mode** (default): assemble a single planner prompt from the
  rough-cut manifest, the surrounding subtitle context, the synopsis, and
  the chosen style file. The prompt is written to `narration_prompt.txt`
  and an empty placeholder `narration.json` is created. The user pastes
  the prompt into Gemini 3 Pro / Qwen 3.6 and pastes the JSON reply into
  `narration.json`.

- **validate mode** (``--validate``): read `narration.json` and verify
  every beat has text, every text fits its char-count budget, and beat
  indices match the rough-cut manifest.

Char-count budget per beat:

    target_chars = beat.total_duration_s × REAL_TTS_CPS

Narration is sacred — the validator never trims text. Text that overruns
budget is reported as a fail, requiring a manual rewrite.

This module is a skeleton — see plan.md Phase 4 for the implementation tasks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.common.script_contract import REAL_TTS_CPS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A narration line is allowed to overrun its char budget by up to this
# fraction (TTS speed has natural variance). Beyond it, the validator
# fails so the user can rewrite shorter.
NARRATION_OVERRUN_TOLERANCE = 0.10


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class NarrationLine:
    """One entry in `narration.json`."""

    beat_index: int
    text: str


@dataclass
class NarrationValidationIssue:
    beat_index: int
    code: str  # "missing", "over_budget", "unknown_beat"
    message: str


@dataclass
class NarrationValidation:
    lines: list[NarrationLine]
    issues: list[NarrationValidationIssue] = field(default_factory=list)
    total_chars: int = 0

    @property
    def ok(self) -> bool:
        return not self.issues


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def build_prompt(
    beats: list[dict[str, object]],
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
    style_text: str,
    synopsis_text: str | None,
    *,
    chars_per_second: float = REAL_TTS_CPS,
) -> str:
    """Assemble the narration-writing prompt the user pastes into the LLM.

    Sections to include in order:
      1. The style file content verbatim.
      2. The synopsis (when supplied) for plot/cast context.
      3. Per-beat block: beat index, total duration, target char budget,
         the micro-shot summaries from `visual_segments`, the subtitle
         lines whose timestamps fall inside the beat's source-shot ranges.
      4. The expected reply format (a JSON list matching NarrationLine).

    Implementation: Phase 4 / Task 4.2 in plan.md.
    """
    raise NotImplementedError("Phase 4 / Task 4.2 — see plan.md")


def validate_narration(
    narration: list[NarrationLine],
    beats: list[dict[str, object]],
    *,
    chars_per_second: float = REAL_TTS_CPS,
    tolerance: float = NARRATION_OVERRUN_TOLERANCE,
) -> NarrationValidation:
    """Check that each narration line fits its beat's char budget.

    Checks performed:
      - every beat in the rough-cut manifest has a NarrationLine
      - no narration line references a beat that doesn't exist
      - every narration line's char count is within
        `total_duration_s × chars_per_second × (1 + tolerance)`

    Implementation: Phase 4 / Task 4.2 in plan.md.
    """
    raise NotImplementedError("Phase 4 / Task 4.2 — see plan.md")


def load_narration(path: Path) -> list[NarrationLine]:
    """Load `narration.json` into NarrationLine dataclasses.

    Implementation: Phase 4 / Task 4.2 in plan.md.
    """
    raise NotImplementedError("Phase 4 / Task 4.2 — see plan.md")


def dump_narration(path: Path, lines: list[NarrationLine]) -> None:
    """Serialize NarrationLine list to `narration.json`.

    Implementation: Phase 4 / Task 4.2 in plan.md.
    """
    raise NotImplementedError("Phase 4 / Task 4.2 — see plan.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="write-narration",
        description="Stage 4: assemble narration prompt or validate the LLM reply.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--rough-cut-manifest", type=Path, required=True,
                        help="Stage 3 `rough_cut.json`.")
    parser.add_argument("--visual-segments", type=Path, required=True,
                        help="Stage 0 `visual_segments.json`.")
    parser.add_argument("--subtitles-json", type=Path, required=True,
                        help="Stage 1 subtitle JSON (with timing).")
    parser.add_argument("--style", type=Path, required=True,
                        help="Style markdown file (e.g. `styles/niu-shu.md`).")
    parser.add_argument("--synopsis", type=Path,
                        help="Optional synopsis.md for plot/cast context.")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Directory for `narration_prompt.txt` and `narration.json`.")
    parser.add_argument("--validate", action="store_true",
                        help="Validate an existing `narration.json` instead of writing the prompt.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raise NotImplementedError("Phase 4 / Task 4.2 — see plan.md")


if __name__ == "__main__":
    sys.exit(main())
