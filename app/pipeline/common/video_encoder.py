"""GPU-only video encoder helpers shared by Stage 4 and Stage 5."""

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


def resolve_encoder() -> str:
    """Return the required GPU codec or raise when ffmpeg cannot use it."""
    if not nvenc_available():
        raise RuntimeError(
            "GPU-only video processing requires ffmpeg with the h264_nvenc encoder, but it is not available."
        )
    if not cuda_decode_available():
        raise RuntimeError(
            "GPU-only video processing requires ffmpeg with CUDA hwaccel decoding, but it is not available."
        )
    return GPU_CODEC


def encoder_ffmpeg_args(codec: str) -> list[str]:
    """Return the ffmpeg -c:v ... arguments for the required GPU codec."""
    if codec == GPU_CODEC:
        return [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", "23",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
        ]
    raise ValueError(f"Unsupported codec: {codec}")
