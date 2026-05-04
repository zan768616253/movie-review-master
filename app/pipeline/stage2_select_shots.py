"""Stage 2: select the high-information subset of shots for the review.

This is the first manual stage in the new video-driven pipeline. The module
runs in two modes:

- **scaffold mode** (default): read Stage 0's `visual_segments.json` and
  emit a `selected_shots.json` where every shot is present with
  ``keep=false``. The user opens that file in an editor and flips
  ``keep=true`` on the shots that should appear in the review.

- **validate mode** (``--validate``): read both files and verify every
  ``shot_id`` exists in the visual segments, that selection order is
  chronological, and that at least one shot is kept.

Inputs:
    <stage0_dir>/visual_segments.json   from `stage0_index_visuals.py`

Outputs:
    <out>/selected_shots.json           the selection scaffold or validated file

Manual v1 owner: the human editor.
Auto v2 owner: a future scoring module that flips ``keep`` automatically.
The output schema is identical in both modes so swapping v1 → v2 does not
require any downstream change.

This module is a skeleton — see plan.md Phase 1 for the implementation tasks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class SelectedShot:
    """One entry in `selected_shots.json`.

    `shot_id` references a visual segment from Stage 0 (e.g. ``visual:042``).
    `keep` defaults to False in the scaffold; the user flips it to True for
    every shot that should appear in the review.
    `tags` is optional, free-form labels (``hook``, ``establishing``,
    ``twist``, ``climax``, …) that downstream stages may use as hints.
    """

    shot_id: str
    start: str
    end: str
    summary: str
    keep: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass
class SelectionValidation:
    """Result of validating a `selected_shots.json` against `visual_segments.json`."""

    total: int
    kept: int
    dropped: int
    issues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def build_scaffold(visual_segments: list[dict[str, object]]) -> list[SelectedShot]:
    """Produce a SelectedShot per visual segment, all with `keep=False`.

    Order is preserved (visual segments are already chronological after
    Stage 0 validation).

    Implementation: Phase 1 / Task 1.2 in plan.md.
    """
    raise NotImplementedError("Phase 1 / Task 1.2 — see plan.md")


def validate_selection(
    visual_segments: list[dict[str, object]],
    selected_shots: list[SelectedShot],
) -> SelectionValidation:
    """Verify a user-edited selection against the canonical Stage 0 list.

    Checks performed:
      - every `shot_id` in `selected_shots` exists in `visual_segments`
      - selection is in chronological order
      - at least one shot has `keep=True` (otherwise the review is empty)

    Implementation: Phase 1 / Task 1.2 in plan.md.
    """
    raise NotImplementedError("Phase 1 / Task 1.2 — see plan.md")


def load_selected_shots(path: Path) -> list[SelectedShot]:
    """Load and parse `selected_shots.json` into SelectedShot dataclasses.

    Implementation: Phase 1 / Task 1.2 in plan.md.
    """
    raise NotImplementedError("Phase 1 / Task 1.2 — see plan.md")


def dump_selected_shots(path: Path, shots: list[SelectedShot]) -> None:
    """Serialize SelectedShot list to `selected_shots.json`.

    Implementation: Phase 1 / Task 1.2 in plan.md.
    """
    raise NotImplementedError("Phase 1 / Task 1.2 — see plan.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="select-shots",
        description="Stage 2: scaffold or validate the high-information shot selection.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--visual-segments", type=Path, required=True,
                        help="Stage 0 `visual_segments.json`.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output path for `selected_shots.json`.")
    parser.add_argument("--validate", action="store_true",
                        help="Validate an existing selection instead of scaffolding.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing scaffold file.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raise NotImplementedError("Phase 1 / Task 1.2 — see plan.md")


if __name__ == "__main__":
    sys.exit(main())
