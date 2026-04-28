# Stage 2 Architectural Overhaul — Plan

**Status:** in progress on `develop` branch.
**Owner:** Eric.
**Started:** 2026-04-27.

This document is the single source of truth while the overhaul is in flight.
When the overhaul lands, fold the "Target Architecture" and "Data Contracts"
sections into `HANDBOOK.md` / `TECHNICAL.md` and delete this file.

---

## 1. Why we're doing this

Today's pipeline is **narration-first**: the writer composes a script in a
vacuum (knowing only SRT + a flat visual timeline), the grounder hunts for
timestamps after the fact, and Stage 5 fights to make visuals fit the
narration's TTS duration. Every recurring problem traces back to step 1:

- B-roll feels random because it's chosen *after* the narration is fixed.
- Narration outlasts the natural shot length, requiring extension/freeze fills.
- Climax doesn't get more screen time because the writer can't see the visual budget.
- The same striking shot gets reused 3–4 times because nothing dedups across beats.

Real human commentary editors don't work this way. They identify visually
memorable anchors first, allocate screen time per anchor, then write narration
to fit those slots.

We are flipping the pipeline to match that pattern. The script is still
authored by an LLM, but it picks **visual anchors and narration in one pass**,
constrained by a chars-per-second budget so narration can never outlast the
chosen visuals.

---

## 2. Confirmed product decisions

| Decision | Value |
|---|---|
| Total review length | Movie-dependent, 4–12 min. `target_seconds` is a hint, not a constraint. |
| Dialog anchoring | Relaxed — related visuals OK for dialog beats. |
| Anchor count target | ~30–50 anchors per typical 5–7 min review. |
| Intensity tags | **Dropped.** The planner picks longer ranges for climax beats implicitly; an explicit tag is redundant once visuals and narration are co-planned. |
| Primary objective | **Story quality.** Narration must be fun, attractive, story-driven first; budget is a guardrail, not the goal. If a prompt change improves match rate but flattens narrative voice, it is the wrong change. |
| Manual editing | **Supported finishing step**, not a failure mode. The pipeline must export per-chunk video segments, per-chunk audio splits, and an edit manifest so Eric can recut in DaVinci/Premiere when the auto-render needs polish. Auto-render must still be near-final on its own. |

Open product questions live in §6 below.

## 2.1 Design principles for the planner-writer

These principles inform every Phase 2 prompt edit and every Phase 5 render
decision. If a future change violates one of them, push back rather than
implement.

1. **Style rulebook is authority for voice.** The planner inherits its
   storytelling voice from `styles/<name>.md`. The prompt cites the style
   verbatim before introducing any visual budget logic.
2. **Narration is sacred. Trim video, not narration.** Phase 5 is allowed
   to trim visual frames to match audio (shot-aware). The pipeline never
   modifies narration text after the planner emits it, never trims it
   post-TTS, never speeds up audio.
3. **Default state: video > narration.** Plan with a conservative
   `chars_per_second` (5.0 for niu-shu — below the slowest measured TTS
   chunk). On average video has ~26% slack over narration; smart-trim
   uses that slack to find clean shot-aligned cuts.
4. **Pick visuals that serve the story, not stories that serve the visuals.**
   The visual segment list is a menu, not a quota. The planner is allowed
   to leave large portions of the source unselected.
5. **Match as much as possible at the auto-render level. Spill to manual
   editing only for polish.** The pipeline ships per-segment artifacts
   so the manual step is for color/transitions/captions, not for fixing
   audio-visual mismatch.
6. **Single-pass writer is the simpler architecture; two-pass is a pivot
   we keep ready.** If a JJK0 trial run reads mechanically (Phase 7),
   first try prompt iteration; only pivot architecture if prompts can't
   recover voice quality.

---

## 3. Target architecture

```
Stage 0  index visuals           UNCHANGED  (Gemini → visual_segments.json)
Stage 1  parse subtitles         UNCHANGED
Stage 2  planner-writer          REWRITE    (single LLM pass; replaces writer + grounder)
Stage 3  TTS voice clone         UNCHANGED logic, manifest schema updated
Stage 4  clip extraction         SIMPLIFIED (multi-range per anchor, drop B-roll cuts)
Stage 5  render                  SIMPLIFIED (hero loop, edge-guard extension, freeze for closing)
```

**Stage 2 input:**

- Style rulebook (`styles/<name>.md`)
- `visual_segments.json` from Stage 0
- Subtitle SRT
- Movie title, genre
- Optional `target_seconds` hint
- Calibrated `chars_per_second` for the chosen voice profile (constant in style file)

**Stage 2 output:** a single anchored script. Every spoken beat has an `[ANCHOR]`
marker that names one or more chronological source-movie ranges, and the
narration text below it is bounded by `sum(range_seconds) × chars_per_second`.

**Reused technology** (per Eric's constraint):

- Gemini for visual indexing — **kept**.
- LLM for Stage 2 — **kept**, just one call instead of two.
- Qwen3-TTS voice cloning — **kept** without modification.
- ffmpeg + NVENC encoding — **kept**.
- pytest layout under `tests/pipeline/` — **kept**.
- `tmp/step_*.py` per-stage harness — **kept** structure, files renamed/edited.

---

## 4. New data contracts

### 4.1 Script marker

Replaces `[SCENE ...]` and `[BROLL: ...]`.

```
[ANCHOR ranges="00:03:12.000-00:03:28.000, 00:04:01.000-00:04:08.000" characters="Yuta|Rika"]
narration text bounded by sum_of_range_seconds × chars_per_second
```

- `ranges` is one or more chronological `start-end` pairs, comma-separated.
- `characters` is optional, pipe-separated, used for downstream sanity checks
  and debug only (no fallback selection logic depends on it any more).
- Structural markers (`[TITLE]`, `[HOOK]`, `[ACT N - ...]`, `[CLOSING]`) are
  unchanged. The `[CLOSING]` block contains narration but no `[ANCHOR]` —
  it renders over a still keyframe.

### 4.2 Voice manifest (Stage 3 output, consumed by Stage 5)

```json
{
  "index": 1,
  "ranges": [["00:03:12.000", "00:03:28.000"], ["00:04:01.000", "00:04:08.000"]],
  "characters": ["Yuta", "Rika"],
  "text": "narration ...",
  "audio_start_s": 12.0,
  "audio_end_s": 26.5
}
```

Removed from old schema: `scene_start`, `scene_end`, `scene_source`,
`scene_confidence`, `scene_evidence`, `broll`. Added: `ranges`.

Closing chunks (no `[ANCHOR]`) emit `"ranges": []`.

### 4.3 Clip manifest (Stage 4 output, consumed by Stage 5)

```json
{
  "index": 1,
  "ranges": [
    {"start_s": 192.0, "end_s": 208.0, "clip_path": "clip_001_a.mp4",
     "pre_handle_s": 0.5, "extracted_duration_s": 17.0},
    {"start_s": 241.0, "end_s": 248.0, "clip_path": "clip_001_b.mp4",
     "pre_handle_s": 0.5, "extracted_duration_s": 8.0}
  ]
}
```

Same per-range metadata as today's single-range entries; just nested.

### 4.4 Output layout

```text
tmp/work/<movie_slug>/
  stage0/visual_segments.json
  stage1/subtitles.txt
  stage2/planner_prompt.txt          ← single prompt file
  stage2/anchored_script.txt         ← single LLM output file
  stage3/voiceover_<style>_voiceclone.mp3
  stage3/voiceover_<style>_voiceclone.manifest.json
  stage4/clips/clip_NNN_a.mp4 …
  stage4/keyframes/keyframe_NNN.jpg
  stage4/clip_manifest.json
  stage5/review.mp4                  ← auto-rendered draft
  stage5/segments/segment_NNN.mp4    ← per-chunk visuals (kept, not deleted)
  stage5/segments/segment_NNN.mp3    ← per-chunk audio split from voiceover
  stage5/edit_manifest.json          ← human-editable timing + source ranges
```

`stage5/segments/` and `stage5/edit_manifest.json` are the **manual-editing
resources**. They let Eric reopen any chunk, swap clips, extend ranges, or
re-record narration in DaVinci/Premiere without re-running the pipeline.
The auto-render stays the primary output; manual editing only fixes
remaining mismatches.

`writer_prompt.txt`, `writer_beats.txt`, `grounder_prompt.txt`,
`grounded_script.txt` are **deleted** — they belong to the old two-pass design.

---

## 5. Phased plan

Each phase ships independently, has its own acceptance criteria, and leaves
the codebase in a runnable state. Tick `[x]` as work lands.

### Phase 0 — Calibration & guardrails (no app code)

- [x] Measure `chars_per_second` for niu-shu voice profile from existing
  Stage 3 outputs. Result: mean **6.74 cps** (median 6.76, stdev 0.58,
  min 5.17, max 8.04) across 57 chunks of `movies/呪術回戦0/voiceover_niu-shu_voiceclone.manifest.json`.
- [x] Add `TTS Budget` line to `styles/niu-shu.md` declaring planner
  budget = **6.0 cps** (slightly under measured mean for safety margin).
- [x] Confirm sample anchor count for JJK0:
  - Target review length: 7–10 min (per style mission). Use 8 min for sizing.
  - Total narration budget: 8 min × 6.0 cps × 60 s = 2,880 chars.
  - Anchor count target: 30–40 single-range anchors plus 3–5 multi-range
    anchors during the climax. Average ~12–16 s of screen time per anchor.

**Acceptance:** ✅ done. Calibration value committed to style file.

**Note:** The pre-existing line `~240-260 chars/min` in the style file is
stale by ~50% (real rate is ~400 cpm). Flagged in the file itself as
"will be reconciled in a later doc pass" — not blocking for Phase 1+.

### Phase 1 — Common contract & parser (small change)

- [x] In `app/pipeline/common/script_contract.py`:
  - Added `AnchorMarker` dataclass with `total_seconds` property.
  - Added `parse_range_list(text)` for the `ranges="..."` attribute payload.
  - Added `parse_anchor_marker(line)` — returns None for non-anchor lines,
    raises `ValueError` for malformed ones (missing ranges, zero/negative
    duration, out-of-order, overlapping). Back-to-back ranges
    (`end_i == start_{i+1}`) are allowed.
  - Marked legacy symbols (`SceneMarker`, `parse_scene_marker`,
    `format_scene_marker`, `parse_broll_ranges`, `LEGACY_SCENE_RE`,
    `BROLL_LINE_RE`, `estimate_scene_duration`,
    `overlapping_visual_segments`) with an `OVERHAUL: remove in Phase 6`
    header comment. Not deleted yet — Stages 3/4/5 still import them
    until their phases land.
- [x] Created `tests/pipeline/test_script_contract.py` with 11 tests
  covering single-range, multi-range, validation failures, and the
  back-to-back edge case. All pass.

**Acceptance:** ✅ done. 73/73 pipeline tests pass (62 existing + 11 new).

### Phase 2 — Stage 2 rewrite (largest single change)

- [x] In `app/pipeline/stage2_generate_script.py`:
  - Replaced `build_writer_prompt` + `build_grounding_prompt` with a single
    `build_planner_prompt(style, srt, visual_segments, target_seconds, synopsis)`.
  - Dropped the writer/grounder subcommands. CLI now has one mode.
  - Prompt teaches the model:
    1. `[ANCHOR ranges="A1-B1, A2-B2" characters="X|Y"]` schema with examples.
    2. The CPS budget formula and a 12s × 5.0 = 60-char worked example.
    3. Multi-range guidance ("prefer multi-range over wide single ranges to
       avoid spanning cuts").
    4. `[CLOSING]` has no anchor — narration over a still keyframe.
  - Optional `--synopsis` flag injects user-authored plot/cast/cultural
    context under `<<<SYNOPSIS_START>>>`. Falls back to a placeholder
    when absent.
- [x] Added `validate_anchored_script(text, cps)` to `script_contract.py`
  with three severity tiers: ok (≤1.0×), warn (≤1.10×, Stage 5 absorbs),
  fail (>1.10×, manual rewrite).
- [x] Added `read_style_chars_per_second(style_path)` — regex-extracts the
  CPS budget from style markdown so each style owns its pace.
- [x] Updated `tmp/step_02_generate_script.py`:
  - First run writes `planner_prompt.txt` (auto-includes
    `movies/<slug>/synopsis.md` when present).
  - Second run validates `anchored_script.txt` and prints per-chunk
    ok/warn/fail tally.
- [x] Updated `tmp/_common.py` paths: `planner_prompt`, `anchored_script`,
  `synopsis` replace the old four-file schema. Updated `tmp/run_all.py`
  to use the new placeholder.
- [x] Tests: 8 new in `test_script_contract.py` (validator + CPS reader),
  6 new in `test_stage2_generate_script.py` (planner prompt + synopsis
  + CLI). 83/83 pipeline tests pass.

**Acceptance:** ✅ code & tests done. Final acceptance — running
`step_02_generate_script.py` end-to-end against a real LLM and getting an
anchored_script that passes the validator — happens in Phase 7.

### Phase 3 — Stage 3 update (small)

- [x] In `app/pipeline/stage3_generate_audio.py`:
  - Replaced `Chunk.scene` with `Chunk.anchor` (Optional[AnchorMarker]).
    Added `ranges`, `characters`, `first_range_start` properties.
  - Rewrote `parse_script_chunks` to consume `[ANCHOR]`. Closing chunks
    accumulate text with `anchor=None`.
  - New manifest schema with `ranges` and `characters` per chunk;
    closing chunks emit `"ranges": []`.
- [x] Updated `tests/pipeline/test_stage3_generate_audio.py` — new tests
  cover single-range, multi-range, and closing-chunk manifest output.

**Acceptance:** ✅ done. 11 stage-3 tests pass.

### Phase 4 — Stage 4 update (medium)

- [x] In `app/pipeline/stage4_video_processor.py`:
  - Wholesale rewrite. Walks the anchored script via Stage 3's
    `parse_script_chunks`; each anchor's N ranges produce N clip files
    `clip_NNN_a.mp4 … clip_NNN_z.mp4` (then `aa`, `ab`, …).
  - Dropped the `[BROLL]` extraction path entirely.
  - **Asymmetric handles per Reviewer 3:** `pre_handle = 2.0s`,
    `post_handle = 4.0s`. Bigger post gives Stage 5 runway to absorb a
    slow TTS chunk.
  - Dropped `--visual-segments` flag — Stage 4 no longer needs visual
    boundaries (Stage 0's validator handles bounds; Stage 5's
    smart-trim consumes shot-boundary metadata).
  - New `clip_manifest.json` schema: nested ranges per anchor.
  - Keyframe extraction still per-anchor (closing chunks fall back to
    the most recent keyframe).
- [x] Rewrote `tests/pipeline/test_stage4_video_processor.py` —
  7 tests cover suffixing, asymmetric handles, EOF/start clamping,
  multi-range, keyframe placement, manifest shape.
- [x] `tmp/step_04_video_processor.py` updated (dropped `--visual-segments`).

**Acceptance:** ✅ done. 7 stage-4 tests pass; 3-range fixture produces 3
clip files with the nested manifest schema.

### Phase 4b — Stage 0 shot-boundary export (small, parallel)

- [x] In `app/pipeline/stage0_indexers/base.py`:
  `snap_to_shot_boundaries` now annotates each segment with
  `shot_boundaries_s: list[float]` — the cut times that fall strictly
  inside the segment's window. Empty list when no boundaries detected
  or the segment didn't snap.
- [x] Updated `tests/pipeline/test_stage0_visual_indexing.py` — added a
  test that confirms inner cuts are emitted, and adjusted the
  empty-boundaries test to expect the new annotation.

**Acceptance:** ✅ done. Every output of `snap_to_shot_boundaries` carries
the `shot_boundaries_s` field; downstream Stage 5 uses it for smart-trim.

### Phase 5 — Stage 5 update (medium)

The fundamental flow per chunk:

1. Get total anchor seconds from `entry.ranges` (sum of range durations).
2. Get audio duration from `audio_end_s - audio_start_s`.
3. If anchor ≥ audio: **smart-trim** the video to match audio exactly,
   preferring to drop time at shot boundaries (within ±5% grace, else
   mid-shot tail cut).
4. If anchor < audio: existing **scene-extension** fills the gap (rare
   when CPS=5.0 keeps anchor ≥ audio for ~99%+ of chunks).

Smart-trim algorithm (§Appendix A below):

- Multi-range anchor: drop entire ranges from the tail first
  (preserves all kept ranges fully). Within the kept ranges, apply
  single-range trim if still over budget.
- Single-range trim: collect shot boundaries inside the range; pick the
  largest cumulative duration ≤ audio_duration that ends at a boundary,
  with ±5% grace; if no boundary fits, mid-shot tail cut to exact
  audio duration.

Tasks:

- [ ] In `app/pipeline/stage5_render_video.py`:
  - Implement `plan_smart_trim(ranges, shot_boundaries, audio_duration)`
    returning the kept sub-ranges to render.
  - Hero loop: iterate kept sub-ranges, render each via existing render
    helper, concat in chronological order.
  - Keep `plan_scene_extension` as the edge guard for the rare case
    audio still overruns the full anchor.
  - Delete: `collect_manual_broll_paths`, `select_semantic_broll_segments`,
    `score_visual_segment`, `tokenize_text`, `text_similarity`, the
    `--visual-segments` CLI flag (replaced by reading `shot_boundaries_s`
    from `clip_manifest.json` which Stage 4 writes through from Stage 0).
  - Keep freeze fallback only for closing chunks.
  - **Stop deleting part files after concat.** Keep
    `stage5/segments/segment_NNN.mp4` on disk for manual editing.
  - Split the voiceover MP3 into per-chunk MP3s using audio_start_s /
    audio_end_s and write to `stage5/segments/segment_NNN.mp3`.
  - Write `stage5/edit_manifest.json` per §4.4.
  - Final summary: print per-stage tally:
    `N exact-fit, M shot-aligned trim, K mid-shot trim, L extension, P freeze`
    plus the manual-edit handoff hint.
- [ ] Update `tests/pipeline/test_stage5_render_video.py`:
  - Remove semantic B-roll tests.
  - Add tests for `plan_smart_trim`:
    * exact fit (no trim needed),
    * shot-aligned trim (drops tail at boundary),
    * mid-shot tail cut fallback,
    * multi-range drop-tail trim.
  - Add a test that `stage5/segments/segment_NNN.{mp4,mp3}` and
    `edit_manifest.json` exist after a run.

**Acceptance (code):** ✅ done. 10 stage-5 tests pass; per-chunk descriptor
prints `exact / shot-aligned-tail / mid-shot-tail / extension-needed /
freeze` per chunk plus a final tally line. **Final acceptance** (mid-shot
cuts <5% on JJK0) is gated on Phase 7 trial.

**Status of Phase 5 deliverables:**

- [x] `plan_smart_trim` with shot-aware tail snap (latest boundary within
  ±5% grace; mid-shot fallback when no boundary qualifies).
- [x] Hero loop iterates kept sub-ranges, renders each from the matching
  Stage-4 clip file with the right offset.
- [x] Deleted: `plan_primary_window`, `plan_scene_extension`,
  `select_semantic_broll_segments`, `score_visual_segment`,
  `tokenize_text`, `text_similarity`, `collect_manual_broll_paths`.
  `--video` flag dropped (no longer reads source movie).
- [x] `stage5/segments/segment_NNN.mp4` kept on disk; per-chunk MP3
  split via `split_voiceover_to_segment`.
- [x] `stage5/edit_manifest.json` written with one entry per chunk:
  `{index, ranges, characters, narration, audio_start_s, audio_end_s,
  segment_video, segment_audio}`.
- [x] Closing chunks render still keyframe (last_anchor_index fallback).
- [x] Final summary prints fallback tally.
- [x] `tmp/step_05_render_video.py` updated (dropped `--video`,
  `--visual-segments` is now optional).

#### Appendix A — `plan_smart_trim` reference behaviour

```
Input:
  ranges = [(start_s, end_s)] (one or more, chronological, non-overlapping)
  shot_boundaries = [b1, b2, ...] (absolute seconds in source movie, sorted)
  audio_duration_s

Output:
  kept_ranges = [(start_s, end_s)] subset/trim of input ranges,
  trim_kind = "exact" | "shot-aligned" | "mid-shot"

Pseudocode:
  total = sum(end_s - start_s for ranges)
  if abs(total - audio_duration_s) <= 0.05 * audio_duration_s:
      return ranges, "exact"
  if total < audio_duration_s:
      return ranges, "exact"  # caller falls through to scene-extension

  # We have slack; trim from the tail.
  excess = total - audio_duration_s
  # 1. Try dropping whole tail ranges.
  while ranges and (ranges[-1].duration <= excess + grace):
      excess -= ranges[-1].duration
      ranges.pop()
  if excess <= 0.05 * audio_duration_s:
      return ranges, "shot-aligned"

  # 2. Trim the (now last) range. Find a shot boundary inside it that
  # gives the right cumulative duration.
  last = ranges[-1]
  candidate_ends = [b for b in shot_boundaries if last.start_s < b < last.end_s]
  candidate_ends.append(last.end_s - excess)  # mid-shot cut as fallback
  best = pick the latest candidate <= last.end_s - excess + 0.05*audio_duration
  if best is at a shot boundary: kind = "shot-aligned"
  else: kind = "mid-shot"
  ranges[-1] = (last.start_s, best)
  return ranges, kind
```

### Phase 6 — Cleanup & docs (partial — code cleanup done; doc rewrites pending)

- [x] Deleted from `script_contract.py`: `LEGACY_SCENE_RE`, `BROLL_LINE_RE`,
  `SceneMarker`, `parse_scene_marker`, `format_scene_marker`,
  `parse_broll_ranges`, `estimate_scene_duration`, `quote_attr`,
  `overlapping_visual_segments`, unused `Iterable` import.
- [x] `grep -rn "scene_start|scene_end|scene_source|broll" app/` returns no
  hits in production code. (Some manifest field names still mention
  `scene_*` historically in commit history but no live code references.)
- [ ] Rewrite `docs/HANDBOOK.md` Stage 2 + Stage 5 sections (deferred
  until after Phase 7 trial confirms architecture works in practice).
- [ ] Rewrite `docs/TECHNICAL.md` script-marker / voice-manifest /
  clip-manifest sections (same — defer to post-Phase 7).
- [ ] Update `tmp/README.md` to describe the new step files.
- [ ] Delete this `OVERHAUL_PLAN.md` once docs are reconciled.

### Phase 7 — End-to-end validation

- [ ] Fresh JJK0 run via `tmp/run_all.py`:
  - Stage 0 output reused if present.
  - Stage 2 yields ~30–50 anchors covering all 4 acts.
  - Stage 3/4/5 run without errors.
  - `review.mp4` plays end to end.
- [ ] Per-chunk descriptor inventory: `extension` < 5%, `freeze` < 1%
  outside closing.
- [ ] Subjective review: no shot repeats more than twice; climax visibly
  longer than setup.

**Acceptance:** a 5–10 min JJK0 review that you'd actually publish.

---

## 6. Open questions

1. **Calibration value for `chars_per_second`** — needs measurement, not a
   guess. Pull from a real Stage 3 output.
2. **Sparse-source policy** — when the movie has too few coherent anchors
   for a target length, options: (a) auto-shrink the review to match
   what the source affords (recommended), (b) fail loud, (c) reuse anchors.
   Decision: start with (a). The planner outputs whatever total length the
   source naturally supports, prints a clear notice, and proceeds.
3. **`[CLOSING]` budget** — should closing narration be budget-constrained
   against the keyframe duration? Probably not — closing usually <30s and
   TTS pacing is fine on a still.
4. **LLM over-budget recovery policy.** ✅ resolved 2026-04-27.
   Narration is sacred (§2.1 #2). The validator now uses two simple tiers:
   - chars ≤ 1.0 × budget: **ok**.
   - 1.0 < chars ≤ 1.10 × budget: **warn** — Stage 5 scene-extension absorbs.
   - chars > 1.10 × budget: **fail** — Eric rewrites that beat manually,
     no auto-trim, no re-prompt.
5. **Visual incoherence within a single range.** ✅ resolved 2026-04-27.
   Stage 0 will emit `shot_boundaries_s` per segment (Phase 4b). Stage 5
   uses them for shot-aware smart-trim. Planner is also instructed to
   prefer multi-range over wide single ranges so trims usually land at
   shot junctions naturally.
6. **Manual-editing handoff format.** The minimum is per-chunk MP4 + MP3
   + JSON manifest (planned in §4.4). NLE-native formats (DaVinci XML,
   Premiere XML, EDL) are nice-to-have but add real complexity. Decision:
   ship the JSON-based handoff for v1, evaluate XML export only after the
   first manual-editing session reveals friction.
7. **Single-pass vs two-pass pivot trigger.** §2.1 principle 5 says we
   pivot to two-pass if narrative voice is flat. What's the concrete
   trigger? Subjective taste during Phase 7 review. If Eric reads the
   first JJK0 output and it doesn't read like Uncle Niu, that is the
   pivot signal — no automated metric.

---

## 7. Progress log

Append entries here as phases land. Format: `YYYY-MM-DD — phase — note`.

- 2026-04-27 — overhaul plan drafted on `develop`.
- 2026-04-27 — Eric confirmed: story quality is primary; manual editing is supported finishing step; pipeline must export per-segment artifacts. Plan updated (§2, §2.1, §4.4, §5 Phase 5, §6 questions 4–7).
- 2026-04-27 — Phase 0 starting.
- 2026-04-27 — Phase 0 complete. Measured 6.74 cps mean ± 0.58 stdev over 57 JJK0 niu-shu chunks; committed `chars_per_second = 6.0` to `styles/niu-shu.md` as planner budget. Phase 1 starting.
- 2026-04-27 — Phase 1 complete. New `AnchorMarker` + `parse_anchor_marker` + `parse_range_list` in `script_contract.py`; new `tests/pipeline/test_script_contract.py` (11 tests); legacy scene/broll helpers marked for Phase 6 removal but kept. 73/73 pipeline tests pass. Pausing for Eric review before Phase 2.
- 2026-04-27 — Eric confirmed: CPS=5.0 (down from 6.0), narration is sacred (no auto-trim), smart-trim grace 5%, multi-range trim defers within-range trim. Stage 0 to emit shot boundaries (Phase 4b added). Plan §2.1 rewritten; Phase 5 redesigned around `plan_smart_trim`; Q4/Q5 resolved. Phase 2 starting.
- 2026-04-27 — Phase 2 partial: validator + CPS reader landed. New helpers in `script_contract.py` (`read_style_chars_per_second`, `AnchorValidation`, `ScriptValidation`, `validate_anchored_script`). 8 new tests, 81/81 pipeline tests pass. `styles/niu-shu.md` updated to CPS=5.0. Pausing before planner-prompt rewrite — Eric should sanity-check validator tier behaviour first.
- 2026-04-27 — Phase 2 complete. Single-pass `build_planner_prompt` replaces writer+grounder. Synopsis support landed (`movies/<slug>/synopsis.md` auto-included when present). `tmp/step_02_generate_script.py` rewritten — first run emits prompt, second run validates. `_common.py` paths updated (`planner_prompt`/`anchored_script`/`synopsis`). 83/83 tests pass. Phase 3 (Stage 3 manifest schema migration) next.
- 2026-04-27 — Three external code reviews surfaced: (1) tmp/step_03+04 grounded_script regression I'd shipped, (2) validator only checked budgets not structure (orphan narration silently dropped), (3) tail-trim cuts payoff frames, (4) static handles too small for TTS variance. Eric and I discussed; locked answers: include range-provenance check (J), drop original-audio retention (K dropped), no auto-retry loop (L), bigger asymmetric handles 2s/4s.
- 2026-04-27 — Fix-up turn shipped. Repaired tmp orchestration; strict structure validator (orphan/title/anchors/monotonic); range-provenance check ±1s/±5s; macro budget + SRT-vs-visual tip + scaled anchor count in prompt; float-safe ratio; smoke test for tmp wrappers. 95/95 tests pass.
- 2026-04-27 — Phases 3, 4, 4b, 5 shipped in one continuous turn. Stage 3 walks `[ANCHOR]` and emits `ranges`/`characters` manifest. Stage 4 cuts N clips per anchor with asymmetric pre=2s/post=4s handles, drops [BROLL] entirely, nested clip_manifest. Stage 0 emits `shot_boundaries_s` per segment. Stage 5 wholesale rewrite: smart-trim (shot-aware tail snap), per-chunk segment MP4+MP3 persisted, edit_manifest.json handoff, fallback tally. 101/101 tests pass.
- 2026-04-27 — Phase 6 partial: deleted unused legacy code (`SceneMarker`, `parse_scene_marker`, `parse_broll_ranges`, `format_scene_marker`, `overlapping_visual_segments`, `quote_attr`, `LEGACY_SCENE_RE`, `BROLL_LINE_RE`, etc.). Doc rewrites of HANDBOOK/TECHNICAL deferred to after Phase 7 trial. 101/101 tests still pass.

---

## 8. Working notes (scratch)

Free-form area for design jottings during the overhaul. Move stable
decisions out of here and into §3/§4 once they crystallize.

(empty)
