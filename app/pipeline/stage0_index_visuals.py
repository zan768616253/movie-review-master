"""Stage 0: Visual Indexing.
Split a long movie into chunks, use Gemini 3 Flash to index visual segments,
and merge them into a single visual_segments.json.
"""

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Sequence
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv(".env")

DEFAULT_MODEL = "models/gemini-3-flash-preview"
DEFAULT_CHUNK_MINUTES = 10
DEFAULT_SEGMENT_PACE = "3"

@dataclass
class VisualSegment:
    start: str
    end: str
    summary: str
    ocr_text: str
    is_action: bool
    confidence: float
    characters: list[str]

def get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(result.stdout.strip())

def seconds_to_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"

def timestamp_to_seconds(ts: str) -> float:
    """Convert HH:MM:SS.mmm or HH:MM:SS format to seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(ts)

def extract_chunk(video_path: Path, start_s: float, duration_s: float, out_path: Path) -> None:
    """Extract a fast-encoded chunk for Gemini processing."""
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-ss", str(start_s),
        "-t", str(duration_s),
        "-i", str(video_path),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        str(out_path)
    ]
    subprocess.run(cmd, check=True)

class GeminiVisualIndexer:
    def __init__(self, api_key: str | None = None, model_name: str = DEFAULT_MODEL):
        if api_key:
            genai.configure(api_key=api_key)
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)

    def index_chunk(self, video_chunk_path: Path, characters: list[str] | None = None) -> list[dict]:
        """Upload chunk to Gemini and return segment list."""
        print(f"Uploading {video_chunk_path.name} to Gemini...")
        video_file = genai.upload_file(path=str(video_chunk_path))
        
        # Wait for processing
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
        
        # Cleanup
        genai.delete_file(video_file.name)
        
        raw_text = response.text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON for {video_chunk_path.name}. Raw text snippet: {raw_text[:200]}")
            raise e

def merge_segments(all_chunks_results: list[list[dict]], chunk_duration_s: float) -> list[dict]:
    """Merge segments from multiple chunks, adjusting timestamps."""
    merged = []
    for i, chunk_results in enumerate(all_chunks_results):
        offset = i * chunk_duration_s
        for seg in chunk_results:
            # Adjust timestamps
            start_s = timestamp_to_seconds(seg["start"]) + offset
            end_s = timestamp_to_seconds(seg["end"]) + offset
            
            seg["start"] = seconds_to_timestamp(start_s)
            seg["end"] = seconds_to_timestamp(end_s)
            merged.append(seg)
    return merged

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="index-visuals",
        description="Stage 0: Index visuals using Gemini 3 Flash.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--video", type=Path, required=True, help="Path to full movie file")
    parser.add_argument("--output", type=Path, help="Path to output visual_segments.json")
    parser.add_argument("--characters", type=str, help="Comma-separated list of characters to identify")
    parser.add_argument("--chunk-minutes", type=int, default=DEFAULT_CHUNK_MINUTES, help="Split movie into X minute chunks")
    parser.add_argument("--tmp-dir", type=Path, default=Path("tmp/indexing"), help="Temp directory for chunks")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Gemini model name")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    video_path = args.video.expanduser().resolve()
    
    if not video_path.exists():
        print(f"Error: Video file not found: {video_path}")
        return 1
    
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found in (.env) or environment")
        return 1

    characters = [c.strip() for c in args.characters.split(",")] if args.characters else []
    
    duration = get_video_duration(video_path)
    chunk_size_s = args.chunk_minutes * 60
    num_chunks = int((duration + chunk_size_s - 1) // chunk_size_s)
    
    print(f"Video duration: {seconds_to_timestamp(duration)} ({duration:.2f}s)")
    print(f"Splitting into {num_chunks} chunks of {args.chunk_minutes} minutes each.")
    
    args.tmp_dir.mkdir(parents=True, exist_ok=True)
    indexer = GeminiVisualIndexer(api_key=api_key, model_name=args.model)
    
    all_results = []
    
    try:
        for i in range(num_chunks):
            start_s = i * chunk_size_s
            # Don't exceed duration
            current_chunk_duration = min(chunk_size_s, duration - start_s)
            
            chunk_path = args.tmp_dir / f"chunk_{i:03d}.mp4"
            print(f"--- Processing Chunk {i+1}/{num_chunks} ({seconds_to_timestamp(start_s)}) ---")
            
            if not chunk_path.exists():
                extract_chunk(video_path, start_s, current_chunk_duration, chunk_path)
            
            chunk_data = indexer.index_chunk(chunk_path, characters=characters)
            all_results.append(chunk_data)
            
            # Optional: Clean up chunk immediately to save space
            # chunk_path.unlink()

        merged_data = merge_segments(all_results, chunk_size_s)
        
        output_path = args.output if args.output else video_path.parent / "visual_segments.json"
        output_path.write_text(json.dumps(merged_data, indent=2, ensure_ascii=False), encoding="utf-8")
        
        print(f"\nSuccess! Merged {len(merged_data)} segments into {output_path}")
        
    except Exception as e:
        print(f"Error during processing: {e}")
        return 1
        
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
