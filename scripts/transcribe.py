from pathlib import Path
from faster_whisper import WhisperModel 

p = Path("transcripts/uncle_niu")
mp3_files = sorted(p.glob("*.mp3"))

model_size = "large-v3"
model = WhisperModel(model_size, device="cuda", compute_type="float16")

for mp3_file in mp3_files:
    try:
        segments, info = model.transcribe(mp3_file, beam_size=5, language="zh", condition_on_previous_text=False)
        transcript_file = mp3_file.with_suffix(".txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            for segment in segments:
                f.write(f"{segment.text}\n")
                
    except Exception as e:
        print(f"Error processing {mp3_file}: {e}")


