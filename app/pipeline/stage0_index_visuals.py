"""Stage 0: Visual Indexing.
Split a long movie into chunks, use Gemini 3 Flash to index visual segments,
and merge them into a single visual_segments.json.
"""

import argparse
import sys
from pathlib import Path
from typing import Sequence

from app.pipeline.common.json_io import dump_json
from app.pipeline.common.script_contract import get_video_duration, validate_visual_segments
from app.pipeline.stage0_indexers import GeminiStrategy, OpenRouterStrategy, VisualIndexerStrategy


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="index-visuals",
        description="Stage 0: Index visuals using a configured VLM strategy.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--video", type=Path, required=True, help="Path to full movie file")
    parser.add_argument("--output", type=Path, help="Path to output visual_segments.json")
    parser.add_argument("--tmp-dir", type=Path, default=Path("tmp/indexing"), help="Temp directory for chunks")
    parser.add_argument(
        "--strategy",
        choices=["gemini", "openrouter"],
        default="gemini",
        help="Visual indexing backend to use",
    )
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=5,
        help="Parallel chunk workers for uncached provider requests",
    )
    return parser


def _build_strategy(name: str, max_workers: int) -> VisualIndexerStrategy:
    if name == "gemini":
        return GeminiStrategy(max_workers=max_workers)
    if name == "openrouter":
        return OpenRouterStrategy(max_workers=max_workers)
    raise ValueError(f"Unsupported strategy: {name}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    video_path = args.video.expanduser().resolve()

    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}")
        return 1

    args.tmp_dir.mkdir(parents=True, exist_ok=True)

    strategy = _build_strategy(args.strategy, args.workers)

    try:
        raw_segments = strategy.index_video(video_path, args.tmp_dir)

        video_duration_s = get_video_duration(video_path)
        segments, diagnostics = validate_visual_segments(raw_segments, video_duration_s)
        if diagnostics.clamped_to_eof or diagnostics.dropped_bad_range or diagnostics.dropped_past_eof or diagnostics.dropped_too_long:
            print(f"Visual segment validation: {diagnostics.as_summary()} (movie duration {video_duration_s:.1f}s)")

        output_path = args.output if args.output else video_path.parent / "visual_segments.json"
        dump_json(output_path, segments)

        print(f"\nSuccess! Kept {len(segments)}/{len(raw_segments)} segments -> {output_path}")
    except Exception as e:
        print(f"Error during processing: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
