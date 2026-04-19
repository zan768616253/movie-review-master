# Product Requirements Document (PRD): movie-review-master

**Product Name:** `movie-review-master`
**Skill & Workflow Objective:** An autonomous AI agent running in Claude Code that ingests a full raw movie file (`.mp4` or `.mkv`) with an external subtitle file, extracts the plot, and autonomously generates a ~10-minute fully produced movie review video (script, voiceover, and video assembly). The agent must support two distinct narrative styles and route the workflow accordingly. The pipeline's final output is a **DaVinci-ready project folder**, not the YouTube master — final polish and export happen in DaVinci Resolve.

---

## 1. Input & Output Specifications

### Input
The user must provide **two files** placed in the same directory:

| File | Format | Notes |
|------|--------|-------|
| Movie file | `.mp4` or `.mkv` | Full-length movie. Both containers are handled identically by `ffmpeg`. |
| Subtitle file | `.srt` (preferred) or `.ass` / `.ssa` | Same directory as the movie by default. If the subtitle filename does not match the movie stem (common with fan-translated subs, e.g., `呪術回戦0.mkv` + `简体.srt`), pass an explicit subtitle path to the CLI. |

**Subtitle file format details:**
- **Preferred:** `.srt` (SubRip Text) — plain text, most universally supported, easiest to parse
- **Accepted fallback:** `.ass` / `.ssa` (Advanced SubStation Alpha)
- Encoding must be **UTF-8** (important for Chinese character support)
- The subtitle language should match the target output language (Chinese subtitles for Chinese output, English for English output)

> If no subtitle file is found alongside the movie, the agent will fall back to audio transcription using OpenAI Whisper (local, free). This fallback is slower and less accurate.

### Output
The agent produces a **DaVinci-ready output folder** next to the input files. The pipeline's `final_video.mp4` is a *draft* — it is watchable end-to-end, but is intentionally **not** the uploadable master. The master is produced by importing this folder into **DaVinci Resolve** (Windows, free edition), fine-tuning, and exporting from there. Every asset is kept as a separate file so DaVinci can swap, re-time, or replace any of them during editing.

```
output/
├── final_video.mp4       # Draft review video (watchable, but not the upload master)
├── voiceover.mp3         # Narration track (MP3) — separate for DaVinci re-timing
├── voiceover.wav         # Narration track (WAV) — higher quality for DaVinci import
├── subtitles.srt         # Narration subtitles — re-importable as a DaVinci subtitle track
├── script.txt            # Full script with [SCENE] markers (Chinese or English)
├── script_clean.txt      # Narration-only (no markers) — source for subtitles.srt
├── script_translated.txt # Translated script (bilingual mode only)
├── thumbnail.jpg         # 1280×720 auto-generated YouTube thumbnail
├── character_map.txt     # Character → archetype mapping (Style A only)
└── clips/
    ├── clip_001.mp4      # Silent video clips at scene timestamps
    ├── clip_002.mp4
    ├── keyframe_001.jpg  # Static keyframes (fallback for coverage gaps)
    └── ...
```

**Draft video specs (what `final_video.mp4` targets):**
- Resolution: **1920×1080** (1080p)
- Frame rate: **30fps**
- Codec: **H.264** (MP4 container)
- Audio: AI-generated voiceover only — **no original movie audio is included**
- Duration: ~10 minutes

> **Post-editing workflow:** open `output/` in DaVinci Resolve on the Windows host (via `\\wsl$\Ubuntu\...`), drop `voiceover.wav` on the timeline, lay `clips/*.mp4` in scene order per `script.txt`, import `subtitles.srt` as a subtitle track, then grade/color and export. The draft `final_video.mp4` is useful for previewing but does not need to be preserved.

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

### Primary Engine: Qwen3-TTS (0.6B-Base)
**Self-hosted, free, GPU-accelerated**

| Spec | Detail |
|------|--------|
| Cost | **$0** (fully local) |
| License | **Apache 2.0** (fully permissive for personal and commercial use) |
| VRAM usage | ~3-5 GB (comfortable on RTX 4060 with ~3-5 GB headroom) |
| Chinese quality | **Best-in-class** — WER 0.92 on Seed-TTS benchmark; Chinese is Qwen3-TTS's strongest language |
| English quality | Excellent — WER 1.32, 10-language multilingual support |
| Voice cloning | **Zero-shot** — needs only **~3 seconds** of reference audio + transcript. No fine-tuning needed |
| Generation speed | ~5x real-time on mid-range GPU (~50 min for a 10-min script). Community `torch.compile` fork claims ~6x speedup |
| Install | `pip install -U qwen-tts` (Python package + model auto-download from HuggingFace) |
| API style | Direct Python API (`from qwen_tts import QwenTTS`); built-in Gradio web UI demo also available |
| Output format | WAV (24 kHz, mono); convert to MP3 via `ffmpeg` |
| Model variants | 0.6B-Base (voice cloning), 1.7B-Base (higher quality, ~5-7 GB VRAM — tight but feasible with FlashAttention 2) |

**Why Qwen3-TTS over Fish Speech:** Fish Speech cannot run on this hardware. Qwen3-TTS has better Chinese benchmarks (WER 0.92 vs Fish Speech's comparable scores), a lower voice cloning reference requirement (3s vs 10-30s), and simpler installation (`pip install`).

**Voice selection strategy:**
- **Style A (Uncle Niu):** Use a built-in Chinese male preset voice (detached, neutral tone). Qwen3-TTS 0.6B-CustomVoice provides 4 Chinese preset voices including male options. Alternatively, clone from the Uncle Niu voice samples in `voice-samples/uncle_niu/`.
- **Style B (First-Person POV):** Use zero-shot voice cloning. The `video_processor.py` script extracts a clean ~3-10 second audio clip of the protagonist's dialogue from the movie. This reference clip + its transcript is passed to Qwen3-TTS at inference time via `create_voice_clone_prompt()`.

**Long-output handling:** Max generation is ~40-50 seconds per call (8192 tokens at 12.5 Hz × 16 codebooks). The `generate_audio.py` script must:
1. Split the script into sentence-level or paragraph-sized chunks (~30-40 seconds each)
2. Use `create_voice_clone_prompt()` once to build a reusable voice prompt from the reference audio
3. Generate each chunk with the cached voice prompt for consistent voice across chunks
4. Concatenate the resulting WAV files using `ffmpeg`
5. Apply audio normalization (consistent volume across chunks, light compression)

### Fallback Engine: edge-tts
If the user's GPU is unavailable or Qwen3-TTS fails:
- **`edge-tts`** (Microsoft Edge Neural TTS): Free, no GPU required, `pip install edge-tts`
- Chinese voices: `zh-CN-XiaoxiaoNeural` (female), `zh-CN-YunxiNeural` (male)
- No voice cloning — uses preset voices only
- Quality: Very good (neural), but no character-matched voice for Style B

> **Default for this project:** Qwen3-TTS 0.6B-Base (local GPU). The `generate_audio.py` script checks which engine is available via a `.env` config and falls back: Qwen3-TTS → edge-tts.

---

## 5. Script Generation (LLM Strategy)

The script is the core creative output. The agent uses **Claude** (via Claude Code itself or the Claude API) to generate the review script from subtitle data.

### Input to the LLM

| Input | Source | Purpose |
|-------|--------|---------|
| Full subtitle text | Parsed by `parse_subtitles.py` | Plot source material — all dialogue with timestamps |
| Style rules | `styles/*.md` file for chosen style | Tone, structure, constraints, archetype table |
| Character mapping | `archetype_mapper.py` output (Style A only) | Original name → archetype name translation table |
| User language choice | User selection at runtime | Chinese (default) or English |

### Generation Workflow

1. **Character extraction:** Parse subtitle text to identify all named characters and their dialogue frequency. For Style A, run archetype mapping and present the mapping table for user review.
2. **Plot analysis:** Feed the full subtitle text to Claude with instructions to identify: main plot arc (beginning, escalation, climax, resolution), key scenes with their subtitle timestamps, and the protagonist.
3. **Script generation:** Feed the plot analysis + style rules to Claude. The output must include:
   - The full narration script (continuous text, ~2,200-2,500 Chinese characters)
   - **Scene timestamp references** per paragraph — e.g., `[SCENE: 00:15:00-00:22:30]` markers indicating which part of the movie each narration segment covers. These markers are stripped from the voiceover text but used by `render_video.py` to select the right video clips.
4. **User review checkpoint:** The agent pauses and presents the generated script for user review. The user can edit the script before TTS generation proceeds. This is the highest-leverage quality control point.

### Context Window Handling

A full movie's subtitles can be 5,000-10,000 lines. Strategies:
- **Primary:** Use Claude's large context window (200K tokens) — most movies fit within a single prompt.
- **Fallback for very long movies:** Summarize the subtitle text in chunks first, then generate the script from the summaries.

---

## 6. Video Quality Features

These features separate "amateur slideshow" from "YouTube-ready review."

### 6.1 Video Clips Over Static Keyframes

Extract **5-15 second silent video clips** at key scene timestamps (from the scene-script alignment in Section 5), not just static JPGs. Movie review channels show motion — this is the single biggest quality differentiator.

- **Primary:** Silent video clips at scene timestamps (no original audio)
- **Fallback:** Static keyframes with Ken Burns effect (subtle pan/zoom) when clips can't be cleanly extracted

### 6.2 Background Music

Add a subtle **royalty-free ambient music track** under the voiceover. Duck music volume during narration, raise slightly during visual-only transitions.

- Source: Pre-selected royalty-free tracks stored in the project (e.g., from pixabay.com/music or incompetech.com)
- Implementation: `ffmpeg` audio mixing — voiceover at full volume, music at -15 to -20 dB

### 6.3 Burned-In Subtitles

Render the narration script as **on-screen subtitles** synchronized to the voiceover. Chinese review channels universally have these — many viewers watch on mobile without audio.

- Render using `ffmpeg` ASS/SRT subtitle burn-in or MoviePy text overlay
- Font: Clean sans-serif (e.g., Source Han Sans / 思源黑体), white with black outline

### 6.4 Visual Transitions

Use **0.3-0.5 second crossfade dissolves** between clips instead of hard cuts. This gives a professional feel at minimal implementation cost.

### 6.5 Audio Post-Processing

After concatenating TTS chunks:
- **Normalize volume** across chunks (prevent jumps between sentences)
- Apply light **compression** for consistent loudness
- Target **-14 LUFS** (YouTube loudness standard)
- Implementation: `ffmpeg` loudnorm filter

### 6.6 Thumbnail Generation (Optional)

Auto-generate a YouTube thumbnail:
- Select the most visually striking keyframe from the movie
- Overlay the video title text (from the `[TITLE]` in the script)
- Output as `output/thumbnail.jpg` (1280×720)

---

## 7. System Architecture ("Progressive Disclosure")

```text
movie-review-master/
├── SKILL.md                 # Mission Control: input collection & workflow routing
├── scripts/
│   ├── parse_subtitles.py   # Parses .srt/.ass into structured Subtitle objects
│   ├── video_processor.py   # Extracts silent video clips, keyframes, + voice reference from .mp4/.mkv
│   ├── archetype_mapper.py  # Style A only: maps character names to archetypes via LLM
│   ├── generate_script.py   # Orchestrates LLM script generation with style rules + scene timestamps
│   ├── generate_audio.py    # TTS: Qwen3-TTS (primary) → edge-tts fallback chain
│   └── render_video.py      # Assembles final video with clips, transitions, subtitles, music
├── styles/
│   ├── niu-shu.md           # Style A: full archetype table + tone rules
│   ├── first-person-pov.md  # Style B: protagonist selection + narrative rules
│   └── xiaodao.md           # Style C: warm emotional narrator + reflective tone rules
├── assets/
│   └── bgm/                 # Royalty-free background music tracks
├── .env.example             # Template: TTS engine selection + optional API keys
└── requirements.txt         # Python dependencies (qwen-tts, moviepy, ffmpeg-python, etc.)
```

### Pipeline Flow

```text
[1] parse_subtitles.py  →  structured subtitle data (with timestamps)
         ↓
[2] generate_script.py  →  review script + scene timestamp markers
    (calls archetype_mapper.py for Style A)
    (user reviews script before continuing)
         ↓
[3] video_processor.py  →  silent video clips at scene timestamps + keyframes + voice ref clip
         ↓
[4] generate_audio.py   →  voiceover WAV (chunked, normalized) + background music mix
         ↓
[5] render_video.py     →  final_video.mp4 + thumbnail + all output assets
```

---

## 8. Success Criteria

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
| 9 | Video shows motion clips, not just static images | Spot-check: scrub through video — most segments should be moving footage |
| 10 | Burned-in subtitles are present and readable | Watch first minute — narration text should appear on screen |
| 11 | Audio has consistent volume with no jarring jumps | Listen through — no sudden loud/quiet transitions between chunks |

---

## 9. Out of Scope (for now)

- Automatic YouTube upload
- AI-generated background music (using pre-selected royalty-free tracks instead)
- Multi-episode or series support
- Automatic YouTube description / tags generation
- Multiple camera angles or picture-in-picture effects
