"""Finalize an upload-ready MP4 from the draft render and narration track.

Reads the Stage 6 draft review (`review.mp4`) and the Stage 3 voiceover,
then remuxes the Stage 6 video stream with the Stage 3 narration track into
an MP4 with `+faststart`, ready for direct upload.

Outputs:

    <output_dir>/final_video.mp4        upload-ready master
    <output_dir>/delivery_manifest.json stage-7 delivery metadata
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from app.pipeline.common.json_io import dump_json


DEFAULT_AUDIO_BITRATE = "192k"
DEFAULT_MANIFEST_NAME = "delivery_manifest.json"


def default_manifest_path(output_path: Path) -> Path:
    return output_path.parent / DEFAULT_MANIFEST_NAME


def build_ffmpeg_command(
    review_video: Path,
    voiceover: Path,
    output_path: Path,
    *,
    audio_bitrate: str = DEFAULT_AUDIO_BITRATE,
) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(review_video),
        "-i",
        str(voiceover),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]


def write_delivery_manifest(
    out_path: Path,
    review_video: Path,
    voiceover: Path,
    output_path: Path,
) -> None:
    dump_json(
        out_path,
        {
            "stage": 7,
            "video_source": str(review_video),
            "audio_source": str(voiceover),
            "output": str(output_path),
            "video_codec": "copy",
            "audio_codec": "aac",
            "audio_bitrate": DEFAULT_AUDIO_BITRATE,
            "movflags": "+faststart",
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finalize-video",
        description="Mux the Stage 6 draft render with the Stage 3 narration track.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--review-video", type=Path, required=True,
                        help="Stage 6 draft render MP4.")
    parser.add_argument("--voiceover", type=Path, required=True,
                        help="Stage 3 voiceover MP3.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Upload-ready final_video.mp4 path.")
    parser.add_argument("--manifest-output", type=Path,
                        help="Optional override for the stage-7 delivery manifest path.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    args.review_video = args.review_video.expanduser().resolve()
    args.voiceover = args.voiceover.expanduser().resolve()
    args.output = args.output.expanduser().resolve()
    if args.manifest_output is not None:
        args.manifest_output = args.manifest_output.expanduser().resolve()
    else:
        args.manifest_output = default_manifest_path(args.output)

    if not args.review_video.exists():
        print(f"Review video not found: {args.review_video}", file=sys.stderr)
        return 1
    if not args.voiceover.exists():
        print(f"Voiceover not found: {args.voiceover}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            build_ffmpeg_command(args.review_video, args.voiceover, args.output),
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed while finalizing upload video: {exc}", file=sys.stderr)
        return 1

    write_delivery_manifest(
        args.manifest_output,
        args.review_video,
        args.voiceover,
        args.output,
    )

    print(f"[done] {args.output}")
    print(f"[manifest] {args.manifest_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
