# Pipeline TODO — Stage 4/5 crash follow-ups

Tracking items from the 2026-04-24 investigation into the Jujutsu 5-min integration-test crash (WSL OOM during Stage 4, bloated clip_039/042/044). Code fixes are landed; this file is for the validation and hardening work that comes next.

## Context (so this file stands alone)

Root cause: (a) Gemini returned hallucinated visual segments, one spanning 9.5 hours on a 1h45m movie; (b) Stage 4's safe-boundary extension was unbounded and picked the latest-ending overlapping segment; (c) Stages 4/5 re-encoded with `libx264` on CPU. Combined, every scene clip was planned as a 34,000-second re-encode and WSL OOM-killed the process mid-clip_044.

Fixed in code:

- `validate_visual_segments()` at the Stage 0 trust boundary (clamps to movie duration, drops bad ranges and > 30s hallucinations).
- `--max-extension-seconds` cap on Stage 4's safe-boundary extension (default 30s).
- EOF clamp on Stage 4 extraction.
- NVENC auto-detect with libx264 fallback (Stages 4 and 5).
- `--model` flag on Stage 0 to switch Gemini Fast ↔ Pro.
- Existing `tmp/e2e_jujutsu_5min/stage0/visual_segments.json` cleaned in place (1754 → 1572 segments, backup at `.bak-preclean`).

## P0 — Validate the fix before trusting it

- [ ] Blow away `tmp/e2e_jujutsu_5min/stage4/` before re-running — the clips dir still holds ~1.2 GB of corrupt extractions.
- [ ] Re-run `tmp/run_stage2b_stage5_slice_harness.py post-grounding` and confirm:
  - Stage 4 startup line shows `encoder=h264_nvenc` and `max-extension=30.0s`.
  - All 50 clips finish without any single clip exceeding ~50 MB.
  - Stage 5 completes and `review_5min.mp4` is playable.
  - `ffprobe` the output — duration should match the voiceover manifest's last `audio_end_s`.
- [ ] Monitor host resources during the re-run (Task Manager or `htop` in a second terminal). Expected: CPU ~30-50%, VRAM ~2 GB, system RAM < 6 GB. If any of those spikes, stop and investigate before scaling to 10 min.
- [ ] Once 5 min works, re-run with `--target-seconds 600` to confirm the 10-min target.

## P1 — Gemini Fast vs Pro evaluation

- [ ] Run Stage 0 once with `--model gemini-3-pro-preview` (or whatever the current Pro identifier is) against the same Jujutsu movie. Keep Fast output as baseline.
- [ ] Compare validator diagnostics between the two runs: segments kept, clamped_to_eof, dropped_past_eof, dropped_too_long.
- [ ] Decision rule: if Pro drops < 1% of segments and Fast drops > 5%, switch the harness default to Pro. Otherwise stay on Fast for cost.
- [ ] Sanity-check: diff a few Pro vs Fast summaries on the same time range — does Pro describe shots more accurately? (Eye check, 10-15 segments is enough.)

## P2 — Hardening

- [ ] Write `tests/pipeline/test_validate_visual_segments.py` with fixtures for: end past EOF, duration > 30s, inverted ranges, missing fields. This is the most load-bearing new helper and has no dedicated test.
- [ ] Add a `.wslconfig` under `C:\Users\<you>\.wslconfig` with `memory=12GB`, `swap=8GB`, `processors=8` (tune to your host). Independent of this bug, but protects against any future runaway. Requires `wsl --shutdown` + WSL restart to take effect.
- [ ] Stage 4 parallel extraction: use `concurrent.futures.ThreadPoolExecutor(max_workers=3)` around the scene loop so 2-3 ffmpeg invocations run at once. NVENC sessions on the 4060 handle 3-4 concurrent 1080p encodes comfortably. Skip until P0 passes.

## P3 — Nice-to-have cleanups

- [ ] Consolidate the several `tmp/e2e_jujutsu_*` directories once the 5-min and 10-min runs are validated. Currently 6 of them exist; only the latest-good one is useful.
- [ ] Consider moving `run_stage2b_stage5_slice_harness.py` into `scripts/` once Stage 2 has an automated backend — the harness name no longer reflects its actual scope (it now drives Stages 0, 2, 3, 4, 5).
- [ ] Document the NVENC requirement in README: Windows NVIDIA driver + WSL CUDA userspace + ffmpeg with `--enable-nvenc`. Trivial for new contributors to miss.

## Ground rules for updating this file

- Keep it short. If an item grows a design discussion, move that to `docs/HANDBOOK.md` or the master plan.
- Tick the box when done, leave a one-line result (e.g. "Pro kept 98% vs Fast's 90% — switched default").
- Delete items outright once they are obsolete, rather than accumulating history.
