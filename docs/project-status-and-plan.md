# Movie Review Master — Project Status & Plan

**Date:** 2026-04-18
**Author:** Eric (review updated with Claude Code)

---

## What This Project Is

An autonomous AI agent that takes a **movie file + subtitle file** as input and produces a **~10-minute movie review video** with:

- generated script
- AI voiceover
- assembled review video

**Target pipeline:** Movie + subtitles → subtitle parsing → plot/script generation → TTS voiceover → video assembly → output assets

**Output handoff model (updated 2026-04-18):** The pipeline produces a *draft* `final_video.mp4` plus all underlying assets (voiceover, clips, keyframes, script, subtitles) into an `output/` folder. The folder is intentionally shaped so that it can be **imported into DaVinci Resolve** for manual fine-tuning and export before YouTube upload. The pipeline is not trying to produce the uploadable master on its own — it is trying to produce a re-editable project.

---

## Current Status At A Glance

**Overall stage:** Phase 1 almost complete. About to test end-to-end on a real movie.

**What already exists (updated 2026-04-18):**
- Style A (`styles/niu-shu.md`) is written.
- 7 Uncle Niu MP3 files and transcripts in `transcripts/uncle_niu/`.
- Xiaodao research documented; sample audio downloaded (not transcribed yet).
- `scripts/parse_subtitles.py` has been **refactored into a class-based design** with `SubtitleParser` ABC, `AssSubtitleParser`, and `SrtSubtitleParser`, plus a format registry.
- Both **`.ass` and `.srt`** are parsed into the same `Subtitle` structure.
- `scripts/transcribe.py` exists as a working batch transcription script.
- Tests cover both `.ass` and `.srt` fixtures.
- Real test movie is on disk: `movies/呪術回戦0/` with `呪術回戦0.mkv` (14.3 GB) and `简体.srt` (Simplified Chinese subtitles, 98 KB).

**What does not exist yet:**
- No `main()` / CLI entry for `parse_subtitles.py` — so the `parse-subtitles` console script declared in `pyproject.toml` is still not callable.
- No structured (JSON) output contract — only `.txt` export.
- `scripts/transcribe.py` is still a hardcoded batch script with work at import time.
- No end-to-end pipeline.
- No `video_processor.py`, `archetype_mapper.py`, `generate_script.py`, `generate_audio.py`, or `render_video.py`.
- No Style B or Style C files yet.

**Scope changes decided 2026-04-18:**
- **Drop `.vtt` support.** Eric has no `.vtt` files and does not expect any. Phase 1 scope is now `.ass` + `.srt` only.
- **Accept `.mkv` as a valid video input** (in addition to `.mp4`). MKV is a container; `ffmpeg` handles it natively. `PROD.md` Section 1 should be widened accordingly.
- **Output is DaVinci-ready, not "final."** The final polish/export step is done manually in DaVinci Resolve.

**Most important planning conclusion:**
Finish the subtitle intake layer (CLI + structured output), then run the real Jujutsu Kaisen 0 subtitle file through it as the first real-world test. That is the highest-value next move because it validates the foundation everything else depends on.

---

## Environment & Workflow (new section, 2026-04-18)

The project runs on a Windows host with WSL2 (Ubuntu). Work is split across the two sides.

### Runs inside WSL (Linux)

- All Python code in this repo (parser, transcriber, script generator, renderer)
- `faster-whisper` transcription, Qwen3-TTS, `edge-tts`
- `ffmpeg` and `moviepy` for video assembly
- PyTorch / CUDA on the RTX 4060 (WSL2 forwards the GPU cleanly)
- Claude Code itself

**Reason:** this is the natural environment for the ML + media pipeline. Fewer packaging surprises, reproducible CLI.

### Runs in Windows (native)

- **DaVinci Resolve (free, Windows version)** for manual editing and final export.
- **Why native Windows, not Linux DaVinci:** the free Linux build of DaVinci Resolve does not support H.264 / H.265 decode or encode (codec licensing). Your MKV file is almost certainly H.264 or H.265, so free Linux DaVinci would refuse to import it. The free **Windows** build supports those codecs out of the box.
- DaVinci opens the WSL `output/` folder through `\\wsl$\Ubuntu\...` in Windows Explorer or through a mapped path.

### File placement rule

Keep the MKV (and its generated assets) **inside the WSL native filesystem**, e.g. `/home/ericw/Project/.../movies/<title>/movie.mkv`. Do **not** process large video files that live under `/mnt/c/...` — cross-filesystem I/O is slow enough to noticeably hurt ffmpeg throughput.

DaVinci reading from `\\wsl$\...` at editing time is fine because it is done once at project import, not during pipeline execution.

### Other editors considered

Mentioned only so the choice is explicit:

| Tool | Notes |
|------|-------|
| **DaVinci Resolve (Windows, free)** | **Chosen.** Best UX, free tier supports H.264/H.265, large community. |
| Shotcut / Kdenlive (Linux) | Work in WSLg but UX is rougher and GPU acceleration is limited. |
| CapCut (Windows) | Fast for short-form content, less control for long review videos. |
| `ffmpeg` / `moviepy` only | What `render_video.py` does — this is what produces the DaVinci-ready draft, not the final. |

---

## Verified Repository State (2026-04-18)

### Code That Exists Today

**`scripts/parse_subtitles.py` (refactored)**
- `Subtitle` dataclass (`start`, `end`, `text`, `speaker`, `style`).
- `SubtitleParser` ABC with `parse()`.
- `AssSubtitleParser` — parses ASS `Dialogue:` events, strips inline tags.
- `SrtSubtitleParser` — parses SRT blocks, handles BOM, normalizes timing with `-->`.
- `SUBTITLE_PARSER_REGISTRY` maps file extensions to parser classes.
- Convenience function: `parse_subtitles()`.
- `main()` handles output routing for file output and `--stdout`.
- **Still missing:** JSON output, format detection from content (not just extension).

**`scripts/transcribe.py`**
- Same as previous status — already used to generate the 7 Uncle Niu transcripts.
- Still has no `main()`, still loads the Whisper model at import time.

### Tests

- `tests/test_parse_subtitles.py` covers both `.ass` and `.srt` paths.
- Fixtures: `tests/fixtures/sample_movie.ass`, `tests/fixtures/sample_movie.srt`.
- Test command (per repo rule):
  `conda run -n py312_machine_learning --no-capture-output pytest tests/test_parse_subtitles.py -q`
- Still missing: CLI smoke test (no CLI yet), malformed-input cases.

### Assets On Disk

**Real test movie (new)**
- `movies/呪術回戦0/呪術回戦0.mkv` — 14.3 GB, Blu-ray quality MKV.
- `movies/呪術回戦0/呪術回戦0.srt` — 98 KB Simplified Chinese SRT.
- **Note:** the subtitle filename does not match the movie filename. `PROD.md` Section 1 currently requires them to share a stem. Either rename the SRT to `呪術回戦0.srt`, or relax the "same name" rule in `PROD.md` and have the CLI accept an explicit subtitle path.

**Transcripts**
- `transcripts/uncle_niu/` — 7 MP3 + TXT pairs.
- `transcripts/xiaodao_greenline.mp3` exists; `.txt` does not yet.

**Voice samples**
- `voice-samples/uncle_niu/` — `uncle_niu_full.mp3` plus 5 clipped samples.

**Style files**
- Present: `styles/niu-shu.md`
- Missing: `styles/xiaodao.md`, `styles/first-person-pov.md`

### Runtime / Environment Snapshot

| Item | Status | Notes |
|------|--------|-------|
| `faster_whisper` | ✅ | transcription dependency |
| `ffmpeg-python` | ✅ | Python wrapper |
| `moviepy` | ✅ | video composition |
| `edge_tts` | ✅ | fallback TTS |
| `yt_dlp` | ✅ | WSL-side |
| `torch` | ✅ | present |
| `openai` | ✅ | present |
| `fish_speech` | ❌ dropped | replaced by Qwen3-TTS (2026-04-07 decision) |
| `qwen_tts` | ❌ not installed | install with `pip install -U qwen-tts` |
| system `ffmpeg` | ✅ | version `6.1.1` |
| NVIDIA GPU | ✅ | `RTX 4060 Laptop GPU`, 8188 MiB |
| DaVinci Resolve (Windows) | ⚠️ user-side | install from blackmagicdesign.com (free tier is enough) |

### Packaging / Repo Mismatches

- `pyproject.toml` declares a `parse-subtitles` console script, but the file has no `main()`. Same for `transcribe`.
- `pyproject.toml` points `readme` to `README.md`, which does not exist.
- Dependencies duplicated in `pyproject.toml` and `requirements.txt`; treat `pyproject.toml` as source of truth.

---

## What Has Been Completed So Far

### Workstream A — Style Research

**Completed**
- Wrote `styles/niu-shu.md` for Style A (Uncle Niu).
- Downloaded and transcribed 7 Uncle Niu review audios.
- Researched Xiaodao and documented findings in `docs/style-c-xiaodao-research.md`.
- Downloaded `transcripts/xiaodao_greenline.mp3`.

**Still open**
- Transcribe Xiaodao sample audio.
- Write `styles/xiaodao.md`.
- Design and write `styles/first-person-pov.md`.
- Revisit `styles/niu-shu.md` using transcript-based pacing evidence.

### Workstream B — Core Pipeline Foundations

**Completed**
- Initial subtitle parsing prototype for ASS.
- **Class-based refactor with `SubtitleParser` ABC + format registry.**
- **`.srt` parser implemented (2026-04-18).**
- Initial transcription prototype for a fixed batch folder.
- Parser unit tests cover both ASS and SRT fixtures.

**Still open**
- Expose `main()` / CLI entry points (subtitles + transcriber).
- Define a stable structured output (JSON) contract for downstream steps.
- Accept `.mkv` alongside `.mp4` as input video format.
- Implement `video_processor.py`, `generate_script.py`, `generate_audio.py`, `render_video.py`.

**Explicitly out of scope (as of 2026-04-18):** `.vtt` subtitle support.

### Workstream C — TTS / Voice

**Completed**
- `edge-tts` available in the environment.
- Uncle Niu voice samples ready.
- TTS engine decision: Qwen3-TTS 0.6B-Base (2026-04-07).

**Still open**
- Install and validate Qwen3-TTS.
- Choose the best Uncle Niu voice sample for cloning reference.
- Build `generate_audio.py` with chunked generation + normalization.
- Decide engine-switching logic.

### Workstream D — LLM Script Generation

**Not started** — documented in `PROD.md` Section 5.

**Still open**
- Build `generate_script.py`.
- Implement scene-script alignment (`[SCENE: HH:MM:SS-HH:MM:SS]` markers per paragraph).
- Implement user review checkpoint.
- Test against a full-length subtitle file.

---

## Recommended Build Order

1. **Finish subtitle intake** — add `main()` / CLI to `parse_subtitles.py`, define the structured output, then run it on the real Jujutsu Kaisen 0 SRT. This is the highest-leverage next move because everything else consumes its output.
2. **Refactor transcription into a real CLI tool** — remove import-time work, add file/folder args. Use it to transcribe `xiaodao_greenline.mp3` as the first real use.
3. **Complete the style library** — write `styles/xiaodao.md` (grounded in the new transcript) and `styles/first-person-pov.md`.
4. **Build script generation (LLM layer)** — `generate_script.py`, `archetype_mapper.py`, scene-script alignment, user review checkpoint. First version can run on Claude via the Claude Code session itself before touching the API.
5. **Build video + audio pipeline** — `video_processor.py` (clips + keyframes from `.mp4` and `.mkv`), `generate_audio.py` (edge-tts first, then Qwen3-TTS), `render_video.py`. Output must be DaVinci-importable.
6. **Integrate Qwen3-TTS voice cloning** — install and validate, add engine switching.

---

## Detailed Next-Step Plan

### Phase 1 — Subtitle Intake v1 (Active — ~70% done)

**Goal:** turn `scripts/parse_subtitles.py` into a reusable project entry point and validate it on the real Jujutsu Kaisen 0 subtitle file.

#### 1.1 Add a clean library + CLI boundary *(open)*

- Keep parsing functions importable without side effects.
- Add a `main()` function so the `parse-subtitles` console script in `pyproject.toml` becomes real.
- Accept:
  - input subtitle path (required)
  - optional output path
  - output format (`txt`, `json`, `stdout`)

#### 1.2 Expand format support *(done — within new scope)*

- `.ass` parser: ✅
- `.srt` parser: ✅ (added 2026-04-18)
- **`.vtt` parser: dropped from scope.** If a `.vtt` file ever appears, reopen this item.
- Normalize both formats into the same `Subtitle` structure — already true via `SubtitleParser` ABC.

#### 1.3 Normalize subtitle text consistently *(partial)*

- Strip ASS tags: ✅
- Convert escaped line breaks like `\N` into consistent text: ✅ in CLI output rendering, but not yet inside `Subtitle.text` during parsing.
- Collapse extra whitespace: TODO.
- Skip empty lines or unsupported dialogue records: partial — check that SRT empty-text blocks are dropped.

#### 1.4 Improve test coverage *(partial)*

- ASS fixture tests: ✅
- SRT fixture tests: ✅ (added 2026-04-18)
- Multiline subtitles: TODO (confirm current coverage).
- Malformed input / missing timing line: TODO.
- CLI smoke test: blocked on 1.1.

#### 1.5 Define the structured output contract *(open)*

Minimum recommended JSON per subtitle item:

```json
{
  "start": 12.34,
  "end": 15.67,
  "text": "subtitle text",
  "speaker": null,
  "style": null,
  "source_format": "ass"
}
```

This feeds future scripts: plot beats, timing windows, character mapping, scene selection.

#### 1.6 Real-world validation on Jujutsu Kaisen 0 *(new)*

- Run the CLI on `movies/呪術回戦0/呪術回戦0.srt`.
- Inspect the parsed output: total cue count, first/last timestamps, any rows that look broken.
- Decide whether `PROD.md` Section 1 needs relaxing on the "subtitle filename must match movie filename" rule (currently violated by `简体.srt` vs `呪術回戦0.mkv`).

### Exit Criteria For Phase 1

- `parse-subtitles <subtitle_file>` runs from the CLI.
- `.ass` and `.srt` both parse into the same structure.
- Tests cover both formats, including one malformed case.
- JSON output option exists and matches the agreed contract.
- The real Jujutsu Kaisen 0 SRT parses cleanly end-to-end.

---

### Phase 2 — Transcription Tool v1

**Goal:** turn `scripts/transcribe.py` into a reusable fallback tool.

#### 2.1 Refactor script structure

- Move model loading inside `main()` or a dedicated function.
- No work at import time.
- Accept file/folder arguments.

#### 2.2 Add reusable options

- input file or folder
- language
- model size
- device / compute type
- output directory

#### 2.3 Use it immediately on the Xiaodao sample

- Input: `transcripts/xiaodao_greenline.mp3`
- Output: `transcripts/xiaodao_greenline.txt`

### Exit Criteria For Phase 2

- `transcribe` works as a real CLI.
- No transcription fires on module import.
- Xiaodao transcript exists for review.

---

### Phase 3 — Complete The Style Library

#### 3.1 Write `styles/xiaodao.md`

- Base on the actual transcript, not just title research.
- Capture: hook pattern, emotional pacing, narrator/viewer relationship, closing style.

#### 3.2 Write `styles/first-person-pov.md`

- Protagonist selection logic.
- Knowledge-boundary rules (what the protagonist could or couldn't know at each beat).
- Emotional intensity rules.
- When this style is a bad fit.

#### 3.3 Refine `styles/niu-shu.md`

- Use the 7 real transcripts to validate pacing claims.
- Confirm the 10-minute structure matches real narration.

### Exit Criteria For Phase 3

- All three style files exist.
- Each style has clear constraints and a usable prompt contract.
- Style-selection logic is ready for orchestration.

---

### Phase 4 — Script Generation (LLM Layer)

**Goal:** Generate a review script from subtitle data using Claude.

#### 4.1 Build `generate_script.py`

- Accept parsed subtitle data (from Phase 1 JSON output).
- Load the chosen style file.
- For Style A: call `archetype_mapper.py` first, present mapping for user review.
- Feed subtitle text + style rules to Claude.
- Output must include `[SCENE: HH:MM:SS-HH:MM:SS]` markers per paragraph.
- Present script to user for review/editing before TTS.

#### 4.2 Build `archetype_mapper.py`

- Extract character names + dialogue frequency from parsed subtitles.
- Map to archetypes from `styles/niu-shu.md`.
- Output a mapping table for user confirmation.

### Exit Criteria For Phase 4

- Given a subtitle file + style choice, produce a reviewable script.
- Script includes scene timestamp markers.
- User can edit the script before proceeding.

---

### Phase 5 — Video & Audio Pipeline (DaVinci-ready output)

Build the production layer. The explicit goal is a folder that opens cleanly in DaVinci Resolve.

- `video_processor.py` — extract silent video clips at scene timestamps, plus keyframes, plus a voice reference clip. **Must accept `.mp4` and `.mkv`** (ffmpeg handles both identically).
- `generate_audio.py` — Qwen3-TTS (primary) → edge-tts fallback; chunked generation + normalization + optional background music mix.
- `render_video.py` — assemble a draft final video: clips, crossfade transitions, Ken Burns on stills, burned-in subtitles, thumbnail generation.

**DaVinci handoff shape** — the `output/` folder should contain:

```
output/
├── final_video.mp4        # Draft — watchable but not the master
├── voiceover.mp3          # Separate so DaVinci can re-time it
├── voiceover.wav          # Optional higher-quality variant
├── script.txt             # Full script with [SCENE] markers
├── script_clean.txt       # Narration-only (good source for subtitle import)
├── subtitles.srt          # Re-importable into DaVinci as a subtitle track
├── thumbnail.jpg          # 1280x720
├── character_map.txt      # Style A only
└── clips/
    ├── clip_001.mp4       # Silent clips at scene timestamps
    ├── clip_002.mp4
    ├── keyframe_001.jpg
    └── ...
```

Each asset is a separate file on disk so DaVinci can rearrange or replace any of them during manual editing.

Target a first end-to-end prototype using `edge-tts` before adding Qwen3-TTS voice cloning.

---

### Phase 6 — Qwen3-TTS Voice Cloning

After the full pipeline works with edge-tts:

- Install Qwen3-TTS (`pip install -U qwen-tts`).
- Validate voice cloning using Uncle Niu samples.
- Add engine switching in `generate_audio.py`.
- Compare Qwen3-TTS cloned voice vs edge-tts preset voice.

---

## Concrete Recommendation For The Very Next Session

Now that a real movie is on disk and Phase 1 is ~70% done, the best next sequence is:

1. **Add `main()` + a CLI to `parse_subtitles.py`** (argparse, input path, optional output path, `--format txt|json`).
2. **Add JSON output** matching the contract in 1.5.
3. **Run the CLI on `movies/呪術回戦0/呪術回戦0.srt`** and sanity-check the parsed result.
4. **Decide what to do about mismatched subtitle filenames** — update `PROD.md` Section 1 if the "same stem" rule should be relaxed.
5. **Refactor `transcribe.py`** so import-time work goes away, then transcribe `xiaodao_greenline.mp3`.
6. **Write `styles/xiaodao.md`** grounded in that transcript.
7. **Start `generate_script.py`** — even a bare-bones version that feeds subtitles + style rules to Claude and returns a draft script is extremely valuable; it proves the core product loop.

That order gets you to a testable end-to-end slice fastest, while each step is small enough to be a learning exercise.

---

## Tracking Checklist

### Foundation
- [x] Define product target in `PROD.md`
- [x] Build initial Whisper transcription workflow
- [x] Create initial ASS subtitle parser
- [x] Class-based refactor with format registry
- [x] `.srt` subtitle parser
- [ ] Widen `PROD.md` Section 1 to accept `.mkv` and clarify DaVinci-ready output
- [ ] Turn subtitle parser into a real CLI (`main()` + argparse)
- [ ] Structured (JSON) output option
- [ ] Real-world test on Jujutsu Kaisen 0 SRT
- [x] ~~Support `.vtt`~~ (dropped 2026-04-18 — out of scope)

### Style System
- [x] Write `styles/niu-shu.md`
- [ ] Write `styles/xiaodao.md`
- [ ] Write `styles/first-person-pov.md`
- [ ] Refine Uncle Niu pacing from transcript evidence

### Script Generation (LLM Layer)
- [ ] Build `generate_script.py` (Claude-based)
- [ ] Build `archetype_mapper.py`
- [ ] Implement scene-script alignment markers
- [ ] Implement user review checkpoint

### Voice / Audio
- [x] Prepare Uncle Niu reference clips
- [x] Verify `edge-tts` is available
- [x] TTS engine decision: Qwen3-TTS replaces Fish Speech
- [ ] Install and validate Qwen3-TTS
- [ ] Build `generate_audio.py` (chunked generation + normalization)
- [ ] Add background music mixing
- [ ] Compare Qwen3-TTS cloned voice vs edge-tts preset voice

### Video Pipeline
- [ ] Build `video_processor.py` (silent clips + keyframes + voice ref) — must accept `.mp4` and `.mkv`
- [ ] Build `render_video.py` (assembly + transitions + subtitle burn-in)
- [ ] Add Ken Burns effect for static keyframes
- [ ] Add crossfade transitions between clips
- [ ] Add thumbnail generation
- [ ] Produce DaVinci-importable `output/` folder shape
- [ ] Create orchestrator / first end-to-end run
- [ ] Validate against `PROD.md` success criteria

### Environment
- [x] Decide WSL (pipeline) + Windows DaVinci Resolve (manual edit) split
- [ ] Install DaVinci Resolve on Windows host and verify it imports an `output/` folder from `\\wsl$\...`
- [ ] Keep large media files inside WSL native filesystem (not `/mnt/c`)

---

## Short Status Summary

**Updated 2026-04-18:**

1. **Subtitle intake refactored.** `parse_subtitles.py` is now a class-based design with a format registry. Both `.ass` and `.srt` are supported.
2. **Scope narrowed.** `.vtt` is explicitly out of scope.
3. **Input scope widened.** `.mkv` is now a valid video input alongside `.mp4`.
4. **Output philosophy clarified.** The pipeline produces a DaVinci-ready `output/` folder, not the YouTube master. Final polish/export happens in DaVinci Resolve on Windows.
5. **First real test case is ready.** `movies/呪術回戦0/` has a 14 GB MKV and a Chinese SRT — the target of the next end-to-end test.
6. **Environment decision recorded.** Pipeline runs in WSL; manual editing runs in Windows DaVinci Resolve free edition (codec support). MKV stays inside WSL native FS.

Phase 1 is on the verge of completion. The single biggest remaining item is giving `parse_subtitles.py` a real CLI + structured output, then running it against the real subtitle file.
