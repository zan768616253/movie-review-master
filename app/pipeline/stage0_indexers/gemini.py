import os
import json
import time
import subprocess

from pathlib import Path
from typing import Dict, List
from google import genai
from google.genai import types

from app.pipeline.common.video_encoder import hwaccel_decode_args, nvenc_available
from .base import VisualIndexerStrategy, get_video_duration, merge_segments

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_CHUNK_MINUTES = 10
DEFAULT_SEGMENT_PACE = "2-3"


class GeminiStrategy(VisualIndexerStrategy):
    def __init__(self):
        key = os.getenv("GOOGLE_API_KEY")        
        self.client = genai.Client(api_key=key)
        self.model_name = DEFAULT_MODEL

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
            *video_args,
            "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]
        subprocess.run(cmd, check=True)

    def _index_chunk(self, video_chunk_path: Path) -> List[Dict]:
        print(f"Uploading {video_chunk_path.name} to Gemini...")
        video_file = self.client.files.upload(file=str(video_chunk_path))

        while video_file.state.name == "PROCESSING":
            time.sleep(3)
            video_file = self.client.files.get(name=video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError(f"Video processing failed for {video_chunk_path}")

        prompt = f"""
        Analyze the uploaded video and return a JSON array of visual segments.
        The goal is to index the video for visual action. You do not need to transcribe dialogue.

        CRITICAL REQUIREMENT: Break the video down into VERY FINE-GRAINED segments.
        Each segment MUST be approximately {DEFAULT_SEGMENT_PACE} seconds long.
        Every single time the camera cuts to a new shot, or a character performs a new distinct motion, start a new segment.

        Follow this JSON schema for each segment:
        {{
          "start": "00:00:00.000",
          "end": "00:00:03.500",
          "summary": "description of the action",
          "ocr_text": "any on screen text, or empty string if none",
          "is_action": true,
          "confidence": 0.99,
                    "characters": ["list of visually identifiable characters"]
        }}

        Identify recurring or visually obvious characters when you are confident.
        If a character cannot be identified from visuals alone, leave "characters" empty for that segment.

        Respond ONLY with the raw JSON array. Do not wrap it in markdown block quotes.
        """

        print(f"Requesting inference for {video_chunk_path.name}...")
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[video_file, prompt],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH),
            ),
        )

        self.client.files.delete(name=video_file.name)

        raw_text = response.text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON for {video_chunk_path.name}. Raw text snippet: {raw_text[:200]}")
            raise e

    def index_video(self, video_path: Path, tmp_dir: Path) -> List[Dict]:
        duration = get_video_duration(video_path)
        chunk_size_s = DEFAULT_CHUNK_MINUTES * 60
        num_chunks = int((duration + chunk_size_s - 1) // chunk_size_s)

        print(
            f"Gemini Stage 0 running. Video duration: {duration:.2f}s, "
            f"splitting into {num_chunks} chunks of {DEFAULT_CHUNK_MINUTES} minutes."
        )

        all_results = []
        for i in range(num_chunks):
            start_s = i * chunk_size_s
            current_chunk_duration = min(chunk_size_s, duration - start_s)

            chunk_path = tmp_dir / f"chunk_{i:03d}.mp4"
            if not chunk_path.exists():
                self._extract_chunk(video_path, start_s, current_chunk_duration, chunk_path)

            chunk_data = self._index_chunk(chunk_path)
            all_results.append(chunk_data)

        return merge_segments(all_results, chunk_size_s)
