# Movie Review Master — Project Status & Plan

**Date:** 2026-04-04
**Author:** Eric (with Claude)

---

## What This Project Is

An autonomous AI agent (running in Claude Code) that takes a **movie file + subtitle file** as input and outputs a **~10-minute fully produced movie review video** — complete with script, voiceover (cloned voice), and assembled video.

**Core pipeline:** Movie → Subtitle Parsing → Script Generation (styled) → TTS Voiceover → Video Assembly → Output

---

## Current Project Structure

```
movie-review-master/
├── PROD.md                          # Product requirements document (complete)
├── requirements.txt                 # Python dependencies
├── yt-dlp.exe                       # YouTube downloader (Windows binary)
├── docs/
│   ├── style-design-progress.md     # Session-by-session progress log
│   ├── style-c-xiaodao-research.md  # Xiaodao style research notes
│   └── project-status-and-plan.md   # ← THIS FILE
├── scripts/
│   ├── transcribe.py                # Whisper transcription script (working)
│   └── parse_subtitles.py           # Subtitle parser (empty — not started)
├── styles/
│   └── niu-shu.md                   # Uncle Niu style guide (complete)
├── transcripts/
│   ├── uncle_niu/
│   │   ├── 01_rebel_girl.mp3 + .txt   (7 pairs total — all transcribed)
│   │   ├── ...
│   │   └── 07_retired_soldier.mp3 + .txt
│   └── xiaodao_greenline.mp3        # Xiaodao sample (NOT yet transcribed)
└── voice-samples/
    └── uncle_niu/
        ├── uncle_niu_full.mp3       # Full audio from video 7
        ├── sample_15s.mp3           # 5 x 30-second clips at different timestamps
        ├── sample_120s.mp3
        ├── sample_300s.mp3
        ├── sample_450s.mp3
        └── sample_600s.mp3
```

---

## Dependency Check (2026-04-04)

### Installed & Working

| Package | Version | Purpose | Status |
|---------|---------|---------|--------|
| faster-whisper | 1.2.1 | Audio → text transcription | ✅ Installed, all 7 Uncle Niu files transcribed |
| ffmpeg | 6.1.1 | Audio/video processing (system) | ✅ Installed |
| ffmpeg-python | 0.2.0 | Python wrapper for ffmpeg | ✅ Installed |
| moviepy | 2.2.1 | Video editing/composition | ✅ Installed |
| torch | 2.7.0 | GPU compute for ML models | ✅ Installed |
| openai | 2.26.0 | OpenAI API (if needed) | ✅ Installed |
| NVIDIA GPU | RTX 4060 8GB, CUDA 13.0 | GPU acceleration | ✅ Available |

### NOT Installed (Needed Next)

| Package | Purpose | Priority |
|---------|---------|----------|
| **Fish Speech** | TTS voice cloning (primary TTS engine per PROD.md) | 🔴 HIGH — blocks voiceover |
| **edge-tts** | Fallback TTS (Microsoft, no GPU needed) | 🟡 MEDIUM — fallback option |
| **yt-dlp** (Linux) | YouTube downloads from WSL | 🟢 LOW — only the Windows .exe exists, not usable in WSL |

### Note on "Fish Whisper"
You mentioned installing "fish whisper" — that was likely **faster-whisper** (the transcription engine), which IS installed (v1.2.1) and has already been used to transcribe all 7 Uncle Niu audio files. **Fish Speech** (the TTS/voice-cloning engine) is a separate tool and has NOT been installed yet.

---

## What's Been Done (Summary)

### Session 1 (2026-03-31) — Style A Research & Data Collection
- Downloaded 7 Uncle Niu YouTube videos as MP3 audio
- Researched character archetypes, opening hooks, transition phrases online
- Wrote complete Uncle Niu style guide: `styles/niu-shu.md` (10 sections)
- Cut 5 × 30-second voice samples for future voice cloning
- Created `PROD.md` product requirements document

### Session 2 (2026-04-01) — Whisper Transcription & Style C Research
- Installed faster-whisper, wrote `scripts/transcribe.py`
- Transcribed all 7 Uncle Niu audio files to text (Chinese)
- Identified Style C candidate: Xiaodao (小岛电影) YouTube channel
- Downloaded Xiaodao sample audio (`xiaodao_greenline.mp3`)
- Analyzed 40 Xiaodao video titles, documented style differences
- Wrote research notes: `docs/style-c-xiaodao-research.md`

### Session 3 (2026-04-04) — This Session
- Full project review and dependency audit
- Created this plan document

---

## Detailed Plan — What To Do Next

### Phase 1: Complete Style Research (Style C + B)

**1.1 Transcribe Xiaodao sample audio**
- File: `transcripts/xiaodao_greenline.mp3` (still untranscribed)
- Use the existing `scripts/transcribe.py` approach
- Output: `transcripts/xiaodao_greenline.txt`

**1.2 Write Xiaodao style file**
- Analyze the transcript for patterns (perspective, pacing, transitions, emotional beats)
- Write `styles/xiaodao.md` following same format as `niu-shu.md`

**1.3 Brainstorm & write Style B (First-Person POV)**
- Design protagonist selection logic
- Define emotional tone calibration rules
- Write `styles/first-person-pov.md`

**1.4 Refine Style A (Uncle Niu) with transcript data**
- Compare `niu-shu.md` assumptions against actual transcripts
- Verify pacing (characters per minute), transition frequency, act structure timing

---

### Phase 2: Build the Core Pipeline Scripts

These are the scripts defined in `PROD.md`. Build them one at a time, learning Python along the way.

**2.1 `scripts/parse_subtitles.py`** — Subtitle Parser
- Input: `.srt`, `.ass`, or `.vtt` subtitle file
- Output: structured data (dialogue text + timestamps)
- This is the entry point — everything else depends on having parsed subtitle data

**2.2 `scripts/video_processor.py`** — Video/Subtitle Intake
- Input: movie file (.mp4) + subtitle file
- Extracts subtitle text, identifies scenes, prepares plot summary
- Sends to Claude API for script generation

**2.3 `scripts/archetype_mapper.py`** — Character Name → Archetype
- Maps real character names to Uncle Niu archetypes (小帅, 小美, 丧彪, etc.)
- Only needed for Style A; Style B/C use real names
- Uses the archetype table from `niu-shu.md`

**2.4 `scripts/generate_audio.py`** — TTS Voiceover
- Takes generated script text → produces voiceover .mp3
- Uses Fish Speech (primary) or edge-tts (fallback)
- Requires Fish Speech to be installed first (see Phase 3)

**2.5 `scripts/render_video.py`** — Final Video Assembly
- Combines: movie clips + voiceover audio → final review video
- Uses moviepy for composition
- Output: `output/final_video.mp4` (1080p H.264)

---

### Phase 3: Install & Configure TTS Engines

**TTS Strategy (decided 2026-04-04):**
Fish Speech S2 Pro (current version) requires 24GB VRAM — won't run on our RTX 4060 (8GB).
Plan: start with edge-tts for development, then add Fish Speech v1.5 for voice cloning.

**3.1 Install edge-tts (development TTS)**
- `pip install edge-tts` — zero GPU, uses Microsoft's cloud voices
- Chinese male voice: `zh-CN-YunxiNeural`
- Good enough to get pipeline working end-to-end
- No voice cloning — generic preset voice only

**3.2 Install Fish Speech v1.5 (voice cloning TTS)**
- Old version (~500M params, ~2-4GB VRAM) — runs on RTX 4060
- Supports zero-shot voice cloning from 10-30s reference audio
- Quality decent but not as good as S2 Pro
- Use for cloning Uncle Niu's voice from our voice samples

**3.3 Select best voice sample**
- Listen to the 5 voice samples in `voice-samples/uncle_niu/`
- Pick the cleanest one (clear speech, no background music)

**3.4 Test voice cloning**
- Feed selected sample + test script to Fish Speech v1.5
- Verify quality of cloned Uncle Niu voice

**3.5 Future: Monitor s2.cpp (GGUF quantized S2 Pro)**
- Community project providing quantized S2 Pro models
- q6_k (~4.5GB) might fit on 8GB VRAM
- Currently alpha — revisit when it matures

---

### Phase 4: Integration & End-to-End Testing

**4.1 Wire all scripts together**
- Create main entry point / orchestrator script
- Movie + subtitles → all the way to final video

**4.2 Test with a real movie**
- Pick a test movie with subtitles
- Run full pipeline end-to-end
- Check against PROD.md success criteria (8 checkpoints)

**4.3 Iterate on quality**
- Review generated script quality
- Check voiceover naturalness
- Verify video assembly timing

---

## Recommended Next Steps (This Session)

1. **Transcribe the Xiaodao audio** — quick win, same process as Uncle Niu
2. **Start writing `parse_subtitles.py`** — the first real pipeline script, good Python practice
3. **Research Fish Speech installation** — understand requirements before installing

---

## Success Criteria (from PROD.md)

1. ✅ `output/final_video.mp4` exists and plays
2. ✅ Duration: 8-12 minutes
3. ✅ Language matches style (Chinese for Uncle Niu)
4. ✅ Style rules applied (archetypes, hooks, transitions)
5. ✅ No original movie audio leaks through
6. ✅ All intermediate assets present (script, voiceover, clips)
7. ✅ Video: 1080p H.264, AAC audio
8. ✅ Full plot captured (no missing key events)
