# Technical Documentation

Code-facing reference for repository structure, entry points, and data
contracts. Complements the handbook instead of duplicating it.

## 1. Source-of-Truth Split

- product scope: [PROD.md](../PROD.md)
- stable design knowledge: [docs/HANDBOOK.md](HANDBOOK.md)
- implementation details: this file

## 2. Repository Map

```text
movie-review-master/
  README.md
  PROD.md
  pyproject.toml
  docs/
    HANDBOOK.md
    TECHNICAL.md
    agent-rules/
  app/
    pipeline/
      stage_0_generate_subtitles.py # (optional) faster-whisper SRT when no human subtitle exists
      stage_1_index_visuals.py     # shot detection (auto)
      stage_1_parse_subtitles.py   # subtitle parse (auto)
      stage_2_build_prompt.py      # LLM prompt builder (story default; --digest pass 1)
      stage_3_generate_audio.py    # TTS the manual script -> MP3 + SRT + manifest
      indexers/                    # Gemini VLM strategy
        base.py
        gemini.py
        shared.py
      common/
        json_io.py
        script_contract.py         # time helpers, visual-segment validation
        subtitle_utils.py          # SRT cue rendering
        video_encoder.py           # ffmpeg hwaccel helpers (used by indexers)
    tools/
      prepare_voice_reference.py   # one-time voice-clone reference prep
      transcribe_audio.py          # one-time Whisper transcription helper
      voice_analysis.py            # one-time prosody analysis helper
  styles/
    niu-shu.md
    first-person-pov.md
    voice-assets/<style>/{reference,analysis}/
  workbench/                       # pipeline harness — see workbench/README.md
    configs/current_movie.toml
    step_0_generate_subtitles.py
    step_1_prepare_inputs.py
    step_2_build_prompt.py
    step_3_generate_audio.py
    tools/                         # one-time-per-style asset prep wrappers
    work/<movie_slug>/{stage0,stage1,stage2,stage3}/
  tests/
    pipeline/{test_stage_1_index_visuals,test_stage_1_index_visuals_integration,test_stage_1_parse_subtitles,test_stage_2_build_prompt,test_stage_3_generate_audio}.py
    tools/{test_prepare_voice_reference,test_transcribe_audio}.py
```

## 3. Environment and Execution

Every Python command must be prefixed with
`conda run -n py312_machine_learning --no-capture-output`. Dependency
changes go through `pyproject.toml` followed by `pip install -e .`.

Reference: [docs/agent-rules/python-environment.md](agent-rules/python-environment.md).

## 4. Pipeline Modules

### `app/pipeline/stage_0_generate_subtitles.py`

Optional. Scans the movie folder for `.srt` / `.ass` and skips when one
exists. Otherwise runs `faster-whisper` `large-v3` on CUDA (float16) and
writes a sibling `.srt` next to the video. Entry point: `generate-subtitles`.

### `app/pipeline/stage_1_index_visuals.py`

Detect every shot via Gemini 3 Flash + ffmpeg scene-detect, emit
`visual_segments.json`. Requires both `--synopsis` (inlined as Cast
Reference in the VLM prompt) and `--characters-dir` (non-empty face gallery
for consistent character naming across chunks). Entry point: `index-visuals`.

### `app/pipeline/stage_1_parse_subtitles.py`

Parse `.srt` / `.ass` subtitles into normalized text and structured JSON.
Entry point: `parse-subtitles`. Test-covered.

### `app/pipeline/stage_2_build_prompt.py`

Build the LLM prompt for movie script writing. Two modes via `--digest`:

- default (story): `build_story_prompt()` — single-pass timeline mode,
  or two-pass digest mode if `--plot-digest PATH` is supplied.
- `--digest`: `build_digest_prompt()` — emit the Pass 1 prompt that asks
  the LLM to extract a structured plot digest first.

Embeds the chosen style markdown verbatim and (optionally) a genre example
script. Entry point: `build-prompt`. Test-covered.

### `app/pipeline/stage_3_generate_audio.py`

TTS the final manual script with Qwen3 voice cloning. Produces:

- `voiceover_<tag>.mp3` — concatenated, loudness-normalized voice track.
- `voiceover_<tag>.manifest.json` — per-chunk `{index, section, text, audio_start_s, audio_end_s}`.
- `voiceover_<tag>.srt` — burnable subtitle cues built from the chunks.

Sampling resolves CLI > `voice_clone.toml` (per-style) > built-in defaults.
Entry point: `generate-script-audio`. Test-covered.

### `app/pipeline/indexers/`

Visual-indexer implementation for Stage 1:

- `base.py` — `VisualIndexerStrategy` abstract class plus `merge_segments`.
- `gemini.py` — Gemini 3 Flash backend.
- `shared.py` — shared utilities (chunk extraction, prompt assembly).

### Series support (TV / anime)

- `app/pipeline/series_context.py` — pure, string-only continuity helpers:
  `extract_continuity_section` (pull the digest's `## 承上启下` body),
  `update_series_context` (insert/replace a per-episode block, idempotent,
  sorted), `assemble_prior_context` (concatenate blocks for episodes `< N`).
- `workbench/_common.py` — series resolution: `is_series_config`,
  `series_episode_common` (synthesizes a movie-shaped `common` with
  `movie_slug = "<series_slug>/ep<NN>"` so `build_paths` nests the work dir),
  `series_context_file`, `load_active_config` (prefers a non-empty
  `current_series.toml`), and `resolve_run_context` (the single entry every step
  calls; returns `RunContext`). `build_paths` honors an optional
  `synopsis_file` override (default `synopsis.md`).
- Stage 2 builders accept `prior_context_text` (digest background / story recap
  source) and `request_carryover` (digest `## 承上启下`); the CLI exposes
  `--prior-context` and `--series-carryover`.
- `[RECAP]` is a structural opener recognized by `stage_3_generate_audio.py`
  (treated like `[HOOK]`) and `stage_2/post_validate.py` (which also exempts the
  `<refs>recap</refs>` sentinel from grounding checks).
- Per-series work dir: `workbench/work/<series_slug>/series_context.md` plus
  `workbench/work/<series_slug>/ep<NN>/stage0..4/`.

### `app/pipeline/common/script_contract.py`

Time helpers and Stage 1 trust boundary. Public surface:

- `timestamp_to_seconds`, `seconds_to_timestamp`, `normalize_timestamp`
- `probe_media_duration`, `get_video_duration`
- `validate_visual_segments`, `VisualSegmentDiagnostics`, `MAX_VISUAL_SEGMENT_DURATION_S`
- `load_visual_segments`
- `build_shot_boundary_set`, `should_collapse_segment_inner_cuts`
- `REAL_TTS_CPS = 6.74` (measured TTS speech rate)

### `app/pipeline/common/video_encoder.py`

ffmpeg hwaccel detection used by the indexers when chunking the source
video: `nvenc_available()`, `cuda_decode_available()`, `hwaccel_decode_args()`.

### `app/pipeline/common/json_io.py`, `subtitle_utils.py`

Generic JSON I/O and SRT cue rendering used across the codebase.

## 5. Tools

These are one-time-per-voice asset-prep CLIs, not part of the per-movie
pipeline. Wrappers live under `workbench/tools/`.

### `app/tools/prepare_voice_reference.py`

Slice a reference clip and place it under
`styles/voice-assets/<style>/reference/`. Entry point:
`prepare-voice-reference`.

### `app/tools/transcribe_audio.py`

Whisper-based transcription helper for one-shot voice-asset prep.
Entry point: `transcribe`.

### `app/tools/voice_analysis.py`

Emit prosody stats (pacing, pauses, pitch, energy) from a reference
audio + transcript pair. Used to tune `voice_clone.toml`.

## 6. Data Contracts

### Visual Segment Contract (Stage 1)

`stage_1_index_visuals.py` writes a JSON list. Each entry:

- optional `id` (loaders assign `visual:NNN` when absent)
- `start`, `end` (HH:MM:SS.mmm, validated to fall in `[0, video_duration]`)
- `summary`
- `ocr_text`
- `characters`
- `shot_boundaries_s` — sorted cut times strictly inside `(start, end)`

Every entry has already passed `validate_visual_segments()`.

### Subtitle JSON Contract (Stage 1)

`stage_1_parse_subtitles.py --format json` emits:

```json
{ "start": 12.34, "end": 15.67, "text": "subtitle text", "speaker": null, "style": null }
```

`speaker` / `style` are populated from ASS when available.

### Voiceover Manifest (Stage 3)

`stage_3_generate_audio.py` emits:

```json
{
  "index": 1,
  "section": "HOOK",
  "ranges": [],
  "characters": [],
  "text": "narration text for this chunk",
  "audio_start_s": 0.0,
  "audio_end_s": 4.82
}
```

One entry per script structural block (`[HOOK]`, `[ACT ...]`, `[CLOSING]`).

## 7. Entry Points

Configured in `pyproject.toml`:

- `generate-subtitles = app.pipeline.stage_0_generate_subtitles:main`
- `index-visuals = app.pipeline.stage_1_index_visuals:main`
- `parse-subtitles = app.pipeline.stage_1_parse_subtitles:main`
- `build-prompt = app.pipeline.stage_2_build_prompt:main`
- `generate-script-audio = app.pipeline.stage_3_generate_audio:main`
- `prepare-voice-reference = app.tools.prepare_voice_reference:main`
- `transcribe = app.tools.transcribe_audio:main`

## 8. Testing

Automated coverage:

- subtitle parsing + CLI behaviour
- visual indexing (mocked Gemini)
- prompt assembly (story + digest modes)
- TTS chunking + manifest layout
- transcription CLI with fake Whisper
- voice-reference preparation with injected ffmpeg/transcription helpers

Run from the repo root: `conda run -n py312_machine_learning --no-capture-output pytest`.
