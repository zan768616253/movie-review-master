# Product Requirements Document (PRD): movie-review-master

**Product Name:** `movie-review-master`
**Skill & Workflow Objective:** An autonomous AI agent running in Claude Code that ingests a full raw movie file (`.mp4`) with an external subtitle file, extracts the plot, and autonomously generates a ~10-minute fully produced movie review video (script, voiceover, and video assembly). The agent must support two distinct narrative styles and route the workflow accordingly.

---

## 1. Input & Output Specifications

### Input
The user must provide **two files** placed in the same directory:

| File | Format | Notes |
|------|--------|-------|
| Movie file | `.mp4` | Full-length movie |
| Subtitle file | `.srt` (preferred) or `.ass` / `.vtt` | Must be in the **same directory** as the `.mp4`, with the **same filename** (e.g., `movie.mp4` + `movie.srt`) |

**Subtitle file format details:**
- **Preferred:** `.srt` (SubRip Text) — plain text, most universally supported, easiest to parse
- **Accepted fallback:** `.ass` / `.ssa` (Advanced SubStation Alpha) or `.vtt` (WebVTT)
- Encoding must be **UTF-8** (important for Chinese character support)
- The subtitle language should match the target output language (Chinese subtitles for Chinese output, English for English output)

> If no subtitle file is found alongside the `.mp4`, the agent will fall back to audio transcription using OpenAI Whisper (local, free). This fallback is slower and less accurate.

### Output
The agent produces an **output folder** next to the input files containing all assets needed for YouTube upload and optional post-editing:

```
output/
├── final_video.mp4       # Assembled ~10-minute review video (ready for YouTube)
├── voiceover.mp3         # Standalone voiceover audio track (for post-editing)
├── script.txt            # Full generated script (Chinese or English)
├── script_translated.txt # Translated version (if bilingual mode used)
└── clips/
    ├── keyframe_001.jpg  # Extracted keyframes used in the video
    ├── keyframe_002.jpg
    └── ...               # Extracted short clips (silent, no original audio)
```

**Output video specs:**
- Resolution: **1920×1080** (1080p, YouTube standard)
- Frame rate: **30fps**
- Codec: **H.264** (MP4 container, universally compatible)
- Audio: AI-generated voiceover only — **no original movie audio is included**
- Duration: ~10 minutes

> Post-editing: All source assets (audio + clips/frames) are kept in the `output/` folder. These can be imported into any free video editor (e.g., **DaVinci Resolve**) for fine-tuning before upload.

---

## 2. Language Support

| Language | Priority | Notes |
|----------|----------|-------|
| Chinese (Mandarin, zh-CN) | **Primary** | Script generated in Chinese by default |
| English | Secondary | Can be triggered by user selection at runtime |

A **bilingual mode** is supported: the agent can generate both a Chinese and an English script, producing two separate voiceover files. The user selects which language to use for the final video assembly, keeping the other as a reference.

---

## 3. Supported Styles (The Style Library)

The agent pauses after plot extraction and asks the user which style to apply before generating the script.

### Style A: Uncle Niu (牛叔说电影)
- **Perspective:** Third-person omniscient
- **Tone:** Deadpan, fast-paced, highly sarcastic
- **Language:** Chinese (default), English (optional)
- **Key Constraints:**
  - Opens with the "注意看" (Notice / Pay attention) hook
  - Original character names are forbidden — characters are mapped to archetypes (e.g., Xiao Shuai for male lead, Da Zhuang for muscle, Da Mo Wang for villain). Full archetype table defined in `styles/niu-shu.md`
- **Voiceover:** Standard, detached, male "movie reviewer" TTS voice

### Style B: First-Person Protagonist POV
- **Perspective:** First-person ("I") — narrated by the **protagonist** (the character with the most plot agency and screen time)
- **Tone:** Emotional, immersive, subjective — personal memoir or confession
- **Language:** Chinese (default), English (optional)
- **Key Constraints:**
  - Original character names must be used
  - Narrative reveals only what the protagonist would know at each point in the story — twist details are withheld until the appropriate moment
  - Focuses on internal struggles, fears, and growth
- **Voiceover:** Character-matched TTS voice (gender and tone matched to the protagonist using voice style selection — see Section 4)

---

## 4. TTS Engine Selection

No original movie audio is used. All voiceover is AI-generated.

**Hardware:** User has an **NVIDIA RTX 4060 (8GB VRAM)** — sufficient for local GPU-accelerated TTS with voice cloning.

### Primary Engine: Fish Speech v1.5+
**Self-hosted, free, GPU-accelerated**

| Spec | Detail |
|------|--------|
| Cost | **$0** (fully local) |
| License | **Apache 2.0** (code + model weights, fully permissive for personal and commercial use) |
| VRAM usage | ~2-4 GB (leaves ~4 GB headroom on RTX 4060) |
| Chinese quality | Excellent — natively trained on large-scale Chinese data; natural prosody, accurate tones |
| English quality | Excellent — multilingual training |
| Voice cloning | **Zero-shot** — pass 10-30 seconds of clean reference audio at inference time. No fine-tuning needed |
| Generation speed | ~1 second of compute produces 10-15 seconds of audio on RTX 4060 |
| Install | `pip install fish-speech` (Python package + model auto-download) |
| API style | OpenAI-compatible HTTP API server, or direct Python API |
| Output format | WAV (native); convert to MP3 via `ffmpeg` |

**Voice selection strategy:**
- **Style A (Uncle Niu):** Use a built-in male Chinese voice (detached, neutral tone). Select from Fish Speech's pre-trained Chinese male voices.
- **Style B (First-Person POV):** Use zero-shot voice cloning. The `video_processor.py` script will extract a clean 10-30 second audio clip of the protagonist's dialogue from the movie. This reference clip is passed to Fish Speech at inference time to clone the protagonist's voice for the narration.

**Long-output handling:** Fish Speech quality can degrade on utterances longer than ~60 seconds. The `generate_audio.py` script must split the script into paragraph-sized chunks (30-50 seconds each), generate each chunk separately, and concatenate the resulting WAV files using `ffmpeg`.

### Fallback Engine: CosyVoice 2
**Self-hosted, free, GPU-accelerated**

Used as a fallback if Fish Speech cannot produce satisfactory results for a specific voice or if shorter reference clips are available:

| Spec | Detail |
|------|--------|
| Cost | **$0** (fully local) |
| License | Apache 2.0 (code); model weights under Tongyi Qianwen license (permits commercial use, review model card for specifics) |
| VRAM usage | ~4-6 GB (tighter on RTX 4060 but functional) |
| Chinese quality | Excellent — natively trained by Alibaba Tongyi Speech Lab |
| Voice cloning | **Zero-shot** — needs only **3-10 seconds** of reference audio (lower requirement than Fish Speech) |
| Install | Clone from GitHub (`FunAudioLLM/CosyVoice`), PyTorch-based |

> **When to use CosyVoice 2 over Fish Speech:** When the protagonist has limited clean dialogue (less than 10 seconds available), CosyVoice 2's lower reference audio requirement (3-10s) makes it the better choice for voice cloning.

### Emergency Fallback: edge-tts
If the user's GPU is unavailable or both local engines fail:
- **`edge-tts`** (Microsoft Edge Neural TTS): Free, no GPU required, `pip install edge-tts`
- Chinese voices: `zh-CN-XiaoxiaoNeural` (female), `zh-CN-YunxiNeural` (male)
- No voice cloning — uses preset voices only
- Quality: Very good (neural), but no character-matched voice for Style B

> **Default for this project:** Fish Speech (local GPU). The `generate_audio.py` script checks which engine is available via a `.env` config and falls back: Fish Speech → CosyVoice 2 → edge-tts.

---

## 5. System Architecture ("Progressive Disclosure")

```text
movie-review-master/
├── SKILL.md                 # Mission Control: input collection & workflow routing
├── scripts/
│   ├── video_processor.py   # Parses subtitle file; extracts keyframes/clips + voice reference from .mp4
│   ├── archetype_mapper.py  # Style A only: maps character names to archetypes
│   ├── generate_audio.py    # TTS: Fish Speech (primary) → CosyVoice 2 → edge-tts fallback chain
│   └── render_video.py      # Assembles final video; writes output/ folder
├── styles/
│   ├── niu-shu.md           # Style A: full archetype table + tone rules
│   └── first-person-pov.md  # Style B: protagonist selection + narrative rules
├── .env.example             # Template: engine selection + optional API keys
└── requirements.txt         # Python dependencies (fish-speech, moviepy, ffmpeg-python, etc.)
```

---

## 6. Success Criteria

A successful run is defined as meeting **all** of the following:

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1 | Output MP4 exists and is playable | Open `output/final_video.mp4` in any video player |
| 2 | Duration is between 8 and 12 minutes | Check video length |
| 3 | Voiceover is in the correct language (Chinese or English) | Listen to first 30 seconds |
| 4 | Style constraints are correctly applied | For Style A: "注意看" hook present, no original names. For Style B: first-person narration, protagonist name used |
| 5 | No original movie audio is present | Mute test: audio stops completely when voiceover track is muted |
| 6 | All post-editing assets are present | `output/voiceover.mp3`, `output/clips/` folder, `output/script.txt` all exist |
| 7 | Video is 1080p H.264 | Check via `ffprobe output/final_video.mp4` |
| 8 | Script captures the full plot arc | Beginning, middle, climax, and ending are all represented |

---

## 7. Out of Scope (for now)

- Archetype table for Style A (defined later in `styles/niu-shu.md`)
- Automatic YouTube upload
- Background music generation
- On-screen text/subtitle overlay on the output video
- Multi-episode or series support
