# Stage 2 multi-pass redesign

**Date:** 2026-05-15
**Status:** Draft — awaiting implementation plan
**Scope:** `app/pipeline/stage_2_build_prompt.py` + `workbench/step_2_build_prompt.py`
**Out of scope:** Stage 1 (visual indexing, subtitle parsing), Stage 3 (TTS), Stage 4 (editor cheatsheet), `styles/*.md`

## Problem

Stage 2 today produces a single ~320 KB story prompt (JK0 example: 1538 VISUAL + 932 SUBTITLE lines + style + synopsis). That prompt overflows DeepSeek-V3's 64K context, strains Qwen 2.5 Max's 128K, and exhibits context-rot symptoms on Gemini 2.5 Pro. Two observed consequences:

1. **Hallucination.** The LLM enriches narration with plot points absent from the timeline. The editor then has no footage to cut against the narration — irrecoverable sync breakage. (See `memory/hallucinated_plot_problem.md`.)
2. **Act-balance drift.** The current digest mode prompt asks for "30–50 beats in chronological order" — flat distribution. The climax (which `styles/niu-shu.md` §4.0 mandates as the longest act, 35–40% of script lines) is under-represented in the digest, so Pass 2 either under-delivers or invents to bridge the gap.

The two symptoms share a root cause: prompts are too big AND under-structured for the task.

## Goals

- Shrink each individual LLM prompt enough to escape context rot on typical 90–130 min movies.
- Make hallucination mechanically harder by enforcing scene coverage and providing a deterministic ref-validation pass.
- Preserve `styles/niu-shu.md`'s act-balance invariant (Act 3 > Act 2) by pre-shaping the digest, not by hoping Pass 2 fixes it.
- Keep the manual orchestration cost low: 3 LLM calls in the default path, up to 5 in a chunked mode for long movies.
- Cleanly separate the default 3-call path (Approach B) from the chunked 5-call path (Approach C) so the codebase doesn't become a tangle of conditionals.

## Non-goals

- Replacing the paste-into-web-LLM workflow with an API-driven loop. Each pass must still be a single prompt that fits comfortably in a chat box.
- Touching the style file. `styles/niu-shu.md` is the source of truth for voice and act balance; this redesign serves it, not the reverse.
- Auto-fixing hallucinated sentences in the script. Post-validation flags; humans decide.

## Pipeline shape (default path, 3 LLM calls)

```
Stage 1 (unchanged)
  ├─ visual_segments.json   (one entry per shot)
  └─ subtitles.txt

Stage 2
  ├─ Pass 0 → scene_markers.json         [LLM call 1, small prompt]
  │           outline + act-tags for every scene
  │
  ├─ Pass 1 → plot_digest.txt            [LLM call 2, anchored prompt]
  │           scene-structured, act-weighted beats with 镜头: visual:NNN refs
  │
  ├─ Pass 2 → script.txt                 [LLM call 3, today's digest mode]
  │           niu-shu-styled retelling with <refs> per sentence
  │
  └─ Post-validation (deterministic, no LLM)
              hallucination_report.json   — flags only, never mutates script.txt
```

## Pass 0 — Scene outline with act-tags

**Purpose:** produce the narrative scaffold that both Pass 1 and post-validation use as ground truth for scene boundaries and act weighting. This is the new call that prevents "entire stretches got skipped" failures.

**Input** (compact, ~30–50 KB total):
- Synopsis (unchanged).
- **Thin timeline view** — one line per visual_segment containing ONLY: `visual:NNN | start..end | characters | ocr_text`. The prose `summary` field is dropped here (it's the heaviest column; the LLM doesn't need it to identify scene boundaries — character continuity and OCR are enough). **Every visual_segment is still represented** — no shot is dropped or merged. The compression is purely schema-level.
- Subtitles (unchanged).

**Output schema** (`scene_markers.json`):
```json
{
  "character_glossary": [
    {"original_name": "乙骨忧太", "role": "protagonist", "first_seen_scene": "scene:01"},
    {"original_name": "祈本里香", "role": "antagonist_curse", "first_seen_scene": "scene:01"}
  ],
  "scenes": [
    {
      "id": "scene:01",
      "label": "乙骨在校园偶遇里香",
      "act_tag": "SETUP",
      "visual_id_range": ["visual:001", "visual:031"],
      "time_range": ["00:00:01.201", "00:03:42.500"],
      "hook": "孤独高中生第一次发现自己被诅咒纠缠"
    }
  ]
}
```

The `character_glossary` is the single source of truth for character names across all downstream passes. Chunked-mode Pass 1 sub-calls each inject the full glossary so names don't drift. Pass 2 also inherits it (today it has to re-derive names from synopsis).

**Act-tags** (six values, mapped to niu-shu §4.0 + §13):
- `HOOK` — opening shock/premise/thesis scenes (~3–5% of runtime)
- `SETUP` — world, characters, conflict introduction (~15–20%)
- `ESCALATION` — pressure, traps, reversals (~25–30%)
- `CLIMAX` — decisive confrontation (~35–40%, the heaviest)
- `RESOLUTION` — ending, cost, aftermath (~10–15%)
- `CLOSING` — final button (~2–4%)

**Hard rules in the Pass 0 prompt:**
- Every visual_segment must fall inside exactly one scene's `visual_id_range` — no gaps, no overlaps.
- 15–25 scenes total. Fewer for short movies, more for epics.
- Exactly one scene tagged `HOOK` (the strongest opening candidate, not necessarily the first scene).
- At least 3 scenes tagged `CLIMAX`. This is the safeguard for the act-balance invariant.
- `act_tag` distribution should roughly match niu-shu §4.0 by runtime percentage.

**Failure recovery:** if the LLM violates the gap/overlap rule, a deterministic Python check in stage 2 surfaces the violation before Pass 1 runs. The user re-runs Pass 0 with a corrective hint.

## Pass 1 — Scene-anchored, act-weighted digest

**Two modes, same output schema** (`plot_digest.txt` — compatible with today's downstream):

### Mode "single" (default, used for movies that fit in one call)

**Input:**
- Synopsis.
- Full timeline (unchanged from today — visual_segments WITH summaries + subtitles).
- `scene_markers.json` from Pass 0, inlined into the prompt as section headers.

**Prompt structure:**
```
# Source: scene structure (from Pass 0)
[Inlined scene markers with act-tags]

# Source: full timeline
[Today's interleaved VISUAL + SUBTITLE lines]

# Task: write a digest organized BY SCENE
For each scene from Pass 0:
  - Write {N} detailed beats — N depends on the scene's act_tag
  - Every beat MUST cite 镜头: visual:NNN refs from that scene's visual_id_range
  - You may not skip a scene
  - You may not invent beats outside a scene's visual_id_range
```

**Strict per-tag beat targets** (the safeguard you requested):

| `act_tag` | Beats per scene |
|---|---|
| `HOOK` | 1–2 |
| `SETUP` | 1–2 (compress aggressively per niu-shu §4.2) |
| `ESCALATION` | 2–3 |
| `CLIMAX` | **4–6** (linger per niu-shu §4.1) |
| `RESOLUTION` | 2–3 |
| `CLOSING` | 1 |

The total beat budget pre-shapes the digest so the climax already dominates by the time Pass 2 receives it.

### Mode "chunked" (long movies, opt-in via config)

When `digest_mode = "chunked"` in `current_movie.toml`:

**Slicing strategy:** three Pass 1 sub-calls (total pipeline = 5 LLM calls, matches budget):
- Call 1a: `HOOK` + `SETUP` + `ESCALATION` scenes (the front-loaded buildup)
- Call 1b: `CLIMAX` scenes  ← isolated, gets the most detailed prompt and the most context room
- Call 1c: `RESOLUTION` + `CLOSING` scenes (the tail)

The `CLIMAX` call is deliberately isolated so it inherits maximum context budget — this is the act-balance invariant's most important call. Each call sees only its scenes' timeline slice plus the character glossary from `scene_markers.json` (shared across calls to prevent name drift).

**Outputs are concatenated into the same `plot_digest.txt` schema** as single mode. Pass 2 doesn't know or care which mode produced the digest.

### Architectural separation (the maintainability requirement)

| Concern | File / function |
|---|---|
| Pass 0 (shared) | `app/pipeline/stage_2/pass_0_outline.py` |
| Pass 1 single mode | `app/pipeline/stage_2/pass_1_digest_single.py` |
| Pass 1 chunked mode | `app/pipeline/stage_2/pass_1_digest_chunked.py` |
| Pass 2 (shared) | `app/pipeline/stage_2/pass_2_story.py` |
| Post-validation (shared) | `app/pipeline/stage_2/post_validate.py` |
| CLI orchestration | `app/pipeline/stage_2_build_prompt.py` (dispatches to the passes; no mode-specific logic) |

This introduces a new `app/pipeline/stage_2/` subpackage. Current `app/pipeline/` convention is flat (multiple `stage_1_*.py` files at top level), so this is a deliberate departure: the maintainability requirement (single dispatch point, no shared internals between B and C) is easier to enforce when the pass modules live in their own subpackage than as flat siblings to other stages.

The two Pass 1 implementations share an explicit interface (`build_digest_prompt(scene_markers, timeline, synopsis=None) -> str`) but have no shared internals. No conditional branches in shared code; mode selection happens at one dispatch point only. Pass 1 does not see the style file — that's Pass 2's domain.

**The today's `build_digest_prompt` and `build_story_prompt` functions are renamed/relocated, not deleted** — their content moves into the new module files. Existing tests stay green via re-exports during the transition.

## Pass 2 — Story writing (essentially unchanged)

`build_story_prompt` already accepts `digest_text`. Today's digest-mode flow continues to work. The only adjustment: the system prompt now mentions that the digest is scene-structured and act-weighted, so Pass 2 is invited to lean on the existing structure rather than re-imposing its own.

`styles/niu-shu.md` continues to drive voice. `styles/genres/<style>/<genre>.rules.md` (recently added) drives genre emphasis. Neither file is touched by this redesign.

## Post-validation (deterministic, flag-only)

**Trigger:** runs automatically after Pass 2's `script.txt` is saved.

**Checks per `<refs>` tag in script.txt:**
1. Every cited `visual:NNN` exists in `visual_segments.json`.
2. The cited IDs' time ranges overlap the cited beat's scene from `scene_markers.json` (catches "sentence claims to describe scene 5 but cites scene 12's footage").
3. The sentence has at least one `<refs>` tag (no naked sentences).

**Output:** `hallucination_report.json`:
```json
{
  "total_sentences": 423,
  "flagged": [
    {
      "line": 187,
      "sentence": "他回头看了一眼母亲的照片",
      "refs": ["visual:045"],
      "issue": "visual:045 has no overlap with claimed scene:07; nearest scene is :03"
    }
  ]
}
```

**The script file is never modified.** The report is for the human reviewer.

**Wiring:** post-validation runs as part of `workbench/step_3_generate_audio.py` (before TTS encoding), since stage 3 already parses the script and is the natural place to gate.

## Workflow impact

**Today's two-paste flow:**
1. Generate `digest_prompt.txt` → paste → save as `plot_digest.txt`
2. Generate `story_prompt.txt` → paste → save as `script.txt`

**New three-paste flow (default):**
1. Generate `outline_prompt.txt` → paste → save as `scene_markers.json`
2. Generate `digest_prompt.txt` → paste → save as `plot_digest.txt`
3. Generate `story_prompt.txt` → paste → save as `script.txt`

**Chunked mode (long-movie fallback, configured per movie):**
- Step 2 becomes 3 sub-pastes (front-buildup / climax / tail), each saved with a deterministic filename, then auto-concatenated into `plot_digest.txt`. Total pipeline = 5 LLM calls.

## Config changes (`current_movie.toml`)

New field under `[common]`:

```toml
digest_mode = "single"    # "single" (default, Approach B) or "chunked" (Approach C)
```

No other config changes. `target_seconds`, `style_path`, `genre` continue to mean what they mean today.

## File outputs (per movie, in `workbench/work/<slug>/stage2/`)

| File | Producer | Consumer |
|---|---|---|
| `outline_prompt.txt` | Stage 2a CLI | User pastes into LLM |
| `scene_markers.json` | User saves LLM reply | Stage 2b, Stage 2c, post-validation |
| `digest_prompt.txt` | Stage 2b CLI | User pastes into LLM |
| `plot_digest.txt` | User saves LLM reply | Stage 2c |
| `story_prompt.txt` | Stage 2c CLI | User pastes into LLM |
| `script.txt` | User saves LLM reply | Stage 3, post-validation |
| `hallucination_report.json` | Post-validation | Human reviewer |

## Testing

- **Unit tests per pass.** Each pass module has its own test file: prompt structure, schema validation (Pass 0 output, digest beat-count rules), idempotent re-runs.
- **Integration test for the full pipeline.** A small synthetic movie (5 visual segments, 3 subtitles) runs end-to-end through all three passes + post-validation.
- **Act-balance regression test.** Given a hand-crafted `scene_markers.json` with `CLIMAX` flagged on specific scenes, verify the generated digest prompt's beat-count instructions land in the CLIMAX block.
- **Hallucination-report fixtures.** A script with deliberately bad refs is fed into post-validation; the report must flag every planted issue and report no false positives on a clean script.

## Open implementation questions (to be resolved during writing-plans)

These are deferred to the implementation plan, not the design:

- Whether to keep `stage_2_build_prompt.py` as a thin dispatcher with subcommands (`stage-2 outline`, `stage-2 digest`, `stage-2 story`), or split into three CLI entry points. Either is compatible with this design.
- Whether Pass 0's "thin timeline" lives as a separate utility in `common/` or inside the Pass 0 module.
- Migration path for existing in-flight movies (sha_po_lang_2 has plot_digest.txt under the old schema). Likely: existing artifacts remain valid; only new runs use Pass 0.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Pass 0 mis-tags acts (e.g. labels a setup scene as CLIMAX) | The act-tag is an LLM judgment; user reviews `scene_markers.json` between Pass 0 and Pass 1 and can edit by hand before Pass 1 runs. |
| Single-mode Pass 1 still overflows on a 3-hour epic | `digest_mode = "chunked"` provides a clean fallback without code changes. |
| Post-validation false positives (a sentence whose beat genuinely needs a ref from an adjacent scene) | Flag-only behavior never mutates the script. Worst case: human ignores the flag. |
| Voice drift across chunked-mode digest calls | Character glossary file passed into every chunked call; CHECK in code that glossary names appear in every chunk's prompt. |
| Pass 0 prompt grows uncomfortably large on subtitle-heavy movies | Subtitles are already small per line; even 1500 subtitles is ~50 KB. Pass 0 stays under 80 KB even for outlier cases. |

## Success metrics (how we know it worked)

- Pass 1 prompt size on JK0 drops from today's effective input (full timeline-based) to ~60–70% of today (because Pass 0 absorbs the structure-finding work and Pass 1's task is now narrower).
- Hallucination report flags decrease by ≥50% on a regression movie vs. today's two-pass output.
- Manual act-balance check on the generated script: Act 3 line count > Act 2 line count on every movie (niu-shu §4.0 invariant holds).
