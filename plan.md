# Plan

Live status and detailed task tracker. For stable design knowledge, see [docs/HANDBOOK.md](docs/HANDBOOK.md). For code-facing contracts, see [docs/TECHNICAL.md](docs/TECHNICAL.md).

This file is the **single source of truth for what to do next**. Any agent or human picking up the project should:

1. Read the **Status Snapshot** below to see which phase is active.
2. Find the first task with `[ ]` (not started) inside that phase.
3. Read its **Goal**, **Inputs**, **Outputs**, **Steps**, and **Done when** sections.
4. Update the checkbox and "Last updated" line when finishing the task.
5. If a task surfaces a new design decision, append it to **Open Design Questions**.

## How to fill a skeleton (read this before Phase 1+)

The new pipeline modules already exist as skeletons under `app/pipeline/stage{2,3,4,5,6,8}_*.py`. Each skeleton contains:

- A complete module docstring describing the stage's role, inputs, outputs.
- Dataclasses defining the JSON schemas (these are the contract — do not change field names without updating `docs/TECHNICAL.md §6` and the consumers).
- Helper function signatures with type hints + docstrings + a `raise NotImplementedError("Phase X.Y — see plan.md")` body.
- A wired-up `build_parser()` so `--help` already works.
- A `main()` stub that also raises `NotImplementedError`.

The corresponding harness scripts (`tmp/step_NN_*.py`) and entry points (`pyproject.toml`) are already wired. Path slots for every stage are in `tmp/_common.py`.

**To fill a skeleton:**

1. Open the skeleton file. The docstring tells you the role; the dataclasses tell you the I/O.
2. Find every `raise NotImplementedError("Phase X.Y — see plan.md")`. The phase tag points back to the relevant task in this file.
3. Implement the helpers. Keep pure logic in the helpers and dispatching/IO in `main()`.
4. Implement `main()`: parse args (already wired), validate inputs exist, call helpers, write outputs.
5. Add tests at `tests/pipeline/test_stage{N}_*.py` mirroring the patterns in `tests/pipeline/test_stage1_parse_subtitles.py` (pure helpers) and `tests/pipeline/test_stage7_finalize_video.py` (CLI with mocked subprocess).
6. Run `conda run -n py312_machine_learning --no-capture-output pytest` and confirm the new tests pass without breaking existing ones.
7. Run the harness `python tmp/step_NN_*.py` against the active movie config to validate end-to-end.
8. Update the corresponding task's checkbox `[ ]` → `[x]` and bump the **Last updated** line.

---

## Status Legend

- `[ ]` not started
- `[-]` in progress
- `[x]` done
- `[!]` blocked (with a note explaining why)

## Status Snapshot

| Phase | Goal | Status |
|---|---|---|
| **Phase 0** | Fix pre-existing Stage 0 test failures | `[x]` done |
| Phase 1 | Build Stage 2: shot selection (manual v1) | `[ ]` not started |
| Phase 2 | Build Stage 3: rough cut assembly | `[ ]` not started |
| Phase 3 | Build Stage 5: TTS (recover engine from git) | `[ ]` not started |
| Phase 4 | Build Stage 4: narration writing (manual v1) | `[ ]` not started |
| Phase 5 | Build Stage 6: visual fitting | `[ ]` not started |
| Phase 6 | Rename old `stage4_align_subtitles` → `stage7_align_subtitles` | `[ ]` not started |
| Phase 7 | Build Stage 8: draft render | `[ ]` not started |
| Phase 8 | Rename old `stage7_finalize_video` → `stage9_finalize_video` | `[ ]` not started |
| Phase 9 | End-to-end validation on `sha_po_lang_2` | `[ ]` not started |

**Active phase:** Phase 1.
**Last updated:** 2026-05-04 (Phase 0 complete; Stage 0 tests now match the 7-minute Gemini chunk duration and the suite is green).

---

## Background — what just happened

The audio-driven `[ANCHOR]` pipeline was retired in May 2026. Diagnosis: forcing variable-length narration onto fixed-length source ranges is structurally unsound, not an implementation bug. The project is rebuilding around a video-driven architecture (visuals first, narration second, audio rendered against narration, visuals trimmed to match audio).

### Cleanup pass (done 2026-05-04)

- Deleted obsolete pipeline modules: `stage2_generate_script.py`, `stage3_generate_audio.py` (driver only — TTS engine code is in git history), `stage5_video_processor.py`, `stage6_render_video.py`.
- Deleted backwards-compat shims (`stage4_video_processor.py`, `stage5_render_video.py`, `stage6_finalize_video.py`) and their duplicate tests.
- Pruned `app/pipeline/common/script_contract.py` from 1103 lines to 263 (anchor parsing, anchor validation, budget math removed; visual-segment validation, time helpers, shot-boundary set kept).
- Deleted obsolete tests, harness scripts (`tmp/step_02..._07_*`), and the `tmp/run_all.py` orchestrator.
- Deleted `docs/OVERHAUL_PLAN.md` and `styles/_style_contract.md` (both 100% about the dead anchor model).
- Swept `tmp/work/<slug>/stage1..7/` while preserving `tmp/work/<slug>/stage0/`.
- Updated `pyproject.toml` to drop dead entry points.
- Rewrote `PROD.md`, `docs/HANDBOOK.md`, `docs/TECHNICAL.md`, `tmp/README.md`.

Surviving code: `stage0_index_visuals.py`, `stage1_parse_subtitles.py`, `stage4_align_subtitles.py` (renames to `stage7` later), `stage7_finalize_video.py` (renames to `stage9` later), all of `app/tools/`, `app/pipeline/common/`, `app/pipeline/stage0_indexers/`.

### Framework scaffold (done 2026-05-04)

After the cleanup, skeleton files were added for every new stage so implementing agents work against fixed contracts:

- Created `app/pipeline/stage{2,3,4,5,6,8}_*.py` — module docstrings, dataclass schemas, helper signatures, wired-up `build_parser()`, `main()` stub. Bodies raise `NotImplementedError("Phase X.Y — see plan.md")`.
- Created `tmp/step_{02,03,04,05,06,08}_*.py` harness scripts that load config, build paths, dispatch to the matching stage's `main()`.
- Updated `tmp/_common.py` with all 29 path slots the new pipeline needs (stage0–stage9 dirs plus per-stage artifact paths). Voiceover filename follows the new `voiceover_<tag>.{mp3,manifest.json}` pattern.
- Registered new entry points in `pyproject.toml`: `select-shots`, `assemble-rough-cut`, `write-narration`, `generate-audio`, `fit-visuals`, `render-video`.
- Verified all 6 new modules import cleanly and `--help` works for every new CLI.

Test baseline post-scaffold: **70 passed, 3 failed** (the 3 are pre-existing — see Phase 0). Framework adds zero test failures and zero passing tests; tests come from the implementing agents in each phase.

---

## Phase 0 — Fix Stage 0 chunk-duration test assertions

**Why first:** the test suite must be green before new work goes in, so failures from new code are easy to spot. The 3 current failures are pre-existing and unrelated to the architecture rebuild.

### Task 0.1 — Update test assertions to match 7-minute chunks

- [x] **Status:** done
- **Goal:** make `pytest` report 73 passed, 0 failed.
- **Why:** commit `d3bb445` changed Stage 0 production code to use 7-minute chunks instead of 6-minute. The test file's hard-coded assertions still expect 6 minutes.
- **Files:**
  - `tests/pipeline/test_stage0_visual_indexing.py`
- **Failing tests (run `conda run -n py312_machine_learning --no-capture-output pytest tests/pipeline/test_stage0_visual_indexing.py` to see current state):**
  - `TestGeminiStrategy::test_index_video_splits_and_merges`
  - `TestGeminiStrategy::test_index_video_persists_and_reuses_chunk_segments`
  - `TestGeminiStrategy::test_index_video_parallel_preserves_chunk_order`
- **Steps:**
  1. Open the test file, search for hard-coded chunk-duration assumptions: `00:06:00`, `360`, "6 minutes", or any integer math that expects 6-minute splits.
  2. Update those assertions to the 7-minute equivalent (`00:07:00`, `420` seconds).
  3. Cross-check against `app/pipeline/stage0_index_visuals.py` to find the canonical chunk-duration constant — match the test to that constant.
  4. Run pytest, confirm 73 passed.
- **Done when:**
  - `conda run -n py312_machine_learning --no-capture-output pytest` reports `73 passed, 0 failed` (1 skipped is also fine).

---

## Phase 1 — Stage 2: Shot Selection (manual v1)

**Why next:** smallest new module; produces the schema everything downstream depends on. Manual editing of `selected_shots.json` is fine for v1.

**What "manual v1" means:** the module produces a *scaffold* `selected_shots.json` populated with every Stage 0 shot pre-marked `keep=false`. The user opens that JSON in VSCode, flips `keep=true` on the shots they want in the review, and saves. A second invocation of the module validates the file.

### Task 1.1 — Define `selected_shots.json` schema

- [ ] **Status:** not started
- **Goal:** schema documented in `docs/TECHNICAL.md §6` and reflected in code.
- **Schema:**
  ```json
  [
    {
      "shot_id": "visual:042",
      "start": "00:14:23.500",
      "end": "00:14:27.100",
      "summary": "the protagonist enters the warehouse",
      "keep": true,
      "tags": ["hook"]
    }
  ]
  ```
  - `shot_id` references entries in Stage 0's `visual_segments.json`.
  - `keep` defaults to `false` in scaffold; user flips to `true`.
  - `tags` is optional, free-form (`hook`, `establishing`, `twist`, `climax`, etc.).
  - Order is chronological by `start`.
- **Steps:**
  1. Add a "Selected Shots Contract" example to `docs/TECHNICAL.md §6` matching the JSON above.
  2. Add a brief `Stage 2` row in the `docs/HANDBOOK.md §10` asset model showing where `selected_shots.json` lives in the per-movie folder.
- **Done when:** schema is in TECHNICAL.md and HANDBOOK.md; both files cross-link to this task's commit.

### Task 1.2 — Fill `app/pipeline/stage2_select_shots.py`

- [ ] **Status:** not started (skeleton exists; bodies raise `NotImplementedError`)
- **Goal:** working CLI that scaffolds the selection file or validates an existing one.
- **What's already in the skeleton:**
  - `SelectedShot` and `SelectionValidation` dataclasses (the contracts).
  - `build_parser()` fully wired (`--visual-segments`, `--out`, `--validate`, `--force`).
  - `main()` arg parsing complete; only the dispatch raises `NotImplementedError`.
- **Functions to implement (each currently raises `NotImplementedError`):**
  - `build_scaffold(visual_segments) -> list[SelectedShot]` — pure: build one entry per visual segment, all `keep=False`.
  - `validate_selection(visual_segments, selected_shots) -> SelectionValidation` — pure: check every `shot_id` exists, chronological order, at least one `keep=True`.
  - `load_selected_shots(path) -> list[SelectedShot]` — JSON I/O.
  - `dump_selected_shots(path, shots) -> None` — JSON I/O.
  - `main(argv)` — wire the helpers: scaffold mode (refuse overwrite without `--force`) or validate mode (print summary).
- **Available helpers to reuse:**
  - `app.pipeline.common.json_io.load_json` / `dump_json`
  - `app.pipeline.common.script_contract.load_visual_segments`
- **Done when:**
  - All `NotImplementedError` calls in this module are replaced.
  - Tests under Task 1.3 pass.
  - `select-shots --visual-segments tmp/work/sha_po_lang_2/stage0/visual_segments.json --out /tmp/sel.json` writes a scaffold.
  - `select-shots --visual-segments ... --out /tmp/sel.json --validate` reports counts.

### Task 1.3 — Add tests for `stage2_select_shots`

- [ ] **Status:** not started
- **Goal:** pure-function coverage at `tests/pipeline/test_stage2_select_shots.py`.
- **Test cases (minimum):**
  - `build_scaffold` produces one entry per visual segment, all `keep=false`.
  - `build_scaffold` preserves chronological order.
  - `validate_selection` accepts a valid `kept ≥ 1` selection.
  - `validate_selection` rejects unknown `shot_id`.
  - `validate_selection` rejects out-of-order entries.
  - `validate_selection` rejects all-`keep=false` selection (empty review).
- **Pattern reference:** look at `tests/pipeline/test_stage1_parse_subtitles.py` for argparse/CLI testing pattern; look at `tests/tools/test_prepare_voice_reference.py` for dataclass-helper testing pattern.
- **Done when:** new tests pass; total pytest count grows by the number of new tests.

### Task 1.4 — Add `tmp/step_02_select_shots.py` harness

- [ ] **Status:** not started
- **Goal:** one-click VSCode entry to run Stage 2 against the active movie config.
- **Pattern:** copy the shape of `tmp/step_00_index_visuals.py` exactly. Read `_common.py` Paths, ensure the stage2 dir exists, dispatch to `stage2_select_shots.main()` via `sys.argv` injection or by calling the module's pure helpers directly.
- **Add to `tmp/_common.py` Paths:**
  - `stage2_dir = work_dir / "stage2"`
  - `selected_shots = stage2_dir / "selected_shots.json"`
  - Update `ensure_stage_dirs` to include `stage2_dir`.
- **Done when:** `python tmp/step_02_select_shots.py` produces a scaffold for the active movie at `tmp/work/<slug>/stage2/selected_shots.json`.

### Task 1.5 — Run Stage 2 manually on `sha_po_lang_2`

- [ ] **Status:** not started
- **Goal:** validate the v1 manual workflow on a real movie.
- **Steps:**
  1. Ensure `tmp/configs/current_movie.toml` points at `sha_po_lang_2`.
  2. Run `tmp/step_02_select_shots.py` to scaffold.
  3. Open `tmp/work/sha_po_lang_2/stage2/selected_shots.json` in VSCode.
  4. Open the source movie in DaVinci/VLC for visual reference.
  5. Flip `keep=true` on ~30–60 shots that look high-information (hook, climax, twist, key character beats).
  6. Run the validator (`--validate` mode).
  7. Note any pain points in **Open Design Questions**.
- **Done when:** validator passes on a real human-edited file; any process pain points captured.

---

## Phase 2 — Stage 3: Rough Cut Assembly

**Why next:** once Stage 2 outputs exist, Stage 3 produces the first *visual artifact* of the new pipeline — a rough cut MP4 you can actually watch. This is the earliest checkpoint where the architecture starts paying off.

### Task 2.1 — Define rough-cut manifest schema

- [ ] **Status:** not started
- **Goal:** schema for `rough_cut.json` that travels with `rough_cut.mp4`.
- **Schema:**
  ```json
  [
    {
      "beat_index": 1,
      "shot_ids": ["visual:042", "visual:043", "visual:045"],
      "start_s": 0.0,
      "end_s": 38.4,
      "total_duration_s": 38.4
    }
  ]
  ```
  - `start_s`/`end_s` are positions inside `rough_cut.mp4`, not source-movie timestamps.
  - `shot_ids` references the Stage 2 selection.
  - One beat is 30–60s of micro-shots that will eventually share one narration line.
- **Done when:** schema added to `docs/TECHNICAL.md §6`.

### Task 2.2 — Pick the beat-grouping algorithm

- [ ] **Status:** not started
- **Goal:** decide how Stage 3 groups consecutive selected shots into beats.
- **Default proposal (start here):** greedy — accumulate shots until adding the next would push beat duration over `BEAT_MAX_S = 60.0`. If a single shot exceeds the max, it becomes its own beat.
- **Optional refinement (decide after first run):** prefer cutting beats at points where (a) consecutive Stage 0 segment summaries diverge significantly, or (b) there's a long subtitle gap suggesting a scene break.
- **Constants to define:** `BEAT_TARGET_S = 45.0`, `BEAT_MIN_S = 20.0`, `BEAT_MAX_S = 60.0`.
- **Done when:** the algorithm is documented inline in `stage3_assemble_rough_cut.py` and the values picked are recorded here.

### Task 2.3 — Build `app/pipeline/stage3_assemble_rough_cut.py`

- [ ] **Status:** not started
- **Goal:** working CLI that emits `rough_cut.mp4` and `rough_cut.json`.
- **CLI:** `stage3_assemble_rough_cut.py --movie PATH --selected-shots PATH --out-dir DIR [--encoder auto|nvenc|libx264]`
- **Behavior:**
  1. Load `selected_shots.json`, filter to `keep=true`, sort chronologically.
  2. Group into beats per Task 2.2.
  3. For each kept shot: extract a re-encoded clip from the source movie via ffmpeg (use `app.pipeline.common.video_encoder.resolve_encoder`).
  4. Concatenate the clips into `rough_cut.mp4` using ffmpeg concat demuxer.
  5. Compute beat positions in the concatenated output and write `rough_cut.json`.
- **Code structure:**
  - Reuse `app.pipeline.common.video_encoder` for encoder selection.
  - Reuse `app.pipeline.common.script_contract.timestamp_to_seconds` for timestamp parsing.
  - Reuse `app.pipeline.common.json_io.dump_json`.
  - Look at the legacy `stage5_video_processor.py` in git history (`git show <commit>:app/pipeline/stage5_video_processor.py`) for the ffmpeg extract-and-concat pattern — copy the technique, drop the anchor coupling.
- **Done when:**
  - `assemble-rough-cut --movie ... --selected-shots ... --out-dir ...` produces a watchable `rough_cut.mp4` plus a manifest.
  - Entry point registered in `pyproject.toml` as `assemble-rough-cut`.
  - Documented in `docs/TECHNICAL.md §4` and §7.

### Task 2.4 — Tests for Stage 3

- [ ] **Status:** not started
- **Goal:** `tests/pipeline/test_stage3_assemble_rough_cut.py` with mocked ffmpeg.
- **Test cases (minimum):**
  - `group_into_beats` honors `BEAT_MAX_S`.
  - `group_into_beats` produces single-shot beats when one shot is itself > max.
  - `compute_beat_positions` correctly accumulates `start_s`/`end_s` after concat.
  - The CLI flow runs end-to-end with `subprocess.run` monkey-patched (mirror the pattern in `tests/pipeline/test_stage7_finalize_video.py`).

### Task 2.5 — Add `tmp/step_03_assemble_rough_cut.py` harness

- [ ] **Status:** not started
- **Pattern:** copy `tmp/step_00_index_visuals.py` shape. Add `stage3_dir`, `rough_cut_video`, `rough_cut_manifest` to `_common.py` Paths.

### Task 2.6 — Run Stage 3 manually on `sha_po_lang_2`

- [ ] **Status:** not started
- **Done when:** `tmp/work/sha_po_lang_2/stage3/rough_cut.mp4` is watchable end-to-end and the cuts feel chronologically coherent. Note timing or visual issues in **Open Design Questions**.

---

## Phase 3 — Stage 5: Voiceover Generation (TTS)

**Why before Stage 4:** narration writing is faster to iterate when the writer can hear the result. Stage 5 has to be ready before manual narration-writing is practical at scale. Stage 5 can be developed against a hand-written stub `narration.json` (3–5 beats) before Stage 4 exists.

### Task 3.1 — Recover the TTS engine code from git history

- [ ] **Status:** not started
- **Goal:** identify the commit that last had `app/pipeline/stage3_generate_audio.py` with the working Qwen3-TTS Voice Clone integration.
- **Steps:**
  1. `git log --all --oneline -- app/pipeline/stage3_generate_audio.py` to find the deletion commit and its parent.
  2. `git show <parent-commit>:app/pipeline/stage3_generate_audio.py > /tmp/stage3_legacy.py` to extract a reference copy.
  3. Read the file, identify the boundary between **engine code** (model loading, generation, audio normalization, concat) and **driver code** (anchored-script parsing, anchor/chunk dataclasses).
- **Done when:** a reference copy exists at `/tmp/stage3_legacy.py` and you've noted the line ranges that map to engine vs driver.

### Task 3.2 — Define the voiceover manifest schema (preserve field names)

- [ ] **Status:** not started
- **Schema:**
  ```json
  [
    { "index": 1, "text": "narration line for beat 1", "audio_start_s": 0.0, "audio_end_s": 4.82 }
  ]
  ```
  - **Field names `index`, `text`, `audio_start_s`, `audio_end_s` are preserved verbatim from the legacy contract** so the surviving `stage4_align_subtitles.py` consumer keeps working without modification.
- **Done when:** schema added to `docs/TECHNICAL.md §6`.

### Task 3.3 — Build `app/pipeline/stage5_generate_audio.py`

- [ ] **Status:** not started
- **Goal:** TTS each beat's narration, concatenate, emit `voiceover.mp3` + manifest.
- **CLI:** `stage5_generate_audio.py --narration PATH --style PATH --out-dir DIR [--ref-audio PATH] [--ref-text PATH] [--tag NAME]`
- **Behavior:**
  1. Load `narration.json` (list of `{beat_index, text}`).
  2. Resolve voice reference: default to `styles/voice-assets/<style-stem>/reference/clone_reference.{mp3,txt}`; allow `--ref-audio` / `--ref-text` overrides.
  3. For each beat: TTS the text, capture the resulting audio duration.
  4. Concatenate into one MP3, loudness-normalize.
  5. Write the manifest with real measured `audio_start_s`/`audio_end_s` per beat.
  6. Output filenames: `voiceover_<tag>.mp3` and `voiceover_<tag>.manifest.json` (default `tag` = style stem).
- **Engine reuse:** copy the engine portion of `/tmp/stage3_legacy.py` (Task 3.1) into the new file. Replace the anchored-chunk parser with a simple JSON load. The Qwen3 model loading, generation API, and concat logic should be reusable verbatim.
- **Done when:**
  - Entry point `generate-audio` registered.
  - Running it with a 3-beat hand-written `narration.json` produces a watchable MP3 plus a manifest with sensible durations (~6.74 chars/sec around `REAL_TTS_CPS`).

### Task 3.4 — Tests for Stage 5

- [ ] **Status:** not started
- **Approach:** mock the TTS model so tests don't hit the real Qwen3 weights. Verify the manifest computes start/end correctly given mocked per-beat durations, and that file-naming follows the `--tag` rule.

### Task 3.5 — Add `tmp/step_05_generate_audio.py` harness

- [ ] **Status:** not started
- **Pattern:** mirror `tmp/step_00_index_visuals.py`. Add `stage5_dir`, `narration`, `voiceover`, `voiceover_manifest` paths to `_common.py`.

---

## Phase 4 — Stage 4: Narration Writing (manual v1)

**Why now:** Stage 5 exists, so the writer can hear results within a minute of pasting LLM output back.

### Task 4.1 — Define narration schema and build the prompt assembler

- [ ] **Status:** not started
- **Schema:**
  ```json
  [
    { "beat_index": 1, "text": "narration line for this beat" }
  ]
  ```
- **Prompt assembler outputs a single text file** (`stage4/narration_prompt.txt`) containing:
  1. The chosen style file's content (verbatim, e.g. `styles/niu-shu.md`).
  2. The optional `synopsis.md` for plot/cast context.
  3. For each beat: beat index, total duration, micro-shot summaries, surrounding subtitle context (subtitles whose timestamps fall inside the beat's source-shot ranges).
  4. A char-count target per beat: `target_chars = beat.total_duration_s × REAL_TTS_CPS`.
  5. The expected reply format (a JSON list matching the narration schema).
- **CLI:** `stage4_write_narration.py --rough-cut-manifest PATH --visual-segments PATH --subtitles-json PATH --style PATH [--synopsis PATH] --out-dir DIR [--validate]`
- **Two-mode behavior (mirror Stage 2):**
  - Without `--validate`: emit `narration_prompt.txt` and create an empty `narration.json` placeholder.
  - With `--validate`: read `narration.json`, check that every beat has text, that every text fits its `target_chars × 1.10` budget, that beat indices match the rough-cut manifest. Print pass/fail summary.

### Task 4.2 — Build `app/pipeline/stage4_write_narration.py`

- [ ] **Status:** not started
- **Steps:**
  1. Pure helpers: `build_prompt(beats, visual_segments, subtitles, style_text, synopsis_text)`, `validate_narration(narration, beats, chars_per_second)`.
  2. CLI dispatch.
  3. Use `REAL_TTS_CPS` from `script_contract.py`.

### Task 4.3 — Tests for Stage 4

- [ ] **Status:** not started
- **Test cases:**
  - Prompt includes every beat with the right shot summaries and subtitle context.
  - Char-count target uses `REAL_TTS_CPS`.
  - Validator passes a clean narration.
  - Validator rejects missing-beat narration.
  - Validator rejects over-budget narration text.

### Task 4.4 — Add `tmp/step_04_write_narration.py` harness and run it

- [ ] **Status:** not started
- **Done when:** running on `sha_po_lang_2` produces a `narration_prompt.txt`, you paste it into Gemini 3 Pro, paste reply into `narration.json`, and the validator passes.

### Task 4.5 — Style file refresh

- [ ] **Status:** not started
- **Goal:** rewrite `styles/niu-shu.md` and `styles/first-person-pov.md` to remove inert references to the dead `[ANCHOR]` format. The new style contract is "voice/tone/perspective + per-beat character budget", no anchor mechanics.
- **Notes:**
  - Keep voice/tone/perspective sections verbatim.
  - Replace anchor-budget formula with the per-beat budget formula from Task 4.1.
  - Add a one-line note at the top explaining the file's role in the new pipeline.
- **Done when:** both files are clean of anchor terminology and the Stage 4 prompt assembler embeds them verbatim without errors.

---

## Phase 5 — Stage 6: Visual Fitting

**The keystone of the new architecture.** This is where the pipeline finally bridges the audio/video duration mismatch.

### Task 5.1 — Pick the fitting strategy

- [ ] **Status:** not started
- **Default strategy (start here):**
  - For each beat: compare TTS duration (from voiceover manifest) to rough-cut beat duration.
  - **TTS shorter than video:** trim from the *tail* of the *least-important* micro-shot. v1 "least important" heuristic = the last micro-shot in the beat.
  - **TTS longer than video:** hold on the last micro-shot's last frame for the overrun. v1 fallback only — note in Open Design Questions if this looks bad.
  - **TTS within ±0.5s of video:** no trim, take the rough cut as-is.
- **Future refinements:** loop the most-static shot, distribute trim proportionally across all shots, insert B-roll cutaway from unused selected shots.

### Task 5.2 — Build `app/pipeline/stage6_fit_visuals.py`

- [ ] **Status:** not started
- **CLI:** `stage6_fit_visuals.py --rough-cut-manifest PATH --rough-cut-video PATH --voiceover-manifest PATH --out-dir DIR`
- **Output:** `fitted/beat_NNN.mp4` per beat, sized to match each beat's TTS duration.
- **Code structure:**
  - Pure helper: `compute_fit_plan(beats, voiceover_manifest)` returns a list of `{beat_index, source_start_s, source_end_s, hold_extra_s}` operations.
  - ffmpeg dispatch: extract the trimmed slice; if `hold_extra_s > 0`, append a frozen tail using `tpad=stop_mode=clone:stop_duration=...`.

### Task 5.3 — Tests for Stage 6

- [ ] **Status:** not started
- **Test cases:**
  - `compute_fit_plan` produces exact trims when TTS < video.
  - `compute_fit_plan` produces a hold operation when TTS > video.
  - `compute_fit_plan` is a no-op when within tolerance.
  - End-to-end CLI test with mocked ffmpeg.

### Task 5.4 — Add `tmp/step_06_fit_visuals.py` harness and run it

- [ ] **Status:** not started
- **Done when:** every fitted clip's duration matches its voiceover-manifest duration to within 0.1s (verify with `ffprobe`).

---

## Phase 6 — Rename `stage4_align_subtitles` → `stage7_align_subtitles`

**Why now:** Stage 8 (next phase) needs to import this module under its new name. Doing the rename in isolation makes the import line in Stage 8 clean.

### Task 6.1 — Move the file and update imports

- [ ] **Status:** not started
- **Steps:**
  1. `git mv app/pipeline/stage4_align_subtitles.py app/pipeline/stage7_align_subtitles.py`.
  2. `git mv tests/pipeline/test_stage4_align_subtitles.py tests/pipeline/test_stage7_align_subtitles.py`.
  3. Update the import in the moved test file: `from app.pipeline.stage7_align_subtitles import ...`.
  4. Update entry point in `pyproject.toml`: `align-subtitles = "app.pipeline.stage7_align_subtitles:main"`.
  5. Update any remaining doc references to the old path.
  6. Run pytest — confirm no regressions.
- **Done when:** pytest still passes 73/73 (or 73 + new tests from earlier phases).

---

## Phase 7 — Stage 8: Draft Render

### Task 7.1 — Build `app/pipeline/stage8_render_video.py`

- [ ] **Status:** not started
- **CLI:** `stage8_render_video.py --fitted-dir DIR --voiceover PATH --subtitle-manifest PATH --out PATH [--encoder auto|nvenc|libx264]`
- **Behavior:**
  1. Concat fitted beats in `beat_index` order via ffmpeg concat demuxer.
  2. Burn subtitles from `subtitle_manifest.json` using libass (write a temporary `.ass` file from the manifest cues).
  3. Mux the voiceover MP3 onto the resulting video.
  4. Output: `review.mp4`.
- **Code reuse:** `app.pipeline.common.video_encoder.resolve_encoder`. Subtitle-burn pattern can be adapted from the legacy `stage6_render_video.py` in git history.

### Task 7.2 — Tests for Stage 8

- [ ] **Status:** not started
- **Pattern:** monkey-patch ffmpeg subprocess calls; verify the constructed command lines have the expected concat/filter/mux structure.

### Task 7.3 — Add `tmp/step_08_render_video.py` harness and run it

- [ ] **Status:** not started
- **Done when:** `tmp/work/sha_po_lang_2/stage8/review.mp4` plays end-to-end with audio + burned subs.

---

## Phase 8 — Rename `stage7_finalize_video` → `stage9_finalize_video`

### Task 8.1 — Move and update

- [ ] **Status:** not started
- **Steps:**
  1. `git mv app/pipeline/stage7_finalize_video.py app/pipeline/stage9_finalize_video.py`.
  2. `git mv tests/pipeline/test_stage7_finalize_video.py tests/pipeline/test_stage9_finalize_video.py`.
  3. Update imports in the moved test file.
  4. Update entry point in `pyproject.toml`: `finalize-video = "app.pipeline.stage9_finalize_video:main"`.
  5. Update remaining doc references.
  6. Run pytest.
- **Done when:** pytest still green.

---

## Phase 9 — End-to-End Validation on `sha_po_lang_2`

### Task 9.1 — Run the full pipeline

- [ ] **Status:** not started
- **Steps (in order):**
  1. Stage 0 outputs already exist in `tmp/work/sha_po_lang_2/stage0/`. Skip.
  2. `step_01_parse_subtitles.py` → `stage1/subtitles.{txt,json}`.
  3. `step_02_select_shots.py` (scaffold + manual flip + validate).
  4. `step_03_assemble_rough_cut.py` → `stage3/rough_cut.{mp4,json}`.
  5. `step_04_write_narration.py` (prompt + paste-paste + validate).
  6. `step_05_generate_audio.py` → `stage5/voiceover_*.{mp3,manifest.json}`.
  7. `step_06_fit_visuals.py` → `stage6/fitted/beat_*.mp4`.
  8. `step_07_align_subtitles.py` → `stage7/subtitle_manifest.json`.
  9. `step_08_render_video.py` → `stage8/review.mp4`.
  10. `step_09_finalize_video.py` → `stage9/final_video.mp4`.

### Task 9.2 — Quality check

- [ ] **Status:** not started
- **Check the final video for:**
  - [ ] no audio overruns (narration finishes before / with the visual)
  - [ ] no static-slideshow feel (visuals change every few seconds, not held for 30+s)
  - [ ] subtitles align to actual speech pauses
  - [ ] no obvious narration/visual mismatch (narration describing a beat while a different beat plays)
  - [ ] full plot arc covered
  - [ ] style rules visible (Style A: deadpan/sarcastic/archetype names)
- **Capture findings:** any failures here become new tasks under Open Design Questions.

### Task 9.3 — `tmp/run_all.py` orchestrator

- [ ] **Status:** not started
- **Goal:** restore one-command end-to-end after Phase 9 confirms each step works individually.
- **Pattern:** mirror the pre-cleanup `run_all.py` (recoverable from git history) — sequential dispatch, skip-if-output-exists, stop-and-prompt on manual stages (2 and 4).

---

## Open Design Questions

Tracked here so they don't get lost between phases.

- **Beat boundary heuristic.** Stage 3's greedy duration grouper is the v1 plan. Decide whether to layer in semantic boundaries (subtitle gaps, summary divergence) after seeing one rough cut.
- **Stage 6 overrun fallback.** Hold-last-frame is the v1 plan. May look static. B-roll cutaway from unused selected shots is the obvious refinement; loop-static-shot is another. Pick after seeing real overruns.
- **Stage 4 v2 (auto narration via direct LLM call).** Defer until manual paste-paste is stable across 2–3 movies.
- **Stage 2 v2 (auto shot scoring).** Defer until at least one movie's worth of human-labeled `selected_shots.json` exists as ground truth.
- **`run_all.py` skip-if-exists semantics.** Manual stages (2, 4) need a "stop and prompt" mode rather than skip-if-exists, since they're never "done" without human input.
- **Renaming cost.** Phases 6 and 8 are pure renames. Could do them in one commit at the very end instead of mid-pipeline. Trade-off: cross-stage imports during construction would point at the new names earlier vs. one big rename diff later. Current plan keeps them mid-pipeline so each new module's imports are correct from day one.

---

## Movies in flight

- `movies/杀破狼2/` — primary current test movie (action). Stage 0 outputs preserved at `tmp/work/sha_po_lang_2/stage0/visual_segments.json`.
- `movies/呪術回戦0/` — Jujutsu Kaisen 0, secondary test movie.
