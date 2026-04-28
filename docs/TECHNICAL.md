# Technical Documentation

> **NOTE (2026-04-27):** The Stage 2 / Stage 3 / Stage 4 / Stage 5 contracts
> below describe the **current** code on `develop`. An architectural
> overhaul is in flight — see [`OVERHAUL_PLAN.md`](OVERHAUL_PLAN.md) for
> target schemas and the phased migration plan.

This document is the code-facing reference for repository structure, entry points, contracts, and current implementation boundaries. It complements the handbook instead of duplicating it.

## 1. Source-of-Truth Split

- product scope: [PROD.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/PROD.md)
- stable design knowledge: [docs/HANDBOOK.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/HANDBOOK.md)
- current status and next tasks: [plan.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/plan.md)
- implementation details: this file

## 2. Repository Map

```text
movie-review-master/
  README.md
  PROD.md
  plan.md
  pyproject.toml
  docs/
    HANDBOOK.md
    TECHNICAL.md
    agent-rules/
  app/
    __init__.py
    pipeline/
      __init__.py
      stage0_index_visuals.py
      stage0_indexers/
        __init__.py
        base.py
        gemini.py
        ollama.py (removed)
      stage1_parse_subtitles.py
      stage2_generate_script.py
      stage3_generate_audio.py
      stage4_video_processor.py
      stage5_render_video.py
      common/
        __init__.py
        script_contract.py
        video_encoder.py
    tools/
      __init__.py
      transcribe_audio.py
      voice_analysis.py
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
  tests/
    pipeline/
      test_stage1_parse_subtitles.py
      test_stage3_generate_audio.py
    tools/
      test_transcribe_audio.py
```

## 3. Environment and Execution Rules

Canonical Python command rule:

- every Python command must be prefixed with `conda run -n py312_machine_learning --no-capture-output`
- dependency updates go through `pyproject.toml`, then `pip install -e .`

Reference: [docs/agent-rules/python-environment.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/agent-rules/python-environment.md)

## 4. Current Script Inventory

Pipeline modules are prefixed with `stageN_` to make pipeline order obvious at a glance. Utility modules that support the pipeline but are not stages live under `app/tools/`.

### `app/pipeline/stage1_parse_subtitles.py`

Purpose:

- parse `.srt` and `.ass` subtitles
- normalize text
- write normalized plain-text or JSON files

Current state:

- implemented
- exposes `parse-subtitles` entry point
- covered by automated tests

Key public pieces:

- `Subtitle` dataclass
- `parse_subtitles()`
- `main()`

### `app/pipeline/stage2_generate_script.py`

Purpose:

- build the writer-pass prompt that produces beat-level narration without timestamps
- build the grounding-pass prompt that aligns those beats to SRT and `visual_segments.json`

Current state:

- implemented as a manual two-pass prompt assembler
- exposes `generate-script` entry point that prints either prompt to stdout
- supports `writer` and `grounder` subcommands; movie title is inferred from the subtitle filename when omitted, and writer genre defaults to `general`
- Stage 2 is still run manually today; the repo owns the prompt contract, while the actual model execution remains outside the codebase

Key public pieces:

- `build_writer_prompt()`
- `build_grounding_prompt()`
- `main()`

### `app/pipeline/stage3_generate_audio.py`

Purpose:

- parse a marked script into narration chunks
- run TTS
- concatenate audio
- emit a manifest that maps chunks to time ranges in the final audio

Current state:

- implemented for the current Stage 2 -> Stage 3 pipeline path
- exposes `generate-audio` entry point
- accepts the same `--style` input used in Stage 2 to derive both the default output tag and the default reference path under `styles/voice-assets/<style>/reference/`
- always uses transcript-conditioned ICL voice cloning from `reference/clone_reference.{mp3,txt}`
- still accepts `--ref-audio` / `--ref-text` overrides for styles that do not have a canonical reference pair yet

Important contract:

- output is `voiceover_<tag>_voiceclone.mp3`
- manifest is `voiceover_<tag>_voiceclone.manifest.json`

### `app/pipeline/stage4_video_processor.py`

Purpose:

- parse `[SCENE]` and `[BROLL]` markers from a script
- extract silent source clips and keyframes with `ffmpeg`

Current state:

- implemented
- exposes `video-processor` entry point

Key CLI flags:

- `--handle-seconds` (default 1.5) — pre/post handle applied around every hero clip.
- `--max-extension-seconds` (default 30.0) — upper bound on safe-boundary extension triggered by `visual_segments.json`. Required because a single hallucinated visual segment can otherwise turn one clip into a full-movie re-encode.
- `--encoder {auto,nvenc,libx264}` (default `auto`) — `auto` picks `h264_nvenc` when available, otherwise falls back to `libx264 -preset fast`.

### `app/pipeline/stage5_render_video.py`

Purpose:

- read the voiceover manifest
- render per-chunk video segments
- concatenate segments
- mux the narration track into `review.mp4`

Current state:

- implemented stage 1 baseline
- exposes `render-video` entry point

Current stage-1 characteristics:

- hard cuts
- no subtitle burn
- no background music
- B-roll rotation supported through pre-extracted clip inputs

Key CLI flags:

- `--encoder {auto,nvenc,libx264}` (default `auto`) — same selector used by Stage 4. Used for hero slices, manual B-roll re-encodes, semantic B-roll re-encodes, and still-frame segments.

### `app/pipeline/stage6_finalize_video.py`

Purpose:

- take the Stage 5 draft render as the locked picture source
- take the Stage 3 voiceover as the authoritative narration source
- emit `final_video.mp4` with `+faststart` for direct upload

Current state:

- implemented
- exposes `finalize-video` entry point

### `app/pipeline/common/`

Shared helpers used by multiple pipeline stages.

- `script_contract.py` — scene marker parsing, timestamp helpers, visual-segment loading, and `validate_visual_segments()` (the Stage 0 trust boundary).
- `video_encoder.py` — `resolve_encoder()`, `nvenc_available()`, `encoder_ffmpeg_args()`. Used by Stage 4 and Stage 5 to produce the `-c:v ...` argument list.

### `app/pipeline/stage0_indexers/`

Strategy implementations driven by `stage0_index_visuals.py`.

- `base.py` — `VisualIndexerStrategy` abstract class and the `merge_segments` helper.
- `gemini.py` — Gemini 3 Flash backend used by Stage 0. Character tags are inferred automatically when the model is confident.
- `ollama.py` — removed.

### `app/tools/transcribe_audio.py`

Purpose:

- transcribe one `.mp3` file or a directory tree of `.mp3` files into `.txt`

Current state:

- implemented utility (not a pipeline stage; used when preparing voice-clone references)
- exposes `transcribe` entry point
- covered by automated tests with injected fake model

### `app/tools/voice_analysis.py`

Purpose:

- one-off analysis helper for TTS experiments
- computes pacing, pauses, pitch, and energy stats from a reference audio plus transcript

Current state:

- implemented utility (not a pipeline stage)
- not part of the main pipeline contract

### `app/tools/prepare_voice_reference.py`

Purpose:

- prepare the canonical `styles/voice-assets/<style>/reference/clone_reference.*` bundle for Stage 3 ICL voice cloning
- enforce the current 90-second ICL reference target by requiring either a source clip already within that target or an explicit `--start` / `--end` selection from a longer file
- reuse the existing transcription and voice-analysis utilities so the prepared bundle includes `clone_reference.mp3`, `clone_reference.txt`, and `clone_reference.analysis.json`

Current state:

- implemented utility (not a pipeline stage)
- exposes `prepare-voice-reference` entry point
- covered by focused tests with injected ffmpeg, transcription, and analysis dependencies

## 5. Planned But Not Yet Implemented

These components are part of the project design but are not yet present as first-class production modules:

- automated Stage 2 model execution inside the repo — today the repo assembles prompts, but a human still runs the writer and grounder passes
- `app/pipeline/archetype_mapper.py` — style-A-specific character mapping helper
- `styles/xiaodao.md` — Style C, research phase only

## 6. Data Contracts

### Subtitle JSON Contract

`stage1_parse_subtitles.py --format json` emits a list of objects shaped like:

```json
{
  "start": 12.34,
  "end": 15.67,
  "text": "subtitle text",
  "speaker": null,
  "style": null
}
```

Notes:

- `speaker` and `style` are populated for ASS when available
- plain-text export writes only the normalized `text` lines in order

### Script Marker Contract

Primary structural markers currently used by downstream tooling:

- legacy scene shorthand: `[SCENE: HH:MM:SS-HH:MM:SS]`
- grounded scene marker: `[SCENE start=HH:MM:SS.mmm end=HH:MM:SS.mmm source=srt|visual confidence=0.00 evidence=srt:NNN|visual:NNN]`
- ungrounded scene marker: `[SCENE source=ungrounded confidence=0.00 evidence=none]`
- optional scene attribute: `characters="Name A|Name B"` for fallback B-roll selection
- `[BROLL: HH:MM:SS-HH:MM:SS, ...]`
- `[TITLE]`, `[HOOK]`, `[ACT ...]`, `[CLOSING]` as structural labels for script organization

Notes:

- the parser accepts both legacy and attribute forms
- downstream extraction and rendering use `source`, `evidence`, and `characters` when present

### Grounding Decision Contract

- dialogue beats should prefer SRT evidence and timestamps
- action beats should prefer visual-segment evidence
- weak matches should be emitted as `source=ungrounded` rather than guessed into fake timestamps
- Stage 4 and Stage 5 use `scene_evidence` and `scene_characters` to steer fallback extraction and semantic B-roll selection

### Voice Manifest Contract

`stage3_generate_audio.py` writes a JSON list where each entry contains:

- `index`
- `scene_start`
- `scene_end`
- `scene_source`
- `scene_confidence`
- `scene_evidence`
- `scene_characters`
- `text`
- `broll`
- `audio_start_s`
- `audio_end_s`

This manifest is the primary sync contract for `stage5_render_video.py`.

### Visual Segment Contract

`stage0_index_visuals.py` writes a JSON list where each entry contains:

- optional `id` (when absent, loaders assign `visual:NNN`)
- `start` (HH:MM:SS.mmm, always within `[0, video_duration]` after validation)
- `end` (HH:MM:SS.mmm, clamped to video duration, always greater than `start`)
- `summary`
- `ocr_text`
- `characters`

These segments exist for non-dialogue grounding. Dialogue beats should anchor to SRT instead of requiring duplicate Stage 0 coverage. The VLM is instructed to emit event-based segments (typically 2-8s, hard cap 12s) and to skip shot-reverse-shot dialogue where nothing visual changes.

Each Stage 0 chunk has its chunk-local PTS burned into the top-left corner so the VLM reads timestamps off the frame rather than estimating them. After inference, segment `start`/`end` are snapped to ffmpeg-detected shot boundaries within a 1.5s tolerance; anything outside tolerance is left untouched.

Every segment in the written file has already passed `validate_visual_segments()`. Downstream stages should not re-check bounds but may call the validator again defensively.

### Output Layout Contract

Expected generated asset layout:

```text
movies/<title>/
  script_<style>_draft.txt
  voiceover_<style>_voiceclone.mp3
  voiceover_<style>_voiceclone.manifest.json
  output/
    clips/clip_NNN.mp4
    clips/broll_NNN_a.mp4
    keyframes/keyframe_NNN.jpg
    segments/segment_NNN.mp4
    review.mp4
    final_video.mp4
```

## 7. Entry Points

Configured in `pyproject.toml`:

- `index-visuals = app.pipeline.stage0_index_visuals:main`
- `parse-subtitles = app.pipeline.stage1_parse_subtitles:main`
- `generate-script = app.pipeline.stage2_generate_script:main`
- `generate-audio = app.pipeline.stage3_generate_audio:main`
- `video-processor = app.pipeline.stage4_video_processor:main`
- `render-video = app.pipeline.stage5_render_video:main`
- `finalize-video = app.pipeline.stage6_finalize_video:main`
- `transcribe = app.tools.transcribe_audio:main`
- `prepare-voice-reference = app.tools.prepare_voice_reference:main`

## 8. Testing Baseline

Automated coverage currently exists for:

- subtitle parsing
- subtitle CLI behavior
- transcription input collection
- transcription CLI flow with a fake model
- reference-preparation CLI flow with injected ffmpeg, transcription, and analysis helpers

Verified baseline on 2026-04-21:

- `conda run -n py312_machine_learning --no-capture-output pytest`
- result: `16 passed`

## 9. Known Technical Gaps

The repo still needs dedicated engineering work in these areas:

1. script generation is still not automated through a committed production module
2. style-aware character mapping is still a planned component, not an implemented one
3. render stage 2 and 3 features remain open: transitions, subtitle burn, BGM ducking, richer fallback logic
4. broader tests are still needed for media-heavy scripts
5. Style C exists as research only, not as a runnable style file
