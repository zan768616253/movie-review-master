"""Video encoder selection shared by Stage 4 and Stage 5.

The pipeline prefers NVENC on the RTX 4060 so long re-encodes stay off the
CPU. On hosts without NVENC (CI, laptops without a discrete GPU) the helpers
fall back to libx264 so the pipeline still runs.
"""

from __future__ import annotations

import subprocess
from functools import lru_cache

ENCODER_CHOICES = ("auto", "nvenc", "libx264")
DEFAULT_ENCODER = "auto"


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """Return True when the local ffmpeg advertises h264_nvenc."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "h264_nvenc" in result.stdout


@lru_cache(maxsize=1)
def cuda_decode_available() -> bool:
    """Return True when the local ffmpeg lists cuda as a hwaccel."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-hwaccels"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return "cuda" in result.stdout


def hwaccel_decode_args(codec: str) -> list[str]:
    """Return ffmpeg input-decoder flags. Must be placed before each ``-i``.

    Only enabled when the chosen encoder is NVENC and the local ffmpeg
    advertises cuda. Decoding in software while encoding on NVENC still
    works, but we prefer full GPU when available — it halves wallclock on
    long re-encodes and keeps the CPU free for everything else.
    """
    if codec == "h264_nvenc" and cuda_decode_available():
        return ["-hwaccel", "cuda"]
    return []


def resolve_encoder(requested: str) -> str:
    """Map an --encoder flag value to the concrete ffmpeg codec name."""
    if requested == "auto":
        return "h264_nvenc" if nvenc_available() else "libx264"
    if requested == "nvenc":
        return "h264_nvenc"
    if requested == "libx264":
        return "libx264"
    raise ValueError(f"Unsupported encoder choice: {requested}")


def encoder_ffmpeg_args(codec: str) -> list[str]:
    """Return the ffmpeg -c:v ... arguments for a resolved codec name.

    Presets are tuned for 1080p30 draft renders: NVENC uses p4/vbr/cq23
    (good quality at ~3-5x realtime on a 4060), libx264 uses preset=fast
    so CI fallback is tolerable.
    """
    if codec == "h264_nvenc":
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "23",
            "-pix_fmt", "yuv420p",
        ]
    if codec == "libx264":
        return [
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
        ]
    raise ValueError(f"Unsupported codec: {codec}")
