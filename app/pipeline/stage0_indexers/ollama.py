import json
import base64
import requests
import subprocess
from pathlib import Path
from typing import List, Dict

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    TfidfVectorizer = None
    cosine_similarity = None

from .base import VisualIndexerStrategy, seconds_to_timestamp

DEFAULT_OLLAMA_MODEL = "qwen3-vl:4b"
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"

class OllamaStrategy(VisualIndexerStrategy):
    def __init__(self, model_name: str = DEFAULT_OLLAMA_MODEL):
        self.model_name = model_name

    def _extract_frames(self, video_path: Path, tmp_dir: Path) -> List[Path]:
        frames_dir = tmp_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        
        # 1 frame every 3 seconds, downscale to 512px wide to reduce payload
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", "fps=1/3,scale=512:-2",
            "-q:v", "5",
            str(frames_dir / "frame_%05d.jpg")
        ]
        subprocess.run(cmd, check=True)
        
        frames = sorted(list(frames_dir.glob("frame_*.jpg")))
        return frames

    def _analyze_frame(self, frame_path: Path, characters: List[str]) -> Dict:
        with open(frame_path, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode("utf-8")
            
        char_str = ", ".join(characters) if characters else "Identify main characters."
        
        prompt = (
            "Analyze the image and return a JSON object. "
            "Follow this JSON schema: "
            '{"summary": "description of the action", '
            '"ocr_text": "any on screen text, or empty string if none", '
            '"is_action": true, '
            '"confidence": 0.99, '
            '"characters": ["list of characters identified"]} '
            f"Main characters to look for: {char_str} "
            "Respond ONLY with the raw JSON object."
        )
        
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64_image],
                }
            ],
            "stream": False,
            "format": "json",
        }
        
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        response.raise_for_status()
        
        raw_text = response.json().get("message", {}).get("content", "")
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = {}

        # Normalize: the model may use alternate key names
        return {
            "summary": parsed.get("summary") or parsed.get("description") or raw_text.strip() or "",
            "ocr_text": parsed.get("ocr_text") or parsed.get("text") or "",
            "is_action": parsed.get("is_action", False),
            "confidence": parsed.get("confidence", 0.5),
            "characters": parsed.get("characters", []),
        }

    def _compute_similarity(self, text1: str, text2: str) -> float:
        if not text1 or not text2:
            return 0.0
        if TfidfVectorizer is None:
            # Fallback simple overlap if sklearn missing
            w1 = set(text1.lower().split())
            w2 = set(text2.lower().split())
            if not w1 or not w2:
                return 0.0
            return len(w1.intersection(w2)) / float(max(len(w1), len(w2)))
            
        vectorizer = TfidfVectorizer()
        try:
            tfidf = vectorizer.fit_transform([text1, text2])
            return cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
        except ValueError:
            return 0.0

    def index_video(self, video_path: Path, characters: List[str], chunk_minutes: int, tmp_dir: Path) -> List[Dict]:
        print(f"Ollama Option B running. Extracting 3s frames from {video_path.name}...")
        frames = self._extract_frames(video_path, tmp_dir)
        
        if not frames:
            return []
            
        raw_segments = []
        for i, frame in enumerate(frames):
            print(f"Analyzing frame {i+1}/{len(frames)}...")
            frame_data = self._analyze_frame(frame, characters)
            
            # Map index back to 3-second increment time
            start_s = i * 3.0
            end_s = (i + 1) * 3.0
            
            frame_data["start"] = seconds_to_timestamp(start_s)
            frame_data["end"] = seconds_to_timestamp(end_s)
            raw_segments.append(frame_data)
            
        # Collapse rule
        collapsed_segments = []
        if not raw_segments:
            return collapsed_segments
            
        current_seg = raw_segments[0]
        
        for next_seg in raw_segments[1:]:
            sim = self._compute_similarity(current_seg["summary"], next_seg["summary"])
            chars_match = set(current_seg["characters"]) == set(next_seg["characters"])
            
            if sim > 0.85 and chars_match:
                # Merge
                current_seg["end"] = next_seg["end"]
            else:
                collapsed_segments.append(current_seg)
                current_seg = next_seg
                
        collapsed_segments.append(current_seg)
        return collapsed_segments
