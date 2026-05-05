# Movie-Review-Master Handbook

> **NOTE (2026-05-04):** The audio-driven `[ANCHOR]` pipeline was retired in
> May 2026 after structural audio/video sync problems proved to be a
> consequence of the architecture rather than implementation bugs. The
> project is now mid-rebuild as a **video-driven** pipeline. See
> [`plan.md`](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/plan.md)
> for current implementation status; sections below describe the new
> target architecture.

This handbook is the central source of truth for stable project knowledge: concepts, design decisions, pipeline logic, conventions, and style-system rules. It is intentionally not a progress log.

## 1. Documentation Map

Use each document for one job only:

- [PROD.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/PROD.md): product scope, success criteria, boundaries
- [docs/HANDBOOK.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/HANDBOOK.md): durable knowledge and system design
- [plan.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/plan.md): current status, priorities, next work
- [docs/TECHNICAL.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/TECHNICAL.md): code-facing architecture, contracts, pipeline, tools, tests
- `styles/*.md`: style-specific writing rulebooks
- [docs/style-c-xiaodao-research.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/style-c-xiaodao-research.md): supporting research for the unfinished Style C
- [docs/agent-rules/python-environment.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/agent-rules/python-environment.md): Python execution rule

## 2. System Goal

The project turns a full movie plus subtitles into a draft long-form review package. The package is designed for fast human finishing, not for fully autonomous final publishing.

The handoff model is deliberate:

- automation produces a draft render and all reusable assets
- DaVinci Resolve is used for final polish, retiming, and export
- source assets stay separate so edits remain flexible

## 3. Operating Model

The system is split across two environments:

- WSL2 Ubuntu runs Python, TTS, transcription, `ffmpeg`, and the build pipeline
- Windows runs DaVinci Resolve for manual finishing and export

Project assumptions:

- GPU: RTX 4060 class hardware
- primary language: Chinese
- primary plot source: subtitle text
- primary media tool: `ffmpeg`

## 4. Architectural Principle: Video Drives Audio

The single rule that defines the pipeline shape:

> **Visuals are picked first. Narration is written against the chosen visuals. Audio is generated from that narration. Then the visuals are trimmed to fit the actual audio.**

The earlier audio-driven pipeline (the `[ANCHOR]` system) tried to bind narration timing to fixed source-movie ranges *before* the audio existed. This created a structural conflict: TTS duration is variable (one sentence is 2.8s or 4.5s depending on emphasis, pacing, punctuation), but source-shot duration is fixed. Forcing those two together produces audible mismatches no amount of micro-tuning could resolve.

The video-driven model avoids that mismatch by reversing the dependency. Each "beat" of the review is a fixed visual sequence whose internal timing is shaped *after* the narration audio is rendered.

## 5. Core Concepts

### Source Movie

The full `.mp4` or `.mkv` file that all clips are extracted from.

### Subtitle Source

The `.srt` or `.ass` file used as plot context for narration writing.

### Shot

A single continuous take detected by the VLM + ffmpeg scene-detect pass. The atomic unit of visual selection.

### Selected Shots

The chronological subset of shots that should appear in the review. Selection is the human (or scorer) judgment about which moments matter for the plot.

### Narrative Beat

A 30–60s segment of the rough cut that contains 5–15 micro-shots and corresponds to one narration line. The beat is the unit of narration writing AND the unit of visual fitting: micro-shots inside one beat are trimmed/looped together to match the beat's TTS duration.

### Voiceover Manifest

The manifest is the sync contract between audio generation and the rest of the pipeline. It records, per beat:

- `index`
- `text` (the narration spoken in this beat)
- `audio_start_s` and `audio_end_s` (where the beat lives in the concatenated voiceover)

Field names are preserved from the legacy manifest where possible to ease migration.

### Subtitle Manifest

The subtitle manifest is the sync contract between subtitle alignment and the renderer. It records, in order:

- `index`, `chunk_index`, `text`, `start_s`, `end_s`

`chunk_index` here refers to the beat index from the voiceover manifest.

### Draft Render

`review.mp4` is the watchable draft. `final_video.mp4` is the upload-ready master created by remuxing the draft picture lock with the voiceover track.

## 6. End-to-End Pipeline Design

The pipeline has 10 stages. Stages 0–1 and 7–9 reuse existing modules; stages 2–6 are the new video-driven core.

| # | Stage | Auto/Manual | Status |
|---|---|---|---|
| 0 | Visual Indexing (shot detection) | Auto | Survives from old pipeline |
| 1 | Subtitle Intake | Auto | Survives from old pipeline |
| 2 | Shot Selection | Manual v1 → Auto v2 | New |
| 3 | Rough Cut Assembly | Auto | New |
| 4 | Narration Writing | Manual v1 → Auto v2 | New |
| 5 | Voiceover Generation | Auto | New (TTS engine reused via git history) |
| 6 | Visual Fitting | Auto | New |
| 7 | Subtitle Alignment | Auto | Survives (was old Stage 4) |
| 8 | Draft Render | Auto | New |
| 9 | Upload Finalize | Auto | Survives (was old Stage 7) |

Each manual stage is a **replaceable module**: its output is a stable JSON file with a versioned schema, so the manual editor can be swapped for an automated scorer/writer without changing any downstream code. The first iteration is "human in the loop" and the second iteration replaces those humans with code, one at a time.

### Stage 0: Visual Indexing

Purpose:

- detect every shot in the source movie and emit a per-shot summary
- the foundation that all selection, scoring, and assembly stages build on

Carried over from the previous architecture without changes. Output: `visual_segments.json`.

The Stage 0 launcher now requires a `synopsis.md` cast reference and a non-empty `characters/` face-gallery directory next to the movie file; it fails fast if either is missing.

### Stage 1: Subtitle Intake

Purpose:

- normalize `.srt`/`.ass` into clean text + timing
- provide plot context to the narration-writing stage

Carried over without changes.

### Stage 2: Shot Selection

Purpose:

- cut the shot list down to the high-information subset
- preserve chronological order

Output: `selected_shots.json` — a list of references back to entries in `visual_segments.json`, plus optional per-shot tags ("hook", "twist", "climax").

v1 (manual): the user opens the JSON in an editor and marks `keep`/`skip`. A simple TUI helper is acceptable but not required.

v2 (auto): a scoring function combines heuristics (face presence, motion, OCR change, scene novelty) and optional VLM judgment. It runs after v1 has produced enough labeled examples to validate the scorer.

The contract — input/output schema — does not change between v1 and v2.

### Stage 3: Rough Cut Assembly

Purpose:

- concatenate the selected shots in chronological order
- group adjacent shots into 30–60s narrative beats
- emit a per-beat manifest

Output: `rough_cut.mp4` plus `rough_cut.json`. Each beat in the manifest carries:

- `beat_index`, `shot_ids` (the micro-shots in this beat), `start_s`/`end_s` in the rough cut, `total_duration_s`.

Auto. Pure ffmpeg concat plus a deterministic beat grouper.

### Stage 4: Narration Writing

Purpose:

- write one narration line per beat, in the chosen review style
- ground each line in the visual content of the beat plus the surrounding subtitle context

Output: `narration.json` — a list of `{ beat_index, text }` objects.

v1 (manual): an LLM prompt is generated containing the beat's micro-shot summaries, surrounding subtitle context, the synopsis, and the style rulebook. The user pastes the prompt into Gemini 3 Pro / Qwen 3.6, pastes the reply back, and a validator checks per-beat character counts.

v2 (auto): direct LLM call from the harness, same prompt structure.

### Stage 5: Voiceover Generation

Purpose:

- TTS each narration line
- concatenate into a single voiceover file
- emit the voiceover manifest with real measured `audio_start_s`/`audio_end_s`

Auto. Uses Qwen3-TTS Voice Clone on the chosen style's reference audio. The TTS engine code is recovered from git history when this stage is implemented.

### Stage 6: Visual Fitting

Purpose:

- shape the rough cut to match the actual audio durations
- per beat: trim, loop, or extend the micro-shots so the beat's video length equals its `audio_end_s − audio_start_s`

Auto. Deterministic strategy:

1. Compute target duration for each beat from the voiceover manifest.
2. Compare to the rough-cut beat duration.
3. If TTS is shorter than the beat → trim from the tails of the least-important micro-shots.
4. If TTS is longer than the beat → loop the most-static micro-shot or hold on the most-recent micro-shot to fill.
5. Output per-beat fitted clips (not yet concatenated) so the renderer can recombine cleanly.

Output: `fitted/beat_NNN.mp4`.

### Stage 7: Subtitle Alignment

Purpose:

- split each beat's narration into shorter subtitle cues
- align cue boundaries to real pauses detected in the voiceover

Carried over from the legacy `stage4_align_subtitles.py`. Output: `subtitle_manifest.json`.

### Stage 8: Draft Render

Purpose:

- concatenate fitted beat clips in order
- burn subtitles from the subtitle manifest
- mux the voiceover track
- emit `review.mp4`

Auto. ffmpeg concat + libass burn-in + audio mux.

### Stage 9: Upload Finalize

Purpose:

- preserve the Stage 8 picture lock
- remux with the voiceover
- emit `final_video.mp4` with `+faststart`

Carried over from the legacy `stage7_finalize_video.py`.

## 7. Auto vs Manual + Recommended Tools

This table is the operator-facing reference. Every entry is intentionally tool-agnostic at the contract level — the per-stage JSON schemas are stable across tool changes.

| # | Stage | Auto/Manual (v1) | Recommended Tool | Notes |
|---|---|---|---|---|
| 0 | Visual Indexing | Auto | **Gemini 3 Flash** via `google-generativeai` | Local Qwen2.5-VL is a fallback on the RTX 4060; slower. |
| 1 | Subtitle Intake | Auto | Built-in Python parser | No external tool. |
| 2 | Shot Selection | **Manual** | VSCode editing `selected_shots.json`, with the source movie open in **DaVinci Resolve / VLC / mpv** for reference | Auto v2 will be a heuristic scorer + optional local VL ranker. |
| 3 | Rough Cut Assembly | Auto | `ffmpeg` concat | No external tool. |
| 4 | Narration Writing | **Manual** | **Gemini 3 Pro** in browser (highest quality) or **Qwen 3.6** locally; paste prompt → paste reply | Validator catches char-count violations. Auto v2 will direct-call the same model via API. |
| 5 | Voiceover Generation | Auto | **Qwen3-TTS Voice Clone** on Base model (`Qwen/Qwen3-TTS-12Hz-1.7B-Base`) | Style A reference voice lives at `styles/voice-assets/niu-shu/reference/clone_reference.{mp3,txt}`. |
| 6 | Visual Fitting | Auto | `ffmpeg` trim + loop | No external tool. |
| 7 | Subtitle Alignment | Auto | `ffmpeg` `silencedetect` filter | No external tool. |
| 8 | Draft Render | Auto | `ffmpeg` concat + libass | NVENC preferred (`h264_nvenc`), `libx264` fallback. |
| 9 | Upload Finalize | Auto | `ffmpeg` remux | `+faststart` for direct upload. |
| Post | Manual Polish | **Manual** | **DaVinci Resolve** (Windows) | Optional. The output folder is structured so DaVinci can import each fitted beat as a separate clip and the user can swap micro-shots, color grade, or add BGM. |

Tool decisions to revisit later:

- Stage 2 v2 scorer: build manually-scored data first; do not over-invest before there's ground truth.
- Stage 4 v2 direct-call: only after manual prompt + reply has stabilized into a fixed template across multiple movies.
- Stage 6 fallback strategies (slow-motion, B-roll cutaway): only add if simple trim/loop produces visible problems.

## 8. Style System

The project is built around style-specific narration rulebooks.

### Style A: Uncle Niu

- detached third-person narrator
- deadpan sarcasm
- archetype nicknames instead of original names
- best for high-energy or high-plot-density reviews

Source of truth: [styles/niu-shu.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/styles/niu-shu.md)

### Style B: First-Person Protagonist POV

- protagonist-led confession
- emotional, intimate, subjective narration
- original names are preserved

Source of truth: [styles/first-person-pov.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/styles/first-person-pov.md)

### Style C: Xiaodao

- warm narrator voice
- reflective, emotional, meaning-driven framing
- intended for classics, dramas, and high-emotion stories

Current research reference: [docs/style-c-xiaodao-research.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/style-c-xiaodao-research.md)

## 9. Technology Decisions

These are the cross-project decisions that should stay consistent unless deliberately replaced.

### Subtitle Parsing

- treat subtitle text as plot context, not as a sync source
- support `.srt` and `.ass`
- preserve timing as numeric seconds for tooling

### TTS

- local TTS is preferred
- Qwen3-TTS Voice Clone on the Base model is the standard for Style A
- narration is generated beat-by-beat, then concatenated into one voiceover file plus one manifest
- long-form output is loudness-normalized before render assembly
- fallback hosted/preset TTS is acceptable only when the main local path is unavailable

### TTS Voice Characteristics for Style A

Useful distilled knowledge from the validation work:

- target pace is fast, roughly around 6 Chinese characters per second
- delivery should feel dry, deadpan, storyteller-like, not theatrical
- short pauses work better than long dramatic ones
- the winning implementation favored timbre recognizability over description-driven synthesis

### TTS Reference-Audio Caveats

- some older Uncle Niu sample files are mislabeled by nominal duration; filenames alone are not a reliable measurement source
- background music in source samples can distort pitch and pause analysis
- a good fresh voice-clone reference should stay relatively short and clean; the current target is a 90-second single-speaker dialogue reference for ICL
- prefer prepared transcript-conditioned references over runtime adaptation of long clips

### Video Processing

- `ffmpeg` is the baseline media engine
- extracted review clips are silent
- micro-shots are re-encoded rather than stream-copied so trim boundaries stay frame-stable
- GPU encoding (`h264_nvenc`) is the default on the RTX 4060 target; `libx264 -preset fast` is the fallback so CI and non-GPU hosts still work

### Render Synchronization

- the voiceover manifest is the authoritative timing source for every downstream stage
- visual fitting always shapes video to audio, never the reverse
- subtitle cues come from `silencedetect` on the real voiceover, not from character counts alone

## 10. Asset Model and Naming Conventions

Per-movie working directory:

```text
movies/<title>/
  <title>.mkv or <title>.mp4
  <subtitle>.srt or <subtitle>.ass
  synopsis.md                              # optional plot/cast context
  selected_shots.json
  narration.json
  voiceover_<style>_voiceclone.mp3
  voiceover_<style>_voiceclone.manifest.json
  output/
    rough_cut/
    fitted/
    keyframes/
    review.mp4
    final_video.mp4
```

Shared voice assets live under the `styles/` tree:

```text
styles/
  niu-shu.md
  first-person-pov.md
  voice-assets/
    niu-shu/
      analysis/
      reference/
    first-person-pov/
      analysis/
    xiao-dao/
      analysis/
```

Naming rules:

- style-tagged files allow side-by-side experiments
- manifest filename tracks the voiceover filename
- output assets stay grouped under the movie directory, not in a global build folder
- `analysis/` holds audio + transcript pairs used for style study
- `reference/` holds the canonical clone source for a style

## 11. Environment Rules

Python execution and dependency management are standardized:

- use the `py312_machine_learning` conda environment
- follow [docs/agent-rules/python-environment.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/agent-rules/python-environment.md) as the canonical command rule
- treat `pyproject.toml` as the dependency source of truth

## 12. Design Principles

These principles explain many of the specific choices above.

### Visual-First Assembly

Visuals drive the timeline. Audio is rendered against fixed visual beats, and visual durations are then adjusted to match real audio. This avoids the structural sync problems of audio-first assembly.

### Replaceable Modules

Every manual stage is designed so its output schema is stable and identical to the schema the future automated version will produce. This lets manual and automated steps coexist and lets the project automate one step at a time without rewriting downstream code.

### Deterministic Contracts

Marker-driven JSON contracts are preferred over fuzzy matching. The manifests (selected_shots, rough_cut, voiceover, subtitle) are the load-bearing surfaces; everything else is implementation.

### Draft First, Polish Later

The pipeline first produces something coherent, inspectable, and re-editable. Production polish (transitions, BGM ducking, advanced motion graphics) is layered on once the deterministic path is stable.

### Keep Stable Knowledge Separate From Session Logs

Implementation status changes often. Core concepts and design rules should not.
