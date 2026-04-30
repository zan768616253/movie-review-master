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
      stage4_align_subtitles.py
      stage5_video_processor.py
      stage6_render_video.py
      stage7_finalize_video.py
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

- build a single planner-writer prompt that picks visual anchors AND writes narration in one LLM pass
- emit a chronological merged timeline of `[srt:NNN]` dialogue lines and `[shot:NNN]` source-shot entries that the planner picks ranges from
- enforce a shot-aware range contract: every anchor range must stay inside one source shot

Current state:

- implemented as a manual single-pass prompt assembler (replaces the old writer + grounder two-pass design)
- exposes `generate-script` entry point that prints the prompt to stdout
- accepts an optional `--synopsis` flag for user-authored plot/cast context
- Stage 2 is run manually: the repo writes the prompt, the user pastes it into an LLM (Gemini 3 Pro / Qwen 3.6) and pastes the reply back; `tmp/step_02_generate_script.py` validates the reply on the second run

Key public pieces:

- `build_planner_prompt()` — assembles the prompt
- `build_merged_timeline()` — interleaves SRT and per-shot visual entries chronologically
- `split_segment_into_shots()` — expands one Stage 0 visual segment into 1+ shots based on `shot_boundaries_s`
- `main()`

Shot-aware range contract (enforced by validator + prompt):

- each anchor range must stay inside one source shot — no shot-boundary crossings
- each individual range duration ≤ `MAX_ANCHOR_RANGE_DURATION_S` (12s)
- each anchor's total duration (sum of range durations) ≤ `MAX_ANCHOR_TOTAL_DURATION_S` (12s)
- range timestamps must come from `[shot:NNN]` lines, not `[srt:NNN]` lines
- multi-shot beats use multi-range anchors with one range per shot

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

### `app/pipeline/stage4_align_subtitles.py`

Purpose:

- split Stage 3 narration chunks into shorter subtitle cues
- derive cue timing from the real Stage 3 voiceover using pause detection
- emit `subtitle_manifest.json` for the render stage

Current state:

- implemented
- exposes `align-subtitles` entry point

Important contract:

- output is `subtitle_manifest.json`
- each cue entry carries `index`, `chunk_index`, `text`, `start_s`, and `end_s`

### `app/pipeline/stage5_video_processor.py`

Purpose:

- parse `[ANCHOR]` markers from a script
- extract silent source clips and keyframes with `ffmpeg`

Current state:

- implemented
- exposes `video-processor` entry point

### `app/pipeline/stage6_render_video.py`

Purpose:

- read the voiceover manifest
- read the subtitle manifest
- render per-chunk video segments
- concatenate segments
- mux the narration track into `review.mp4`

Current state:

- implemented stage 1 baseline
- exposes `render-video` entry point

Current stage-1 characteristics:

- hard cuts
- subtitle burn from `subtitle_manifest.json`
- no background music
- B-roll rotation supported through pre-extracted clip inputs

Key CLI flags:

- `--encoder {auto,nvenc,libx264}` (default `auto`) — same selector used by Stage 5. Used for hero slices, manual B-roll re-encodes, semantic B-roll re-encodes, and still-frame segments.

### `app/pipeline/stage7_finalize_video.py`

Purpose:

- take the Stage 6 draft render as the locked picture source
- take the Stage 3 voiceover as the authoritative narration source
- emit `final_video.mp4` with `+faststart` for direct upload

Current state:

- implemented
- exposes `finalize-video` entry point

### `app/pipeline/common/`

Shared helpers used by multiple pipeline stages.

- `script_contract.py` — scene marker parsing, timestamp helpers, visual-segment loading, and `validate_visual_segments()` (the Stage 0 trust boundary).
- `video_encoder.py` — `resolve_encoder()`, `nvenc_available()`, `encoder_ffmpeg_args()`. Used by Stage 5 and Stage 6 to produce the `-c:v ...` argument list.

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

- automated Stage 2 model execution inside the repo — today the repo assembles the planner prompt, but a human still runs the LLM call and pastes the reply back
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

Primary structural markers used by downstream tooling:

- `[ANCHOR ranges="HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS" characters="Name A|Name B"]` —
  one or more chronological source-movie ranges followed by the
  narration text bounded by `sum(range_seconds) × chars_per_second`.
- `[TITLE]`, `[HOOK]`, `[ACT ...]`, `[CLOSING]` as structural labels.

Anchor invariants (parser + validator):

- ranges within one anchor are non-overlapping; the parser sorts them by
  start time so playback is always forward in source time
- each range duration ≤ `MAX_ANCHOR_RANGE_DURATION_S` (12s)
- anchor total duration (sum of range durations) ≤ `MAX_ANCHOR_TOTAL_DURATION_S` (12s)
- each range stays inside ONE source shot (`range_shot_crossing` validator
  check against the global shot-boundary set built from
  `visual_segments.json`)
- range timestamps must overlap a real timeline entry — anchors are not
  allowed to invent timestamps
- anchors march chronologically across the script within each section
- closing chunk has narration but no `[ANCHOR]` — renders over a still keyframe

### Validation Decision Contract

- `validate_anchored_script(text, chars_per_second, timeline_intervals=..., shot_boundaries=...)` returns per-anchor budget verdicts and script-level structure issues
- per-anchor severity tiers: `ok` (≤1.0× budget) / `warn` (≤1.10×, Stage 6 absorbs visual slack) / `fail` (>1.10×, manual rewrite required)
- script-level fail codes: `no_title`, `no_anchors`, `orphan_narration`, `non_monotonic`, `bad_anchor`, `range_too_long`, `anchor_too_long`, `range_shot_crossing`, `range_provenance` (when timeline intervals supplied)
- narration is sacred — the pipeline never trims narration text or speeds up audio. When a chunk overruns budget, Stage 6's smart-trim removes visual slack at shot boundaries instead

### Voice Manifest Contract

`stage3_generate_audio.py` writes a JSON list where each entry contains:

- `index`
- `ranges`
- `characters`
- `text`
- `audio_start_s`
- `audio_end_s`

This manifest is the primary sync contract for `stage6_render_video.py`.

### Subtitle Manifest Contract

`stage4_align_subtitles.py` writes a JSON list where each entry contains:

- `index`
- `chunk_index`
- `text`
- `start_s`
- `end_s`

This manifest is the subtitle sync contract for `stage6_render_video.py`.

### Visual Segment Contract

`stage0_index_visuals.py` writes a JSON list where each entry contains:

- optional `id` (when absent, loaders assign `visual:NNN`)
- `start` (HH:MM:SS.mmm, always within `[0, video_duration]` after validation)
- `end` (HH:MM:SS.mmm, clamped to video duration, always greater than `start`)
- `summary`
- `ocr_text`
- `characters`
- `shot_boundaries_s` — list of cut times (absolute seconds, sorted) that
  fall strictly inside the `(start, end)` window. Empty list when no
  internal cuts. Used by Stage 2 to split each segment into per-shot
  timeline entries (`split_segment_into_shots`) and by Stage 6's smart-trim
  for shot-aware tail-cuts.
  - **Migration note:** until 2026-04-30, `merge_segments` left this
    field in chunk-local seconds while shifting `start`/`end` to
    absolute. Use `tmp/migrate_shot_boundaries.py` (chunk-offset
    arithmetic, no API or ffmpeg cost) on existing `visual_segments.json`
    files generated before that date.

These segments exist for non-dialogue grounding. Dialogue beats should anchor to SRT instead of requiring duplicate Stage 0 coverage. The VLM is instructed to emit event-based segments (typically 2-8s, hard cap 12s) and to skip shot-reverse-shot dialogue where nothing visual changes.

Each Stage 0 chunk has its chunk-local PTS burned into the top-left corner so the VLM reads timestamps off the frame rather than estimating them. After inference, segment `start`/`end` are snapped to ffmpeg-detected shot boundaries within a 1.5s tolerance; anything outside tolerance is left untouched. The same scene-detection pass populates each segment's `shot_boundaries_s` annotation with cuts that fall strictly inside the (snapped) window.

**Optional Cast Reference (synopsis enrichment):** `stage0_index_visuals.py` accepts `--synopsis PATH`. When supplied, the synopsis text is inlined into the VLM prompt as a Cast Reference block, and the VLM's character-labeling rule flips from "only names you can re-identify visually within this chunk" to "any name on the Cast Reference, never names outside it". The harness `tmp/step_00_index_visuals.py` auto-attaches `movies/<slug>/synopsis.md` when present. This produces consistent character names across chunks without risking franchise-knowledge over-attribution.

The full set of shot-cut timestamps in the source movie is reconstructed by `build_shot_boundary_set(visual_segments)`: union of every segment's start/end (excluding the t=0 movie start) with every entry in any segment's `shot_boundaries_s`. Stage 2's validator uses this set to reject anchor ranges that would bridge a hard cut.

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
- `align-subtitles = app.pipeline.stage4_align_subtitles:main`
- `video-processor = app.pipeline.stage5_video_processor:main`
- `render-video = app.pipeline.stage6_render_video:main`
- `finalize-video = app.pipeline.stage7_finalize_video:main`
- `transcribe = app.tools.transcribe_audio:main`
- `prepare-voice-reference = app.tools.prepare_voice_reference:main`

## 8. Testing Baseline

Automated coverage currently exists for:

- subtitle parsing
- subtitle CLI behavior
- transcription input collection
- transcription CLI flow with a fake model
- reference-preparation CLI flow with injected ffmpeg, transcription, and analysis helpers

Verified baseline:

- `conda run -n py312_machine_learning --no-capture-output pytest`
- result: `140 passed, 1 skipped`

## 9. Known Technical Gaps

The repo still needs dedicated engineering work in these areas:

1. script generation is still not automated through a committed production module
2. style-aware character mapping is still a planned component, not an implemented one
3. render stage 2 and 3 features remain open: transitions, subtitle burn, BGM ducking, richer fallback logic
4. broader tests are still needed for media-heavy scripts
5. Style C exists as research only, not as a runnable style file
