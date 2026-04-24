# Pipeline TODO

Working notes for the Jujutsu integration test and everything that falls out of it. Tick items as you finish them; drop them when they stop being useful.

## Context

The original crash was root-caused in April 2026: Stage 0 (Gemini Fast) hallucinated visual segments with 9-hour end timestamps, Stage 4's "safe-boundary extension" was unbounded, and Stages 4/5 re-encoded with `libx264` on CPU. Combined, every clip was planned as a 34,000-second NVENC-less re-encode — WSL ran out of RAM mid-clip_044. Code fixes now landed:

- `validate_visual_segments()` at the Stage 0 trust boundary (clamps to movie duration, drops > 30s hallucinations).
- `--max-extension-seconds` cap on Stage 4 (default 30s).
- EOF clamp on every Stage 4 extraction.
- NVENC auto-detect with libx264 fallback across Stages 0/4/5.
- `-hwaccel cuda` decode on every source-movie input (~2x faster wallclock, ~10x less CPU load on the test machine).
- Stage 0 Gemini chunk extraction switched from `libx264 ultrafast` to `h264_nvenc p1`.
- Existing `tmp/e2e_jujutsu_5min/stage0/visual_segments.json` sanitised in place (1754 → 1572 segments, backup `.bak-preclean`).
- Harness simplified (588 → 299 lines) — README/STATUS generation dropped.

---

## P0 — Validate the fix before trusting it

- [ ] Delete `tmp/e2e_jujutsu_5min/stage4/` (still holds corrupt clips from the original crash).
- [ ] Re-run `tmp/run_stage2b_stage5_slice_harness.py post-grounding` and confirm:
  - Stage 4 startup line shows `encoder=h264_nvenc` and `max-extension=30.0s`.
  - No single clip exceeds ~50 MB.
  - `review_5min.mp4` plays and its duration matches the last `audio_end_s` in the voice manifest.
- [ ] Watch host CPU / RAM / VRAM during the run. Expected: CPU < 50%, RAM < 6 GB, VRAM ~2 GB. Investigate if anything spikes.
- [ ] Once 5 min is clean, rerun with `--target-seconds 600` for the 10-min target.

## P1 — Stage 2 automation

Goal: replace the copy-paste handoff with an automated writer+grounder pass that still pauses for human review.

Design:

- Add two functions in `app/pipeline/stage2_generate_script.py`:
  - `run_writer(prompt_text) -> beats_text` — sends the writer prompt to an LLM, returns narration beats.
  - `run_grounder(prompt_text) -> grounded_text` — sends the grounder prompt, returns the final scene-marked script.
- Backend: start with **Gemini 2.5 Pro** (you already have `google-genai` installed, and grounder prompts are 400+ KB so the 1M-token context helps). Keep Claude as a second option behind an `--llm-backend` flag.
- Add a `--pause-for-review / --auto-approve` switch to the harness. Pause mode prints a summary (first 5 beats or first 5 scenes + character coverage stats) and waits for `ENTER` before writing the output file. Auto mode writes immediately.
- When review is requested and the user types `r` instead of `ENTER`, the harness re-calls the LLM with a "revise, your previous draft had X problem" follow-up prompt. Skip this until the plain path works.
- Write the LLM response straight into `writer_beats.txt` / `grounded_script.txt`, then run `validate_script_input()` (already exists) before continuing. If validation fails, print the error and re-prompt once, then give up and leave the raw draft for manual fixing.

Steps:

- [ ] Add `google-generativeai` (if not already pulled by `google-genai`) and `anthropic` to `pyproject.toml`, then `pip install -e .`.
- [ ] Implement `run_writer()` + `run_grounder()` in `stage2_generate_script.py`. Both take `model_name` and `backend` arguments; defaults live in the module.
- [ ] Add CLI flags `--writer-model`, `--grounder-model`, `--llm-backend` to stage2's `main()`. Existing prompt-printing behaviour stays as the fallback (`--mode writer --print-only`).
- [ ] Update the harness:
  - `run_stage2_writer` and `run_stage2_grounder` call the new helpers instead of just writing prompt files.
  - New flag `--auto-approve` on the harness skips the review prompt.
  - `run_auto` chains through writer → review → grounder → review → stage 3 without re-invocation.
- [ ] Smoke-test with the existing Jujutsu writer prompt. Acceptance: one `auto` run produces a playable `review_5min.mp4` with at most two `ENTER` presses and no copy-paste.

Guardrails:

- Stage 2 output still goes to disk under `stage2/` with the same filenames. Downstream stages don't change.
- The raw LLM response is also saved as `writer_beats.raw.txt` / `grounded_script.raw.txt` before any post-processing, so you can always recover if a cleaner regex goes wrong.
- Add a test that feeds a canned LLM response into the writer/grounder helpers and asserts the output file passes `validate_script_input`.

## P2 — Speed-ups, sorted by impact

Rough wallclock savings on a single fresh 10-min review run on this machine. "Cold" = first run with nothing cached; "warm" = rerun reusing stage outputs that haven't changed.

### High impact (minutes saved)

- [ ] **Parallel Stage 0 Gemini chunk indexing** (~4-5 min cold). Currently 10-11 chunks run strictly serially — each one uploads, waits for Gemini to finish PROCESSING, infers, deletes. With `asyncio.gather` or a small `ThreadPoolExecutor(max_workers=4)` around `_index_chunk`, all chunks overlap network I/O and model latency. Cost: need to rate-limit against Gemini's per-minute quota (the free tier caps at 5-15 RPM; paid is higher). Implement behind a `--stage0-concurrency` flag defaulting to 4.
- [ ] **Stage 2 automation** (~10-15 min per run of human wait). See P1. This is "impact" in human time more than CPU time, but it's the biggest single wall-clock improvement for how you actually use the pipeline.
- [ ] **Stage 3 per-chunk audio cache** (~2-3 min on warm reruns). If you tweak one scene's narration and rerun, Stage 3 re-generates all 50 chunks. Hash each chunk's text + voice config, cache the `.wav` under `stage3/chunk_cache/<hash>.wav`, reuse when present. Only the concat + loudnorm has to run. Reruns that touch 1-3 chunks drop from ~3 min to ~10 s.

### Medium impact (tens of seconds to ~1 min saved)

- [ ] **Stage 3 TTS batching** (~30-60 s cold). Qwen3-TTS on a 4060 can process multiple chunks in one forward pass if the model's `generate_voice_clone` accepts batched input. Verify with a 2-chunk smoke test first; if it works, batch in groups of 4-8. If it doesn't, skip — model-dependent.
- [ ] **Stage 4 parallel extraction** (~30-60 s cold). With NVENC already in place each clip is sub-second; serial overhead is mostly ffmpeg startup. `ThreadPoolExecutor(max_workers=3)` around the scene loop brings total stage4 time below ~20 s for 50 clips. Important: the NVENC engine on the 4060 handles 3-4 concurrent 1080p sessions comfortably; don't push higher without measuring.
- [ ] **Skip Stage 5 re-encode on the hero path when stage4 output already matches target format** (~30-45 s cold). Stage 4 produces `libx264/nvenc` mp4s; Stage 5's `render_excerpt` re-encodes them again through the normalize filter. When `plan_primary_window` is a straight slice (no time offset into the clip) and the clip is already 1920×1080 30fps, use `-c:v copy` instead of re-encoding. Stage 5 would only need to re-encode for time-offset slices or aspect-ratio mismatches.
- [ ] **Reduce Stage 0 chunk size from 10 min to 5 min** (~flat wallclock, better parallelism ceiling). With parallel indexing in place, smaller chunks parallelise better and Gemini tends to hallucinate less on shorter inputs. Measure the dropped-segments ratio from `validate_visual_segments` diagnostics before and after.

### Low impact (< 30 s saved, or quality-of-life only)

- [ ] **Quieter ffmpeg logging off by default** — `-loglevel error` is already set; already fine.
- [ ] **Skip stage0 tmp chunk mp4s after upload** — saves a few GB of scratch disk but not wallclock. Currently cached for re-runs; keep that behaviour.
- [ ] **Use NVENC `p1` (fastest)** for all Stage 4/5 re-encodes instead of `p4`. Quality drops slightly; worth only if you ever feel encoder bound.
- [ ] **Cache Stage 0 visual_segments.json across runs of the same movie**. Already effectively cached because the harness skips Stage 0 when the file exists.

## P3 — Hardening / housekeeping

- [ ] Write `tests/pipeline/test_validate_visual_segments.py` with fixtures for end-past-EOF, duration > 30 s, inverted ranges, missing fields. Most load-bearing new helper; still has no dedicated test.
- [ ] Add a `.wslconfig` at `C:\Users\<you>\.wslconfig` with `memory=12GB swap=8GB processors=8` (tune to host). Independent of this bug but caps blast radius for future runaways. Requires `wsl --shutdown` then restart.
- [ ] Document the NVENC / hwaccel requirements in README (Windows NVIDIA driver + WSL CUDA userspace + ffmpeg with `--enable-nvenc`). Trivial for new contributors to miss.
- [ ] Gemini Fast vs Pro evaluation: run Stage 0 once with `--model gemini-3-pro-preview` against Jujutsu, compare validator diagnostics (`kept`, `dropped_past_eof`, `dropped_too_long`). Switch default to Pro only if Pro drops < 1 % and Fast drops > 5 %.
- [ ] Consolidate `tmp/e2e_jujutsu_*` directories after the 10-min run is confirmed green. Six of them exist; only the latest-good one is useful.
- [ ] Rename the harness once Stage 2 is automated — `run_stage2b_stage5_slice_harness.py` no longer reflects scope (it drives 0/2/3/4/5).

## Disk-space note (out of project scope but worth knowing)

The project itself is ~14 GB, dominated by `movies/呪術回戦0.mkv`. Nothing inside the repo is safe to delete beyond what you've already cleaned. The 30 GB you were seeing almost certainly lives in `~/.cache/` (37 GB on this machine — HuggingFace model weights, pip wheels, torch, conda pkgs). Candidates there:

- `~/.cache/huggingface/hub/` — TTS and VLM weights. Only safe to delete if you're willing to re-download on the next run.
- `~/.cache/pip/` — pip wheel cache. Safe to delete; slightly slower next `pip install`.
- `~/.cache/torch/` — torch hub checkpoints. Deletable, re-download on demand.

Run `du -sh ~/.cache/*` to see the split before deciding.

## Ground rules

- Keep this file short. Design discussions belong in `docs/HANDBOOK.md` or the master plan.
- Tick items off with a one-line result (e.g. "Pro kept 98% vs Fast's 90% — switched default").
- Delete obsolete items rather than crossing them out.
