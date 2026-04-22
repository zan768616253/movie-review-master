# Technical Documentation

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
      stage1_parse_subtitles.py
      stage2_generate_script.py
      stage3_generate_audio.py
      stage4_video_processor.py
      stage5_render_video.py
    tools/
      __init__.py
      transcribe_audio.py
      voice_analysis.py
  voice-assets/
    uncle_niu/
      analysis/
      reference/
    first_person_pov/
      analysis/
    xiaodao/
      analysis/
  styles/
    niu-shu.md
    first-person-pov.md
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
- export plain text or JSON

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

- document the script-authoring step
- assemble the LLM prompt that turns subtitles + style rulebook into a reviewable draft with `[SCENE]` and `[BROLL]` markers

Current state:

- placeholder: rich module docstring + `build_prompt()` helper
- exposes `generate-script` entry point that prints the assembled prompt to stdout
- Stage 2 is run manually today (paste prompt into Claude, paste response into a draft file); `build_prompt()` is the stable contract an automated backend can drop into later

### `app/pipeline/stage3_generate_audio.py`

Purpose:

- parse a marked script into narration chunks
- run TTS
- concatenate audio
- emit a manifest that maps chunks to time ranges in the final audio

Current state:

- implemented for the current Style A production path
- exposes `generate-audio` entry point
- defaults to the Style A reference pair at `voice-assets/uncle_niu/reference/clone_reference.{mp3,txt}`

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

### `app/pipeline/stage5_render_video.py`

Purpose:

- read the voiceover manifest
- render per-chunk video segments
- concatenate segments
- mux the narration track into `final_video.mp4`

Current state:

- implemented stage 1 baseline
- exposes `render-video` entry point

Current stage-1 characteristics:

- hard cuts
- no subtitle burn
- no background music
- B-roll rotation supported through pre-extracted clip inputs

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

## 5. Planned But Not Yet Implemented

These components are part of the project design but are not yet present as first-class production modules:

- `app/pipeline/stage2_generate_script.py` — currently a placeholder; automated LLM-backed generation is planned
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

- `[SCENE: HH:MM:SS-HH:MM:SS]`
- `[BROLL: HH:MM:SS-HH:MM:SS, ...]`
- `[TITLE]`, `[HOOK]`, `[ACT ...]`, `[CLOSING]` as structural labels for script organization

### Voice Manifest Contract

`stage3_generate_audio.py` writes a JSON list where each entry contains:

- `index`
- `scene_start`
- `scene_end`
- `text`
- `broll`
- `audio_start_s`
- `audio_end_s`

This manifest is the primary sync contract for `stage5_render_video.py`.

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
    final_video.mp4
```

## 7. Entry Points

Configured in `pyproject.toml`:

- `parse-subtitles = app.pipeline.stage1_parse_subtitles:main`
- `generate-script = app.pipeline.stage2_generate_script:main`
- `generate-audio = app.pipeline.stage3_generate_audio:main`
- `video-processor = app.pipeline.stage4_video_processor:main`
- `render-video = app.pipeline.stage5_render_video:main`
- `transcribe = app.tools.transcribe_audio:main`

## 8. Testing Baseline

Automated coverage currently exists for:

- subtitle parsing
- subtitle CLI behavior
- transcription input collection
- transcription CLI flow with a fake model

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
