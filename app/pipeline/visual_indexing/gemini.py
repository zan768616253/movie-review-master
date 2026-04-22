import os
import json
import time
import subprocess
from pathlib import Path
from typing import List, Dict
import google.generativeai as genai

from .base import VisualIndexerStrategy, get_video_duration, seconds_to_timestamp, merge_segments

DEFAULT_MODEL = "models/gemini-3-flash-preview"
DEFAULT_SEGMENT_PACE = "3"

class GeminiStrategy(VisualIndexerStrategy):
    def __init__(self, api_key: str | None = None, model_name: str = DEFAULT_MODEL):
        key = api_key or os.getenv("GOOGLE_API_KEY")
        if key:
            genai.configure(api_key=key)
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)

    def _extract_chunk(self, video_path: Path, start_s: float, duration_s: float, out_path: Path) -> None:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start_s), "-t", str(duration_s),
            "-i", str(video_path),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k",
            str(out_path)
        ]
        subprocess.run(cmd, check=True)

    def _index_chunk(self, video_chunk_path: Path, characters: List[str] | None = None) -> List[Dict]:
        print(f"Uploading {video_chunk_path.name} to Gemini...")
        video_file = genai.upload_file(path=str(video_chunk_path))
        
        while video_file.state.name == "PROCESSING":
            time.sleep(5)
            video_file = genai.get_file(video_file.name)
            
        if video_file.state.name == "FAILED":
            raise ValueError(f"Video processing failed for {video_chunk_path}")

        char_str = ", ".join(characters) if characters else "Identify main characters."
        
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
          "characters": ["list of characters identified"]
        }}

        Main characters to look for: {char_str}

        Respond ONLY with the raw JSON array. Do not wrap it in markdown block quotes.
        """
        
        print(f"Requesting inference for {video_chunk_path.name}...")
        response = self.model.generate_content([video_file, prompt], request_options={"timeout": 600})
        
        genai.delete_file(video_file.name)
        
        raw_text = response.text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON for {video_chunk_path.name}. Raw text snippet: {raw_text[:200]}")
            raise e

    def index_video(self, video_path: Path, characters: List[str], chunk_minutes: int, tmp_dir: Path) -> List[Dict]:
        duration = get_video_duration(video_path)
        chunk_size_s = chunk_minutes * 60
        num_chunks = int((duration + chunk_size_s - 1) // chunk_size_s)
        
        print(f"Gemini Option A running. Video duration: {duration:.2f}s, splitting into {num_chunks} chunks.")
        
        all_results = []
        for i in range(num_chunks):
            start_s = i * chunk_size_s
            current_chunk_duration = min(chunk_size_s, duration - start_s)
            
            chunk_path = tmp_dir / f"chunk_{i:03d}.mp4"
            if not chunk_path.exists():
                self._extract_chunk(video_path, start_s, current_chunk_duration, chunk_path)
            
            chunk_data = self._index_chunk(chunk_path, characters=characters)
            all_results.append(chunk_data)
            
        return merge_segments(all_results, chunk_size_s)
