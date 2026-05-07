# Technical Documentation

> **NOTE (2026-05-04):** The audio-driven `[ANCHOR]` pipeline was retired
> in May 2026. Stages 2–6 of the new video-driven pipeline are
> **designed but not yet implemented**. This document describes the
> post-cleanup repository state and the target module boundaries.

This document is the code-facing reference for repository structure, entry points, contracts, and implementation boundaries. It complements the handbook instead of duplicating it.

## 1. Source-of-Truth Split

- product scope: [PROD.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/PROD.md)
- stable design knowledge: [docs/HANDBOOK.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/HANDBOOK.md)
- current status and next tasks: [plan.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/plan.md)
- implementation details: this file

## 2. Repository Map (post-cleanup)

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
      stage0_index_visuals.py        # shot detection (auto)
      stage0_indexers/
        __init__.py
        base.py
        gemini.py
        openrouter.py
        shared.py
      stage1_parse_subtitles.py      # subtitle parse (auto)
      stage4_align_subtitles.py      # subtitle cues from voiceover (auto, legacy numbering)
      stage7_finalize_video.py       # mux to final_video.mp4 (auto, legacy numbering)
      common/
        __init__.py
        json_io.py
        script_contract.py           # time helpers, visual-segment validation, shot-boundary set
        video_encoder.py             # NVENC/libx264 selector
    tools/
      __init__.py
      transcribe_audio.py
      voice_analysis.py
      prepare_voice_reference.py
  styles/
    niu-shu.md
    first-person-pov.md
    voice-assets/
      niu-shu/{analysis,reference}/
      first-person-pov/analysis/
      xiao-dao/analysis/
  tests/
    pipeline/
      test_stage0_visual_indexing.py
      test_stage0_visual_indexing_integration.py
      test_stage1_parse_subtitles.py
      test_stage4_align_subtitles.py
      test_stage7_finalize_video.py
    tools/
      test_prepare_voice_reference.py
      test_transcribe_audio.py
      test_video_encoder.py
  tmp/
    README.md
    _common.py
    configs/
    step_00_index_visuals.py
    step_01_parse_subtitles.py
    work/<movie_slug>/stage0/        # stage0 outputs preserved across cleanup
```

Note on numbering: surviving modules retain their legacy numeric prefixes (`stage4_align_subtitles`, `stage7_finalize_video`) until the new pipeline modules land. The target numbering after the rebuild is documented in §5.

## 3. Environment and Execution Rules

Canonical Python command rule:

- every Python command must be prefixed with `conda run -n py312_machine_learning --no-capture-output`
- dependency updates go through `pyproject.toml`, then `pip install -e .`

Reference: [docs/agent-rules/python-environment.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/agent-rules/python-environment.md)

## 4. Current Script Inventory

Pipeline modules use a `stageN_` prefix. Tools live under `app/tools/`.

### `app/pipeline/stage0_index_visuals.py`

Purpose:

- detect every shot in the source movie via VLM + ffmpeg scene-detect
- emit `visual_segments.json`

Status: implemented. Entry point: `index-visuals`.

### `app/pipeline/stage1_parse_subtitles.py`

Purpose:

- parse `.srt` / `.ass` subtitles into normalized text and structured JSON

Status: implemented. Entry point: `parse-subtitles`. Test-covered.

### `app/pipeline/stage4_align_subtitles.py`

Purpose:

- split voiceover narration into shorter subtitle cues using ffmpeg `silencedetect`
- emit `subtitle_manifest.json`

Status: implemented (legacy numbering retained — will be renamed to `stage7_align_subtitles.py` when the new pipeline lands). Entry point: `align-subtitles`.

### `app/pipeline/stage7_finalize_video.py`

Purpose:

- remux the draft `review.mp4` with the voiceover into an upload-ready `final_video.mp4` with `+faststart`

Status: implemented (legacy numbering retained — will be renamed to `stage9_finalize_video.py` when the new pipeline lands). Entry point: `finalize-video`.

### `app/pipeline/common/script_contract.py`

Shared time, shot-boundary, and visual-segment helpers. Trust boundary between Stage 0 (VLM output) and the rest of the pipeline.

Public surface:

- `timestamp_to_seconds`, `seconds_to_timestamp`, `normalize_timestamp`
- `probe_media_duration`, `get_video_duration`
- `validate_visual_segments`, `VisualSegmentDiagnostics`, `MAX_VISUAL_SEGMENT_DURATION_S`
- `load_visual_segments`
- `build_shot_boundary_set`, `should_collapse_segment_inner_cuts`, `COLLAPSE_INNER_CUTS_BELOW_S`
- `REAL_TTS_CPS = 6.74` (measured TTS speech rate, used to estimate narration audio duration from char count)

### `app/pipeline/common/video_encoder.py`

`resolve_encoder()`, `nvenc_available()`, `encoder_ffmpeg_args()`. Used wherever the pipeline emits `-c:v ...` arguments. Prefers `h264_nvenc` on the RTX 4060 target, falls back to `libx264 -preset fast`.

### `app/pipeline/common/json_io.py`

Generic JSON read/write helpers used by every stage that produces a manifest.

### `app/pipeline/stage0_indexers/`

Strategy implementations driven by `stage0_index_visuals.py`:

- `base.py` — `VisualIndexerStrategy` abstract class and the `merge_segments` helper
- `gemini.py` — Gemini 3 Flash backend (default)
- `openrouter.py` — OpenRouter backend (alternative)
- `shared.py` — shared utilities

### `app/tools/transcribe_audio.py`

Transcribe one `.mp3` file or a directory tree of `.mp3` files into `.txt`. Used when preparing voice-clone references. Entry point: `transcribe`. Test-covered.

### `app/tools/build_story_prompt.py`

Build a copy-paste prompt for external LLMs to draft a full movie-retelling script from a style markdown file, Stage 0 `visual_segments.json`, and Stage 1 `subtitles.json`. The tool converts the structured inputs into a single chronological plain-text timeline so the external model can infer the whole movie without watching it. Entry point: `build-story-prompt`. Test-covered.

### `app/tools/generate_script_audio.py`

Generate a voice-cloned narration MP3 plus a chunk manifest from the final manual script text. Entry point: `generate-script-audio`. Test-covered.

### `app/tools/generate_audio_subtitles.py`

Generate subtitle files for the narration audio from the final script text and generated audio. The tool prefers the sibling audio manifest for exact chunk timing and falls back to proportional timing when no manifest is available. Entry point: `generate-audio-subtitles`. Test-covered.

### `app/tools/voice_analysis.py`

One-off analysis helper for TTS experiments. Computes pacing, pauses, pitch, and energy stats from a reference audio plus transcript. Not a pipeline stage.

### `app/tools/prepare_voice_reference.py`

Prepare the canonical `styles/voice-assets/<style>/reference/clone_reference.*` bundle for ICL voice cloning. Entry point: `prepare-voice-reference`. Test-covered.

## 5. New Pipeline — Module Boundaries (designed, not implemented)

The numbering below is the **target** layout for the new video-driven pipeline. Surviving legacy files (current `stage4_align_subtitles.py`, current `stage7_finalize_video.py`) keep their old numbers in the meantime; they will be renamed to match this layout when the surrounding stages are implemented.

| # | Target Module | Role | Auto/Manual |
|---|---|---|---|
| 0 | `stage0_index_visuals.py` | Shot detection | Auto (already exists) |
| 1 | `stage1_parse_subtitles.py` | Subtitle parse | Auto (already exists) |
| 2 | `stage2_select_shots.py` | Shot selection | Manual v1 → Auto v2 |
| 3 | `stage3_assemble_rough_cut.py` | Rough cut concat + beat segmentation | Auto |
| 4 | `stage4_write_narration.py` | Narration writing | Manual v1 → Auto v2 |
| 5 | `stage5_generate_audio.py` | TTS + voiceover concat | Auto |
| 6 | `stage6_fit_visuals.py` | Per-beat trim/loop to fit TTS duration | Auto |
| 7 | `stage7_align_subtitles.py` | Subtitle cues (renamed from current `stage4_align_subtitles.py`) | Auto |
| 8 | `stage8_render_video.py` | Concat fitted beats, burn subs, mux audio | Auto |
| 9 | `stage9_finalize_video.py` | Upload-ready remux (renamed from current `stage7_finalize_video.py`) | Auto |

Each new module is a single CLI entry point with explicit input/output paths. The modules do not import each other; they communicate through the JSON manifests in §6.

## 6. Data Contracts

### Visual Segment Contract (Stage 0)

`stage0_index_visuals.py` writes a JSON list where each entry contains:

- optional `id` (when absent, loaders assign `visual:NNN`)
- `start` (HH:MM:SS.mmm, always within `[0, video_duration]` after validation)
- `end` (HH:MM:SS.mmm, clamped to video duration, always greater than `start`)
- `summary`
- `ocr_text`
- `characters`
- `shot_boundaries_s` — list of cut times (absolute seconds, sorted) that fall strictly inside the `(start, end)` window

Every segment in the written file has already passed `validate_visual_segments()`. Downstream stages may call the validator again defensively but should not re-clamp.

The full set of shot-cut timestamps is reconstructed by `build_shot_boundary_set(visual_segments)`: union of every segment's start/end (excluding the t=0 movie start) with every entry in any segment's `shot_boundaries_s` (subject to inner-cut collapse for segments where micro-cuts represent false granularity).

**Required Cast Reference and Face Gallery:** `stage0_index_visuals.py` now requires both `--synopsis PATH` and `--characters-dir DIR`. The synopsis text is always inlined into the VLM prompt as a Cast Reference block, and the face-gallery directory must contain at least one reference image so the VLM can label characters consistently across chunks.

### Subtitle JSON Contract (Stage 1)

`stage1_parse_subtitles.py --format json` emits a list shaped like:

```json
{ "start": 12.34, "end": 15.67, "text": "subtitle text", "speaker": null, "style": null }
```

`speaker` and `style` are populated for ASS when available. Plain-text export writes only the normalized `text` lines in order.

### Selected Shots Contract (Stage 2 — designed)

```json
[
  {
    "shot_id": "visual:042",
    "start": "00:14:23.500",
    "end": "00:14:27.100",
    "tags": ["hook", "establishing"]
  },
  ...
]
```

Order is chronological. `tags` is optional and free-form for now.

### Rough Cut Manifest (Stage 3 — designed)

```json
[
  {
    "beat_index": 1,
    "shot_ids": ["visual:042", "visual:043", "visual:045"],
    "start_s": 0.0,
    "end_s": 38.4,
    "total_duration_s": 38.4
  },
  ...
]
```

`start_s`/`end_s` are positions inside `rough_cut.mp4`, not source-movie timestamps.

### Narration Contract (Stage 4 — designed)

```json
[
  { "beat_index": 1, "text": "narration line for this beat" },
  ...
]
```

### Voiceover Manifest (Stage 5 — designed, names preserved from legacy)

```json
[
  {
    "index": 1,
    "text": "narration line for this beat",
    "audio_start_s": 0.0,
    "audio_end_s": 4.82
  },
  ...
]
```

`index` corresponds to `beat_index` from Stage 3/4. Field names `text`, `audio_start_s`, `audio_end_s` are preserved from the legacy contract so existing consumers (Stage 7 subtitle alignment) continue to work without changes.

### Subtitle Manifest (Stage 7)

`stage4_align_subtitles.py` writes a JSON list where each entry contains:

- `index`
- `chunk_index` (= beat index from the voiceover manifest)
- `text`
- `start_s`
- `end_s`

### Output Layout Contract

Expected generated asset layout once the new pipeline is complete:

```text
movies/<title>/
  selected_shots.json
  narration.json
  voiceover_<style>.mp3
  voiceover_<style>.manifest.json
  output/
    rough_cut/rough_cut.mp4
    rough_cut/rough_cut.json
    fitted/beat_NNN.mp4
    keyframes/keyframe_NNN.jpg
    review.mp4
    final_video.mp4
```

## 7. Entry Points

Configured in `pyproject.toml`:

- `index-visuals = app.pipeline.stage0_index_visuals:main`
- `parse-subtitles = app.pipeline.stage1_parse_subtitles:main`
- `align-subtitles = app.pipeline.stage4_align_subtitles:main`
- `finalize-video = app.pipeline.stage7_finalize_video:main`
- `transcribe = app.tools.transcribe_audio:main`
- `build-story-prompt = app.tools.build_story_prompt:main`
- `prepare-voice-reference = app.tools.prepare_voice_reference:main`
- `generate-script-audio = app.tools.generate_script_audio:main`
- `generate-audio-subtitles = app.tools.generate_audio_subtitles:main`

New entry points (`select-shots`, `assemble-rough-cut`, `write-narration`, `generate-audio`, `fit-visuals`, `render-video`) will be added as those modules land.

## 8. Testing Baseline

Automated coverage exists for:

- subtitle parsing
- subtitle CLI behavior
- transcription input collection and CLI flow with a fake model
- reference-preparation CLI flow with injected ffmpeg, transcription, and analysis helpers
- subtitle alignment
- finalize/mux
- video-encoder selection

Pre-cleanup baseline: `140 passed, 1 skipped`. Post-cleanup: `70 passed, 3 failed`. The 3 failures are pre-existing assertions about Stage 0 chunk duration (changed in commit `d3bb445` from 6 to 7 minutes); the test file was not updated. They are unrelated to the pipeline architecture change and tracked in `plan.md`.

## 9. Known Technical Gaps

The repo needs dedicated engineering work in these areas:

1. **Stages 2–6 and 8 are not implemented.** Module sketches in §5 above; full status in `plan.md`.
2. **Stage 5 TTS engine** is recoverable from git history but needs to be re-fitted to the new beat-indexed input.
3. **Stage 0 chunk-duration test failures** need a one-line update to match the 7-minute production value.
4. **Stage 4 / Stage 7 will be renamed** to `stage7_align_subtitles` and `stage9_finalize_video` once the surrounding new stages exist.
5. Style C exists as research only, not as a runnable style file.
