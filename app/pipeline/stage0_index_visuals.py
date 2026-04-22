"""Stage 0: Visual Indexing.
Split a long movie into chunks, use Gemini 3 Flash or Ollama local models to index visual segments,
and merge them into a single visual_segments.json.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from app.pipeline.visual_indexing import GeminiStrategy, OllamaStrategy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="index-visuals",
        description="Stage 0: Index visuals using Gemini or Ollama.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--video", type=Path, required=True, help="Path to full movie file")
    parser.add_argument("--output", type=Path, help="Path to output visual_segments.json")
    parser.add_argument("--characters", type=str, help="Comma-separated list of characters to identify")
    parser.add_argument("--chunk-minutes", type=int, default=10, help="Split movie into X minute chunks")
    parser.add_argument("--tmp-dir", type=Path, default=Path("tmp/indexing"), help="Temp directory for chunks")

    parser.add_argument(
        "--strategy",
        type=str,
        choices=["gemini", "ollama"],
        default="gemini",
        help="Backend strategy to use for visual extraction",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    video_path = args.video.expanduser().resolve()

    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}")
        return 1

    characters = [c.strip() for c in args.characters.split(",")] if args.characters else []
    args.tmp_dir.mkdir(parents=True, exist_ok=True)

    if args.strategy == "gemini":
        strategy = GeminiStrategy()
    else:
        strategy = OllamaStrategy()

    try:
        segments = strategy.index_video(video_path, characters, args.chunk_minutes, args.tmp_dir)

        output_path = args.output if args.output else video_path.parent / "visual_segments.json"
        output_path.write_text(json.dumps(segments, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\nSuccess! Found {len(segments)} segments using {args.strategy} strategy -> {output_path}")
    except Exception as e:
        print(f"Error during processing: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
