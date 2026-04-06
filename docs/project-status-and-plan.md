# Movie Review Master — Project Status & Plan

**Date:** 2026-04-06
**Author:** Eric (review updated with GitHub Copilot)

---

## What This Project Is

An autonomous AI agent that takes a **movie file + subtitle file** as input and produces a **~10-minute movie review video** with:

- generated script
- AI voiceover
- assembled review video

**Target pipeline:** Movie + subtitles -> subtitle parsing -> plot/script generation -> TTS voiceover -> video assembly -> output assets

The product goal in `PROD.md` is still correct. What changed in this update is the **implementation status** and the **recommended build order** based on the actual repository state.

---

## Current Status At A Glance

**Overall stage:** Early implementation / foundation work

**What already exists:**
- Style A (`styles/niu-shu.md`) is written.
- 7 Uncle Niu MP3 files and transcripts exist in `transcripts/uncle_niu/`.
- Xiaodao research is documented and the sample audio is downloaded.
- `scripts/parse_subtitles.py` exists as an initial ASS parser.
- `scripts/transcribe.py` exists as a working batch transcription script.

**What does not exist yet:**
- No end-to-end pipeline.
- No reusable CLI for subtitle parsing or transcription.
- No `video_processor.py`, `archetype_mapper.py`, `generate_audio.py`, or `render_video.py`.
- No Style B file and no Style C file yet.

**Most important planning conclusion:**
The next best step is **not** to start the subtitle parser from scratch. That work has already started. The best next step is to **finish the subtitle intake layer properly** so the rest of the pipeline has a stable foundation.

---

## Verified Repository State (2026-04-06)

### Code That Exists Today

**`scripts/parse_subtitles.py`**
- Has a `Subtitle` dataclass.
- Parses ASS timestamps into seconds.
- Removes ASS inline style tags.
- Parses ASS `Dialogue:` lines into structured subtitle objects.
- Can export parsed ASS subtitles to a `.txt` file.
- Current limitation: it is **ASS-only**, has **no `main()`**, and is not yet a general subtitle ingestion tool.

**`scripts/transcribe.py`**
- Has already been used to generate the 7 Uncle Niu transcript `.txt` files.
- Current limitation: it is a **hardcoded batch script**, not a reusable tool.
- The script loads the Whisper model at module import time, which makes it unsuitable as a clean package entry point.
- It also has **no `main()`**, even though `pyproject.toml` declares a `transcribe` console script.

### Tests

- `tests/test_parse_subtitles.py` currently passes with:
  `conda run -n py312_machine_learning --no-capture-output pytest tests/test_parse_subtitles.py -q`
- Result during this review: **4 parser tests passed**.
- Current limitation: tests only cover the initial ASS path and do not yet cover `.srt`, `.vtt`, CLI behavior, or malformed-input handling.

### Assets On Disk

**Transcripts**
- `transcripts/uncle_niu/` contains 7 MP3 + TXT pairs.
- `transcripts/xiaodao_greenline.mp3` exists.
- `transcripts/xiaodao_greenline.txt` does **not** exist yet.

**Voice samples**
- `voice-samples/uncle_niu/` contains `uncle_niu_full.mp3` plus 5 clipped samples.

**Style files**
- Present: `styles/niu-shu.md`
- Missing: `styles/xiaodao.md`, `styles/first-person-pov.md`

### Runtime / Environment Snapshot

Verified during this review:

| Item | Status | Notes |
|------|--------|-------|
| `faster_whisper` | ✅ importable | transcription dependency available |
| `ffmpeg-python` / `ffmpeg` module | ✅ importable | Python wrapper available |
| `moviepy` | ✅ importable | video composition dependency available |
| `edge_tts` | ✅ importable | fallback TTS already available |
| `yt_dlp` | ✅ importable | Linux-side package available |
| `torch` | ✅ importable | present in environment |
| `openai` | ✅ importable | present in environment |
| `fish_speech` | ❌ not importable | still not installed |
| system `ffmpeg` | ✅ verified | version `6.1.1` |
| NVIDIA GPU | ✅ verified | `RTX 4060 Laptop GPU`, `8188 MiB` |

### Packaging / Repo Mismatches

These are small but important:

- `pyproject.toml` declares console scripts for `parse-subtitles` and `transcribe`, but the current Python files do not expose `main()` functions yet.
- `pyproject.toml` points `readme` to `README.md`, but there is currently no `README.md` in the repository root.
- Dependencies are declared in both `pyproject.toml` and `requirements.txt`; by repo rule, `pyproject.toml` should be treated as the source of truth for dependency changes.

---

## What Has Been Completed So Far

### Workstream A — Style Research

**Completed**
- Wrote `styles/niu-shu.md` for Style A (Uncle Niu).
- Downloaded and transcribed 7 Uncle Niu review audios.
- Researched Xiaodao and documented the findings in `docs/style-c-xiaodao-research.md`.
- Downloaded `transcripts/xiaodao_greenline.mp3` as the first Style C sample.

**Still open**
- Transcribe Xiaodao sample audio.
- Write `styles/xiaodao.md`.
- Design and write `styles/first-person-pov.md`.
- Revisit `styles/niu-shu.md` using transcript-based pacing evidence.

### Workstream B — Core Pipeline Foundations

**Completed**
- Initial subtitle parsing prototype for ASS files.
- Initial transcription prototype for a fixed batch folder.
- Parser unit tests for the sample ASS fixture.

**Still open**
- Support `.srt` and `.vtt` subtitle formats.
- Create clean CLI entry points.
- Define a stable parsed-subtitle output contract for downstream steps.
- Implement video processing, script generation handoff, TTS generation, and rendering.

### Workstream C — TTS / Voice

**Completed**
- `edge-tts` is already available in the environment.
- Uncle Niu voice sample assets exist.

**Still open**
- Install and validate Fish Speech.
- Choose the best Uncle Niu voice sample.
- Build `generate_audio.py`.
- Decide how to switch between generic TTS and cloned-voice TTS in the pipeline.

---

## Recommended Build Order

This is the recommended order from this point forward.

### 1. Finish subtitle intake first

Reason:
- Subtitle parsing is the real entry point for the entire product.
- It is already partially built, so this is the highest-leverage next step.
- A reliable parser gives you reusable structured input for script generation, style application, and scene selection.

### 2. Refactor transcription into a real tool

Reason:
- You already proved the transcription path works.
- Turning it into a reusable CLI lets you transcribe Xiaodao immediately and reuse the same workflow for future samples or subtitle fallback.

### 3. Complete the style library

Reason:
- Style quality matters, but style work is not the current technical blocker.
- Once the parser/transcriber are stable, style documents become easier to ground in real transcript evidence.

### 4. Delay Fish Speech integration until text intake is stable

Reason:
- `edge-tts` is already available, so you can reach a first end-to-end prototype without voice cloning.
- Fish Speech is still valuable, but it is no longer the next critical blocker.

---

## Detailed Next-Step Plan

### Phase 1 — Subtitle Intake v1 (Recommended Next Milestone)

**Goal:** turn `scripts/parse_subtitles.py` from a prototype into a reusable project entry point.

### 1.1 Add a clean library + CLI boundary

- Keep parsing functions importable without side effects.
- Add a `main()` function so the `parse-subtitles` console script in `pyproject.toml` becomes real.
- Accept:
  - input subtitle path
  - optional output path
  - output format (`txt`, `json`, possibly `stdout`)

### 1.2 Expand format support

- Keep the current ASS parser.
- Add `.srt` parsing.
- Add `.vtt` parsing.
- Normalize all formats into the same `Subtitle` structure.

### 1.3 Normalize subtitle text consistently

- Strip ASS tags.
- Convert escaped line breaks like `\N` into a consistent text form.
- Collapse extra whitespace.
- Skip empty lines or unsupported dialogue records.

### 1.4 Improve test coverage

- Keep the current ASS fixture tests.
- Add one `.srt` fixture.
- Add one `.vtt` fixture.
- Add tests for multiline subtitles.
- Add tests for malformed or partial input.
- Add a CLI smoke test once `main()` exists.

### 1.5 Define the output contract for downstream scripts

Minimum recommended structure per subtitle item:

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

That gives future scripts enough information to:
- summarize plot beats
- reconstruct timing windows
- map characters
- select scenes for clips

### Exit Criteria For Phase 1

- `parse-subtitles <subtitle_file>` works from the CLI.
- `.ass`, `.srt`, and `.vtt` all parse into the same structure.
- Tests cover the three formats.
- Parsed output is good enough to feed a later `video_processor.py`.

---

### Phase 2 — Transcription Tool v1

**Goal:** convert `scripts/transcribe.py` from a one-off script into a reusable fallback tool.

### 2.1 Refactor script structure

- Move model loading inside `main()` or a dedicated function.
- Avoid doing work at import time.
- Add file/folder arguments instead of hardcoded paths.

### 2.2 Add reusable options

- input file or folder
- language
- model size
- device / compute type
- output directory

### 2.3 Use it immediately on the Xiaodao sample

- Input: `transcripts/xiaodao_greenline.mp3`
- Output target: `transcripts/xiaodao_greenline.txt`

### Exit Criteria For Phase 2

- `transcribe` works as a real CLI.
- Module import no longer triggers transcription.
- Xiaodao transcript exists and can be reviewed.

---

### Phase 3 — Complete The Style Library

### 3.1 Write `styles/xiaodao.md`

- Base it on the actual transcript, not just title research.
- Capture:
  - hook pattern
  - emotional pacing
  - narrator/viewer relationship
  - closing style

### 3.2 Write `styles/first-person-pov.md`

- Define protagonist selection logic.
- Define knowledge-boundary rules.
- Define emotional intensity rules.
- Define when this style is a bad fit.

### 3.3 Refine `styles/niu-shu.md`

- Use the 7 transcripts to check actual pacing.
- Confirm whether the 10-minute structure in the style file matches the real narration pattern.

### Exit Criteria For Phase 3

- All three style files exist.
- Each style has clear constraints and a usable prompt contract.
- Style-selection logic is ready for later orchestration.

---

### Phase 4 — Pipeline Skeleton

After the three phases above, build the next layer:

- `video_processor.py`
- `archetype_mapper.py`
- `generate_audio.py`
- `render_video.py`
- a simple orchestrator script

At that point, the project can target its first end-to-end prototype with `edge-tts` before Fish Speech voice cloning is added.

---

## Concrete Recommendation For The Very Next Session

If you want the highest-value next move, do this exact sequence:

1. Finish `scripts/parse_subtitles.py` into a real CLI.
2. Add `.srt` and `.vtt` support plus tests.
3. Refactor `scripts/transcribe.py` so it no longer runs work at import time.
4. Transcribe `transcripts/xiaodao_greenline.mp3`.
5. Write `styles/xiaodao.md`.

That order gives you one technical milestone and one content milestone without jumping too early into video assembly or voice cloning.

---

## Tracking Checklist

### Foundation
- [x] Define product target in `PROD.md`
- [x] Build initial Whisper transcription workflow
- [x] Create initial ASS subtitle parser
- [ ] Turn subtitle parser into reusable CLI
- [ ] Support `.srt` and `.vtt`
- [ ] Define parsed-subtitle JSON contract

### Style System
- [x] Write `styles/niu-shu.md`
- [ ] Write `styles/xiaodao.md`
- [ ] Write `styles/first-person-pov.md`
- [ ] Refine Uncle Niu pacing from transcript evidence

### Voice / Audio
- [x] Prepare Uncle Niu reference clips
- [x] Verify `edge-tts` is available
- [ ] Install Fish Speech
- [ ] Build `generate_audio.py`
- [ ] Compare generic TTS vs cloned voice quality

### Video Pipeline
- [ ] Build `video_processor.py`
- [ ] Build `archetype_mapper.py`
- [ ] Build `render_video.py`
- [ ] Create orchestrator / first end-to-end run
- [ ] Validate against `PROD.md` success criteria

---

## Short Status Summary

The project is in a better place than the older plan suggested: subtitle parsing has started, parser tests pass, and `edge-tts` / `yt-dlp` are already available. The biggest gap is not missing dependencies anymore; it is the lack of **clean, reusable interfaces** between the prototype scripts and the planned pipeline.

That makes the next move clear: finish subtitle intake first, then refactor transcription, then complete the style library, then assemble the pipeline.