"""One-off migration: shift `shot_boundaries_s` from chunk-local to absolute time.

Background: until 2026-04-30, ``stage0_indexers.base.merge_segments``
shifted ``start``/``end`` by chunk offset but forgot to shift the
``shot_boundaries_s`` list. As a result, 96% of inner-cut entries in
existing ``visual_segments.json`` files point one chunk earlier than
their parent segment and are silently discarded by
``split_segment_into_shots`` and ``build_shot_boundary_set``.

Re-running Stage 0 is the cleanest path forward but costs Gemini API
calls and ~10 min wall time per movie. Re-detecting scene cuts via
ffmpeg on the full movie would also work but is single-threaded and
takes 30+ min on a 100-min movie.

This script does the *cheap* fix: each segment was originally produced
in some chunk N (where N = floor(segment.start / chunk_size_s)), and
its chunk-local inner cuts need the same ``chunk_index × chunk_size_s``
offset that the segment's own ``start``/``end`` already received. We
just apply the missing shift.

Usage::

    python tmp/migrate_shot_boundaries.py            # default 5-min chunks (Gemini)
    python tmp/migrate_shot_boundaries.py --chunk-minutes 2   # OpenRouter (2-min)
    python tmp/migrate_shot_boundaries.py --check    # dry-run, prints stats only

Output: rewrites the visual_segments.json in place after writing a
``visual_segments.json.bak`` next to it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_paths, load_config, DEFAULT_CONFIG

from app.pipeline.common.script_contract import timestamp_to_seconds


def needs_shift(segment: dict, chunk_size_s: float) -> bool:
    """True if the segment has chunk-local inner cuts (not yet shifted).

    A correctly-shifted segment has every entry in shot_boundaries_s
    falling strictly inside (segment.start, segment.end) absolute. A
    chunk-local segment (the bug) has them shifted earlier by ~one
    chunk and so they fall outside the segment's absolute window.
    """
    inner = segment.get("shot_boundaries_s") or []
    if not inner:
        return False
    try:
        start_s = timestamp_to_seconds(str(segment["start"]))
        end_s = timestamp_to_seconds(str(segment["end"]))
    except (KeyError, ValueError):
        return False
    if start_s < chunk_size_s:
        # Segment is in chunk 0 — chunk-local == absolute, so the bug is
        # invisible here even on un-migrated data. Treat as already correct.
        return False
    return any(not (start_s < float(b) < end_s) for b in inner)


def shift_segments(segments: list[dict], chunk_size_s: float) -> tuple[list[dict], int]:
    """Apply the chunk offset to every chunk-local shot_boundaries_s list.

    Returns ``(new_segments, fixed_count)``. A segment is "fixed" when
    its annotation actually changed.
    """
    new_segments: list[dict] = []
    fixed = 0
    for seg in segments:
        new_seg = dict(seg)
        if needs_shift(seg, chunk_size_s):
            try:
                start_s = timestamp_to_seconds(str(seg["start"]))
            except (KeyError, ValueError):
                new_segments.append(new_seg)
                continue
            chunk_index = int(start_s // chunk_size_s)
            offset = chunk_index * chunk_size_s
            shifted: list[float] = []
            for raw in seg.get("shot_boundaries_s") or []:
                try:
                    shifted.append(round(float(raw) + offset, 3))
                except (TypeError, ValueError):
                    continue
            new_seg["shot_boundaries_s"] = shifted
            fixed += 1
        new_segments.append(new_seg)
    return new_segments, fixed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="movie TOML config")
    parser.add_argument(
        "--chunk-minutes",
        type=int,
        default=5,
        help="Stage 0 chunk size in minutes (Gemini=5, OpenRouter=2)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="dry-run: don't rewrite the JSON, just print what would change",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    paths = build_paths(cfg)

    if not paths.visual_segments.exists():
        print(f"visual_segments.json not found: {paths.visual_segments}", file=sys.stderr)
        return 1

    chunk_size_s = float(args.chunk_minutes * 60)
    print(f"Segments:    {paths.visual_segments}")
    print(f"Chunk size:  {args.chunk_minutes} min ({chunk_size_s:.0f}s)")

    segments = json.loads(paths.visual_segments.read_text(encoding="utf-8"))
    new_segments, fixed = shift_segments(segments, chunk_size_s)

    multi_shot_after = sum(
        1 for seg in new_segments if seg.get("shot_boundaries_s")
    )
    inner_cuts_after = sum(
        len(seg.get("shot_boundaries_s") or []) for seg in new_segments
    )
    misplaced_after = sum(
        1 for seg in new_segments
        if seg.get("shot_boundaries_s") and any(
            not (
                timestamp_to_seconds(str(seg["start"])) < float(b) < timestamp_to_seconds(str(seg["end"]))
            )
            for b in seg["shot_boundaries_s"]
        )
    )
    print(
        f"Segments:    {len(segments)} total, "
        f"{multi_shot_after} multi-shot ({100 * multi_shot_after / max(len(segments), 1):.1f}%)"
    )
    print(f"Inner cuts:  {inner_cuts_after} total after migration")
    print(f"Migration:   {fixed} segments shifted")
    print(f"Sanity:      {misplaced_after} segments still have boundaries outside their window")
    if misplaced_after:
        print(
            "Warning: some boundaries remain outside their segment window. "
            "This usually means a different chunk_minutes was used for this "
            "movie's Stage 0. Try --chunk-minutes 2 (OpenRouter) or 5 (Gemini)."
        )

    if args.check:
        print("(--check) skipping write")
        return 0

    backup = paths.visual_segments.with_suffix(paths.visual_segments.suffix + ".bak")
    if not backup.exists():
        backup.write_text(paths.visual_segments.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Backed up original to: {backup}")
    else:
        print(f"(backup already exists, leaving as-is: {backup})")

    paths.visual_segments.write_text(
        json.dumps(new_segments, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Rewrote: {paths.visual_segments}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
