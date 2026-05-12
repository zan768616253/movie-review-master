"""ffmpeg hardware-decode helpers used by Stage 1 chunking."""

from __future__ import annotations

import subprocess
from functools import lru_cache

GPU_CODEC = "h264_nvenc"


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
    """Return ffmpeg input-decoder flags. Must be placed before each ``-i``."""
    if codec == GPU_CODEC and cuda_decode_available():
        return ["-hwaccel", "cuda"]
    return []
