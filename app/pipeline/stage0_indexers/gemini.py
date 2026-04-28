from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import subprocess
import time

from pathlib import Path
from typing import Dict, List

from google import genai
from google.genai import types

from app.pipeline.common.json_io import dump_json, load_json
from app.pipeline.common.video_encoder import hwaccel_decode_args, nvenc_available
from .base import (
    VisualIndexerStrategy,
    detect_shot_boundaries,
    get_video_duration,
    merge_segments,
    snap_to_shot_boundaries,
)

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_CHUNK_MINUTES = 5
DEFAULT_SHOT_SNAP_TOLERANCE_S = 1.5
DEFAULT_SHOT_DETECT_THRESHOLD = 0.3
DEFAULT_TIMESTAMP_FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")


def build_timestamp_drawtext_filter() -> str:
    font_prefix = ""
    if DEFAULT_TIMESTAMP_FONT_PATH.exists():
        font_prefix = f"fontfile={DEFAULT_TIMESTAMP_FONT_PATH}:"
    return (
        "drawtext="
        f"{font_prefix}"
        r"text='%{pts\:hms}':"
        "x=12:y=12:"
        "fontsize=28:fontcolor=white:"
        "box=1:boxcolor=black@0.7:boxborderw=6"
    )


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


PROMPT = """\
# Role
You are indexing a movie for VISUAL events only. Dialogue is indexed separately from SRT subtitles; do NOT duplicate dialogue coverage here.

# Timestamps (critical)
A chunk-local timestamp in HH:MM:SS.mmm is burned into the TOP-LEFT corner of every frame.
- Read it directly from the frame. Do NOT estimate or round timestamps from context.
- Every "start" and "end" you emit MUST match a timestamp visible in an actual frame.
- Timestamps are relative to this chunk (it always starts at 00:00:00.000), NOT the full movie.

# What to emit
Emit one segment per visually distinct event: a shot cut, a location change, a notable character action, or a significant on-screen text appearance.
- Typical segment length: 2-8 seconds. HARD MAXIMUM: 12 seconds.
- No forced minimum. A 1-second shot cut is a valid segment.
- Let the visible event define the duration. Do NOT invent transitions to fill time.

# What to SKIP (emit nothing for these)
- Pure shot-reverse-shot dialogue with no notable visual change (handled by SRT).
- Long static shots where nothing new is happening - wait for the next visible change.
- Any moment you cannot confidently describe. Omission is always better than a guess.

# Field rules
- summary: one short phrase describing the visible action. No dialogue paraphrasing.
- ocr_text: transcribe on-screen text clearly visible in-scene. Do NOT transcribe the burned-in timestamp in the top-left corner. Empty string if nothing.
- characters: only include a character you can visually re-identify across MULTIPLE segments in THIS chunk. If unsure, leave empty. NEVER guess from general knowledge or franchise assumptions.

# Self-check before returning
- every start < end
- segments are in strictly ascending time order
- no segment longer than 12 seconds
- no start or end exceeds the chunk length
"""


class GeminiStrategy(VisualIndexerStrategy):
    def __init__(self, api_key: str | None = None, max_workers: int = 1):
        key = api_key if api_key is not None else os.getenv("GOOGLE_API_KEY")
        self.api_key = key
        self.model_name = DEFAULT_MODEL
        self.max_workers = max(1, max_workers)

    def _create_client(self) -> genai.Client:
        return genai.Client(api_key=self.api_key)

    def _chunk_paths(self, tmp_dir: Path, chunk_index: int) -> tuple[Path, Path]:
        chunk_path = tmp_dir / f"chunk_{chunk_index:03d}.mp4"
        segments_path = tmp_dir / "segments" / f"chunk_{chunk_index:03d}.json"
        return chunk_path, segments_path

    def _load_cached_chunk_segments(self, segments_path: Path) -> List[Dict] | None:
        if not segments_path.exists():
            return None

        try:
            cached_segments = load_json(segments_path)
        except Exception as exc:
            print(f"  {segments_path.stem}: cache read failed ({exc}); reprocessing")
            return None

        if not isinstance(cached_segments, list):
            print(f"  {segments_path.stem}: cache payload is not a list; reprocessing")
            return None

        print(f"  {segments_path.stem}: reusing cached segments from {segments_path}")
        return cached_segments

    def _persist_chunk_segments(self, segments_path: Path, chunk_segments: List[Dict]) -> None:
        temp_path = segments_path.with_suffix(".tmp")
        dump_json(temp_path, chunk_segments)
        temp_path.replace(segments_path)

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

    def _process_chunk(
        self,
        video_path: Path,
        tmp_dir: Path,
        chunk_index: int,
        start_s: float,
        duration_s: float,
    ) -> List[Dict]:
        chunk_path, segments_path = self._chunk_paths(tmp_dir, chunk_index)

        cached_segments = self._load_cached_chunk_segments(segments_path)
        if cached_segments is not None:
            return cached_segments

        if not chunk_path.exists():
            self._extract_chunk(video_path, start_s, duration_s, chunk_path)

        chunk_segments = self._index_chunk(chunk_path)

        boundaries = detect_shot_boundaries(chunk_path, threshold=DEFAULT_SHOT_DETECT_THRESHOLD)
        print(
            f"  chunk_{chunk_index:03d}: {len(chunk_segments)} segments, "
            f"{len(boundaries)} shot cuts; snapping within {DEFAULT_SHOT_SNAP_TOLERANCE_S}s"
        )
        chunk_segments = snap_to_shot_boundaries(
            chunk_segments,
            boundaries,
            tolerance_s=DEFAULT_SHOT_SNAP_TOLERANCE_S,
        )
        self._persist_chunk_segments(segments_path, chunk_segments)
        print(f"  chunk_{chunk_index:03d}: cached segments -> {segments_path}")
        return chunk_segments

    def _process_chunk_job(
        self,
        video_path: Path,
        tmp_dir: Path,
        chunk_index: int,
        start_s: float,
        duration_s: float,
    ) -> tuple[int, List[Dict]]:
        return chunk_index, self._process_chunk(video_path, tmp_dir, chunk_index, start_s, duration_s)

    def index_video(self, video_path: Path, tmp_dir: Path) -> List[Dict]:
        duration = get_video_duration(video_path)
        chunk_size_s = DEFAULT_CHUNK_MINUTES * 60
        num_chunks = int((duration + chunk_size_s - 1) // chunk_size_s)
        (tmp_dir / "segments").mkdir(parents=True, exist_ok=True)

        print(
            f"Gemini Stage 0 running. Video duration: {duration:.2f}s, "
            f"splitting into {num_chunks} chunks of {DEFAULT_CHUNK_MINUTES} minutes."
        )
        if self.max_workers > 1:
            print(
                f"Stage 0 concurrency enabled with {self.max_workers} workers for missing chunk caches. "
                "Higher values can increase 503 risk."
            )

        chunk_specs = []
        for i in range(num_chunks):
            start_s = i * chunk_size_s
            current_chunk_duration = min(chunk_size_s, duration - start_s)
            chunk_specs.append((i, start_s, current_chunk_duration))

        if self.max_workers == 1:
            all_results = [
                self._process_chunk(video_path, tmp_dir, chunk_index, start_s, current_chunk_duration)
                for chunk_index, start_s, current_chunk_duration in chunk_specs
            ]
        else:
            chunk_results_by_index: dict[int, List[Dict]] = {}
            first_error: Exception | None = None
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        self._process_chunk_job,
                        video_path,
                        tmp_dir,
                        chunk_index,
                        start_s,
                        current_chunk_duration,
                    ): chunk_index
                    for chunk_index, start_s, current_chunk_duration in chunk_specs
                }
                for future in as_completed(futures):
                    try:
                        chunk_index, chunk_segments = future.result()
                    except Exception as exc:
                        if first_error is None:
                            first_error = exc
                        continue
                    chunk_results_by_index[chunk_index] = chunk_segments

            if first_error is not None:
                raise first_error

            all_results = [chunk_results_by_index[i] for i in range(num_chunks)]

        return merge_segments(all_results, chunk_size_s)
