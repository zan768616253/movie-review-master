from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

from pathlib import Path
from typing import Any, Dict, List

from app.pipeline.common.video_encoder import hwaccel_decode_args, nvenc_available
from .shared import (
    ChunkedVisualIndexerStrategy,
    DEFAULT_SHOT_DETECT_THRESHOLD,
    DEFAULT_SHOT_SNAP_TOLERANCE_S,
    PROMPT,
    build_timestamp_drawtext_filter,
)

DEFAULT_MODEL = "qwen/qwen2.5-vl-72b-instruct"
DEFAULT_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_CHUNK_MINUTES = 2
DEFAULT_REQUEST_TIMEOUT_S = 600
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_S = 5
DEFAULT_APP_TITLE = "movie-review-master"

_SEGMENT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start": {"type": "string", "description": "Chunk-local start timestamp in HH:MM:SS.mmm."},
        "end": {"type": "string", "description": "Chunk-local end timestamp in HH:MM:SS.mmm."},
        "summary": {"type": "string", "description": "Short phrase describing the visible action."},
        "ocr_text": {"type": "string", "description": "Visible on-screen text, excluding the burned-in timestamp."},
        "characters": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Only characters visually re-identified across multiple segments in this chunk.",
        },
    },
    "required": ["start", "end", "summary", "ocr_text", "characters"],
    "additionalProperties": False,
}

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "visual_segments",
        "strict": True,
        "schema": {
            "type": "array",
            "items": _SEGMENT_ITEM_SCHEMA,
        },
    },
}


class OpenRouterStrategy(ChunkedVisualIndexerStrategy):
    def __init__(self, api_key: str | None = None, max_workers: int = 1):
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY")
        super().__init__(
            provider_label="OpenRouter",
            model_name=DEFAULT_MODEL,
            max_workers=max_workers,
            chunk_minutes=DEFAULT_CHUNK_MINUTES,
            shot_snap_tolerance_s=DEFAULT_SHOT_SNAP_TOLERANCE_S,
            shot_detect_threshold=DEFAULT_SHOT_DETECT_THRESHOLD,
        )
        self.api_url = os.getenv("OPENROUTER_API_URL", DEFAULT_API_URL)
        self.http_referer = os.getenv("OPENROUTER_REFERER")
        self.app_title = os.getenv("OPENROUTER_TITLE", DEFAULT_APP_TITLE)
        self.request_timeout_s = DEFAULT_REQUEST_TIMEOUT_S

    def _extract_chunk(self, video_path: Path, start_s: float, duration_s: float, out_path: Path) -> None:
        if nvenc_available():
            codec = "h264_nvenc"
            video_args = [
                "-c:v", "h264_nvenc",
                "-preset", "p1",
                "-cq", "32",
                "-b:v", "0",
                "-pix_fmt", "yuv420p",
            ]
        else:
            codec = "libx264"
            video_args = [
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "32",
                "-pix_fmt", "yuv420p",
            ]
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            *hwaccel_decode_args(codec),
            "-ss", str(start_s), "-t", str(duration_s),
            "-i", str(video_path),
            "-vf", f"scale='min(960,iw)':-2,{build_timestamp_drawtext_filter()}",
            *video_args,
            "-an",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)

    def _build_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("OpenRouter API key missing. Set OPENROUTER_API_KEY or pass api_key.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.app_title:
            headers["X-OpenRouter-Title"] = self.app_title
        return headers

    def _inline_video_data_url(self, video_chunk_path: Path) -> str:
        encoded_video = base64.b64encode(video_chunk_path.read_bytes()).decode("ascii")
        return f"data:video/mp4;base64,{encoded_video}"

    def _request_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._build_headers(),
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.request_timeout_s) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body)
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_error = ValueError(
                    f"OpenRouter request failed with HTTP {exc.code}: {error_body[:400]}"
                )
                if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == DEFAULT_MAX_RETRIES:
                    raise last_error from exc
            except urllib.error.URLError as exc:
                last_error = ValueError(f"OpenRouter request failed: {exc.reason}")
                if attempt == DEFAULT_MAX_RETRIES:
                    raise last_error from exc
            time.sleep(DEFAULT_RETRY_BACKOFF_S * attempt)

        raise last_error or ValueError("OpenRouter request failed")

    def _extract_response_text(self, response_body: dict[str, Any]) -> str:
        try:
            content = response_body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"Unexpected OpenRouter response payload: {response_body}") from exc

        if isinstance(content, str) and content.strip():
            return content

        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            joined = "".join(text_parts).strip()
            if joined:
                return joined

        raise ValueError(f"OpenRouter response missing text content: {response_body}")

    def _index_chunk(self, video_chunk_path: Path) -> List[Dict]:
        video_size_mib = video_chunk_path.stat().st_size / (1024 * 1024)
        print(
            f"Sending {video_chunk_path.name} to OpenRouter ({self.model_name}, {video_size_mib:.1f} MiB inline video)..."
        )
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "video_url", "video_url": {"url": self._inline_video_data_url(video_chunk_path)}},
                    ],
                }
            ],
            "response_format": _RESPONSE_FORMAT,
            "provider": {"require_parameters": True},
            "plugins": [{"id": "response-healing"}],
            "temperature": 0,
        }
        response_body = self._request_completion(payload)
        response_text = self._extract_response_text(response_body)

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            print(
                "Failed to parse JSON for "
                f"{video_chunk_path.name}. Raw text snippet: {response_text[:200]}"
            )
            raise exc