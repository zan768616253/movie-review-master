from __future__ import annotations

import json
import os
import subprocess
import time

from pathlib import Path
from typing import Dict, List

from google import genai
from google.genai import types

from app.pipeline.common.video_encoder import hwaccel_decode_args, nvenc_available
from .base import detect_shot_boundaries, get_video_duration
from .shared import (
    ChunkedVisualIndexerStrategy,
    DEFAULT_SHOT_DETECT_THRESHOLD,
    DEFAULT_SHOT_SNAP_TOLERANCE_S,
    DEFAULT_TIMESTAMP_FONT_PATH as SHARED_DEFAULT_TIMESTAMP_FONT_PATH,
    PROMPT,
    build_timestamp_drawtext_filter as _build_timestamp_drawtext_filter,
)

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_CHUNK_MINUTES = 5
DEFAULT_TIMESTAMP_FONT_PATH = SHARED_DEFAULT_TIMESTAMP_FONT_PATH


def build_timestamp_drawtext_filter() -> str:
    return _build_timestamp_drawtext_filter(DEFAULT_TIMESTAMP_FONT_PATH)


_SEGMENT_ITEM_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "start": types.Schema(type=types.Type.STRING),
        "end": types.Schema(type=types.Type.STRING),
        "summary": types.Schema(type=types.Type.STRING),
        "ocr_text": types.Schema(type=types.Type.STRING),
        "characters": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(type=types.Type.STRING),
        ),
    },
    required=["start", "end", "summary", "ocr_text", "characters"],
)

_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.ARRAY,
    items=_SEGMENT_ITEM_SCHEMA,
)


class GeminiStrategy(ChunkedVisualIndexerStrategy):
    def __init__(self, api_key: str | None = None, max_workers: int = 1):
        key = api_key if api_key is not None else os.getenv("GOOGLE_API_KEY")
        self.api_key = key
        super().__init__(
            provider_label="Gemini",
            model_name=DEFAULT_MODEL,
            max_workers=max_workers,
            chunk_minutes=DEFAULT_CHUNK_MINUTES,
            shot_snap_tolerance_s=DEFAULT_SHOT_SNAP_TOLERANCE_S,
            shot_detect_threshold=DEFAULT_SHOT_DETECT_THRESHOLD,
        )

    def _get_video_duration(self, video_path: Path) -> float:
        return get_video_duration(video_path)

    def _detect_shot_boundaries(self, video_path: Path) -> List[float]:
        return detect_shot_boundaries(video_path, threshold=self.shot_detect_threshold)

    def _create_client(self) -> genai.Client:
        return genai.Client(api_key=self.api_key)

    def _extract_chunk(self, video_path: Path, start_s: float, duration_s: float, out_path: Path) -> None:
        if nvenc_available():
            codec = "h264_nvenc"
            video_args = ["-c:v", "h264_nvenc", "-preset", "p1", "-pix_fmt", "yuv420p"]
        else:
            codec = "libx264"
            video_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            *hwaccel_decode_args(codec),
            "-ss", str(start_s), "-t", str(duration_s),
            "-i", str(video_path),
            "-vf", build_timestamp_drawtext_filter(),
            *video_args,
            "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)

    def _index_chunk(self, video_chunk_path: Path) -> List[Dict]:
        client = self._create_client()
        print(f"Uploading {video_chunk_path.name} to Gemini...")
        video_file = client.files.upload(file=str(video_chunk_path))
        video_file_name: str | None = None

        state = video_file.state
        if state is None:
            raise ValueError(f"Unexpected missing state for uploaded file: {video_file}")
        state_name = state.name
        if state_name is None:
            raise ValueError(f"Unexpected missing state for uploaded file: {video_file}")
        if video_file.name is None:
            raise ValueError(f"Uploaded file missing name: {video_file}")
        video_file_name = video_file.name

        try:
            while state_name == "PROCESSING":
                time.sleep(3)
                video_file = client.files.get(name=video_file_name)
                state = video_file.state
                if state is None:
                    raise ValueError(f"Unexpected missing state for uploaded file: {video_file}")
                state_name = state.name
                if state_name is None:
                    raise ValueError(f"Unexpected missing state for uploaded file: {video_file}")
                if video_file.name is None:
                    raise ValueError(f"Uploaded file missing name: {video_file}")
                video_file_name = video_file.name

            if state_name == "FAILED":
                raise ValueError(f"Video processing failed for {video_chunk_path}")

            print(f"Requesting inference for {video_chunk_path.name}...")
            response = client.models.generate_content(
                model=self.model_name,
                contents=[video_file, PROMPT],
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                ),
            )
            if not response.text:
                raise ValueError(f"Empty response for {video_chunk_path}")

            try:
                return json.loads(response.text)
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON for {video_chunk_path.name}. Raw text snippet: {response.text[:200]}")
                raise e
        finally:
            if video_file_name is not None:
                try:
                    client.files.delete(name=video_file_name)
                except Exception:
                    pass
