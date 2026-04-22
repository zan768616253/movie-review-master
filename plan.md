# Project Plan

Last updated: 2026-04-21

`plan.md` is the live project tracker. Stable design knowledge lives in [docs/HANDBOOK.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/HANDBOOK.md). Coding contracts live in [docs/TECHNICAL.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/TECHNICAL.md).

## 1. Current Snapshot

- Documentation structure has been consolidated around `PROD.md`, `docs/HANDBOOK.md`, `plan.md`, and `docs/TECHNICAL.md`.
- Subtitle parsing is implemented and tested.
- Transcription CLI is implemented and tested.
- Utility modules now live under `app/tools/` instead of sitting beside the pipeline stages.
- Style A and Style B rule files exist.
- Style A audio generation, clip extraction, and stage-1 rendering scripts exist.
- The full script-generation module is still the biggest missing production component.

## 2. Verified Baseline

Verified on 2026-04-21:

- test command: `conda run -n py312_machine_learning --no-capture-output pytest`
- result: `16 passed`

## 3. Completed

- pipeline scripts renamed with `stageN_` prefix for obvious ordering
- `app/pipeline/stage1_parse_subtitles.py` supports `.srt` and `.ass`
- JSON and text subtitle exports exist
- `app/pipeline/stage2_generate_script.py` placeholder documents the manual script-authoring workflow and assembles the LLM prompt
- `app/pipeline/stage3_generate_audio.py` exists for the current Style A path
- `app/pipeline/stage4_video_processor.py` extracts primary clips, B-roll, and keyframes
- `app/pipeline/stage5_render_video.py` provides a stage-1 deterministic render path
- `app/tools/transcribe_audio.py` provides a reusable CLI (utility, not a stage)
- `app/tools/voice_analysis.py` provides one-off TTS reference analysis
- `styles/niu-shu.md` and `styles/first-person-pov.md` are present
- documentation cleanup and centralization completed on 2026-04-21

## 4. Active Priorities

1. Build the missing script-generation layer.
2. Strengthen the render pipeline beyond stage 1.
3. Finish Style C from research into a real style file.
4. Expand automated tests around media pipeline contracts.

## 5. Ordered Next Tasks

### Priority 1: automate `app/pipeline/stage2_generate_script.py`

Goal:

- turn the current prompt-assembler placeholder into an LLM-backed module that returns a finished script with valid `[SCENE]` markers

Needed:

- backend switch (Anthropic API first; local LLM fallback later) behind the existing `build_prompt()` contract
- style selection flow
- protagonist selection flow for Style B
- optional archetype mapping support for Style A

### Priority 2: render stage 2

Goal:

- improve viewer-facing quality without breaking the deterministic path

Needed:

- crossfades
- stronger short-clip fallback behavior
- subtitle generation and burn path
- optional BGM mixing and ducking

### Priority 3: Style C completion

Goal:

- move Xiaodao from research note to supported style asset

Needed:

- transcript the sample audio already in the repo
- extract repeatable opening, pacing, and closing patterns
- write `styles/xiaodao.md`

### Priority 4: testing expansion

Goal:

- make the media pipeline safer to change

Needed:

- tests for script marker parsing
- tests for manifest generation
- tests for render input validation paths

## 6. Risks and Gaps

- there is still no committed production script generator, so the pipeline is not yet end-to-end autonomous
- render quality features are partially implemented
- Style C remains design research, not a completed runnable path
- media-heavy steps depend on external tools and large assets, so regression coverage is still thinner than the parser/transcription layer

## 7. Definition Of “Next Milestone”

The next meaningful milestone is:

1. generate a valid marked script from subtitles
2. run voiceover generation on that script
3. extract clips
4. render a full draft end to end with no manual file reshaping between steps
