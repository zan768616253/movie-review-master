# TV-series support — implementation plan

**Goal:** Add multi-episode (TV/anime) support to the pipeline: a series config
with an active-episode pointer, a running continuity file auto-seeded from each
episode's digest, prior-context injection into Stage 2, and a `[RECAP]` opening
block for episodes after the first — reusing Stage 0/1/3/4 per episode.

**Spec:** `docs/specs/2026-06-02-tv-series-support-design.md`

**Tech stack:** Python 3.12, pytest, argparse, tomllib. No new dependencies.

**Method:** TDD, one task per commit. Tests first, watch them fail, implement,
watch them pass, commit. Backward compatibility for the movie path is a hard
requirement — every existing test must stay green.

---

## Test execution conventions

Every Python command runs under the project conda env. The required prefix is:

```
conda run -n py312_machine_learning --no-capture-output
```

For brevity the steps write `python -m pytest ...`; **prepend the prefix to
every real run**. Reference: `docs/agent-rules/python-environment.md`.

---

## File structure

**New files**
- `app/pipeline/series_context.py` — pure continuity logic (extract / update / assemble)
- `tests/pipeline/test_series_context.py`
- `tests/workbench/__init__.py`, `tests/workbench/conftest.py` — put `workbench/` on `sys.path`
- `tests/workbench/test_common_series.py`
- `workbench/configs/_series_template.toml`
- `tests/pipeline/test_series_integration.py`

**Modified**
- `workbench/_common.py` — series detection, episode resolution, `resolve_run_context()`, `series_context_file()`
- `workbench/step_0..4_*.py` — use `resolve_run_context()` (1–2 lines each)
- `workbench/step_2_build_prompt.py` — inject prior context, harvest carryover
- `app/pipeline/stage_2/pass_1_digest_single.py` — `prior_context_text`, carryover instruction
- `app/pipeline/stage_2/pass_1_digest_chunked.py` — thread `prior_context_text`, carryover on tail only
- `app/pipeline/stage_2/pass_2_story.py` — `prior_context_text` + `[RECAP]` recap-mode directive
- `app/pipeline/stage_2_build_prompt.py` — `--prior-context` flag (digest + story)
- `app/pipeline/stage_3_generate_audio.py` — recognize `[RECAP]`
- `app/pipeline/stage_2/post_validate.py` — `[RECAP]` header + `recap` ref sentinel
- Docs: `docs/HANDBOOK.md`, `docs/TECHNICAL.md`, `PROD.md`, `workbench/README.md`, `styles/niu-shu.md` (additive `[RECAP]` note)

**Untouched logic:** Stage 1 modules, Stage 4 logic, TTS engine, `script_contract.py`, the style voice/act-balance rules.

---

## Task 1: Pure continuity logic (`series_context.py`)

The string-only core: extract the carryover from a digest, update the running
markdown per episode, and assemble prior-episode context. No file I/O — trivially
testable and reusable by the harness.

**Files:** create `app/pipeline/series_context.py`, `tests/pipeline/test_series_context.py`

- [ ] **Step 1 — failing tests.** Cover:
  - `extract_continuity_section(digest_text)` returns the text under a
    `## 承上启下` header up to the next `## ` or EOF; returns `None` when absent;
    tolerates extra heading text after `承上启下` on the same line.
  - `update_series_context(existing_md, episode_no, episode_title, carryover)`
    inserts a `## 第 N 集 回顾 — <title>` block; re-running with the same N
    overwrites only that block (idempotent) and preserves block order by N.
  - `assemble_prior_context(series_md, before_episode_no)` returns the
    concatenated blocks for episodes `< before_episode_no` only; empty string
    when none (episode 1).
- [ ] **Step 2 — run, confirm ImportError / failures.**
- [ ] **Step 3 — implement** `app/pipeline/series_context.py`:
  - `CONTINUITY_HEADER = "承上启下"`; a regex matching `^##\s*承上启下` up to the
    next `^##\s` or EOF.
  - Episode blocks keyed by a stable `^##\s*第\s*(\d+)\s*集` regex so update can
    locate and replace a single block; rebuild the file sorted by episode number.
  - All functions operate on `str` and return `str`/`str | None`.
- [ ] **Step 4 — run, confirm green.**
- [ ] **Step 5 — commit:** `feat: add pure series continuity helpers (extract/update/assemble)`

---

## Task 2: Series config resolution in `_common.py`

Detect the series config, resolve the active episode into a movie-shaped
`common` dict so existing `build_paths()` produces episode-nested work dirs, and
expose `resolve_run_context()` as the single entry the steps call.

**Files:** modify `workbench/_common.py`; create `tests/workbench/{__init__.py,conftest.py,test_common_series.py}`

- [ ] **Step 1 — failing tests** (`conftest.py` adds `workbench/` to `sys.path`):
  - `is_series_config(cfg)` true when `[[episodes]]` + `series_slug` present.
  - `series_episode_common(cfg, 2)` returns a dict with
    `movie_slug == "<series_slug>/ep02"`, `movie_dir == series_dir`,
    `video_file`/`subtitle_file` from episode 2, `movie_title` from the episode
    `title` (fallback `"<series_title> 第2集"`), and inherited
    `style_path`/`genre`/`digest_mode`/`target_seconds`.
  - `build_paths(series_episode_common-wrapped cfg)` yields
    `…/work/<series_slug>/ep02/stage1/visual_segments.json`.
  - `series_context_file(cfg)` → `…/work/<series_slug>/series_context.md`.
  - Per-episode `synopsis_file` override resolves; default is series `synopsis.md`.
  - `episode_entry(cfg, n)` raises a clear error for an unknown episode number.
- [ ] **Step 2 — run, confirm failures.**
- [ ] **Step 3 — implement** in `_common.py`:
  - `load_active_config()` → load `configs/current_series.toml` if present and
    non-empty, else `configs/current_movie.toml`; return `(cfg, is_series)`.
  - `is_series_config`, `series_episodes`, `active_episode_no`, `episode_entry`,
    `series_episode_common`, `series_context_file`.
  - Add optional `synopsis_file` support to `build_paths` (default `"synopsis.md"`),
    keeping the movie path unchanged.
  - `resolve_run_context()` → returns a small dataclass `RunContext(cfg, paths,
    is_series, episode_no, series_context_path)`; for movie mode
    `is_series=False`, `episode_no=None`, `series_context_path=None`.
- [ ] **Step 4 — run new + full suite green** (`pytest -q`).
- [ ] **Step 5 — commit:** `feat: series config resolution + episode-nested paths in workbench/_common`

---

## Task 3: Stage 3 recognizes `[RECAP]`

**Files:** modify `app/pipeline/stage_3_generate_audio.py`; add cases to `tests/pipeline/test_stage_3_generate_audio.py`

- [ ] **Step 1 — failing tests:**
  - A script opening with `[RECAP]` (no `[HOOK]`) parses to ≥1 chunk (script not
    skipped); first chunk `section == "RECAP"`.
  - A `<refs>recap</refs>` line followed by prose → the prose is in the chunk
    text (spoken) with empty `ranges`.
- [ ] **Step 2 — run, confirm failures** (currently the `[RECAP]` script yields
  "No narration chunks found").
- [ ] **Step 3 — implement:** add `RECAP` to `STRUCTURAL_MARKER_RE`; change the
  opening branch to `if marker in ("HOOK", "RECAP"):`.
- [ ] **Step 4 — run, confirm green** (existing HOOK tests unaffected).
- [ ] **Step 5 — commit:** `feat: stage 3 treats [RECAP] as an opening narrated block`

---

## Task 4: post-validation exempts the `recap` sentinel

**Files:** modify `app/pipeline/stage_2/post_validate.py`; add cases to `tests/pipeline/test_post_validate.py`

- [ ] **Step 1 — failing tests:**
  - `[RECAP]` header line is skipped (not treated as a sentence).
  - A sentence under `<refs>recap</refs>` is **not** flagged.
  - A recap-section sentence with **no** `<refs>` at all **is** flagged
    (missing-refs still enforced).
  - Normal `visual:NNN` validation is unchanged (regression).
- [ ] **Step 2 — run, confirm failures.**
- [ ] **Step 3 — implement:** add `RECAP` to `_ACT_HEADER_RE`; when a `<refs>`
  body contains no `visual:NNN` token but is non-empty (the sentinel, e.g.
  `recap`), set a flag that marks the next sentence intentionally-ungrounded —
  skip both the missing-ref and scene-overlap checks for it.
- [ ] **Step 4 — run, confirm green.**
- [ ] **Step 5 — commit:** `feat: post-validation exempts <refs>recap</refs> sentinel sentences`

---

## Task 5: Pass 1 single-mode prior-context + carryover

**Files:** modify `app/pipeline/stage_2/pass_1_digest_single.py`; add to `tests/pipeline/test_pass_1_digest_single.py`

- [ ] **Step 1 — failing tests:**
  - `build_digest_prompt(..., prior_context_text="…")` includes a
    `# Previously in the series` block and the no-footage warning ("do not cite
    footage for prior events").
  - With `prior_context_text=None` the prompt is byte-identical to today (regression).
  - The output format includes the `## 承上启下` carryover instruction when
    `request_carryover=True` (default) and omits it when `False`.
- [ ] **Step 2 — run, confirm failures.**
- [ ] **Step 3 — implement:** add `prior_context_text: str | None = None` and
  `request_carryover: bool = True`; inject the prior-context background section
  (after synopsis, before the timeline) and append the carryover instruction to
  the output-format section. No change when both are default-off-equivalent.
- [ ] **Step 4 — run new + `test_stage_2_build_prompt.py` green.**
- [ ] **Step 5 — commit:** `feat: Pass 1 digest accepts prior-episode context + carryover request`

---

## Task 6: Pass 1 chunked-mode threads prior-context

**Files:** modify `app/pipeline/stage_2/pass_1_digest_chunked.py`; add to `tests/pipeline/test_pass_1_digest_chunked.py`

- [ ] **Step 1 — failing tests:** prior context appears in **every** chunk
  (front/climax/tail); the `## 承上启下` carryover instruction appears in **only**
  the tail chunk.
- [ ] **Step 2 — run, confirm failures.**
- [ ] **Step 3 — implement:** pass `prior_context_text` to all three
  `build_digest_prompt` sub-calls; pass `request_carryover=True` only for `tail`,
  `False` for `front`/`climax`.
- [ ] **Step 4 — run, confirm green.**
- [ ] **Step 5 — commit:** `feat: chunked digest threads prior context; carryover on tail only`

---

## Task 7: Pass 2 story prior-context + `[RECAP]` recap mode

**Files:** modify `app/pipeline/stage_2/pass_2_story.py`; add to `tests/pipeline/test_stage_2_build_prompt.py` (or a new `test_pass_2_story.py`)

- [ ] **Step 1 — failing tests:**
  - `build_story_prompt(..., prior_context_text="…")` includes a
    `# Previously in the series (recap source)` block and a directive to open
    with a `[RECAP]` block using `<refs>recap</refs>` and a forward tease; the
    output-requirements mention `[RECAP]`.
  - With `prior_context_text=None`, no recap directive appears and the prompt is
    the existing `[HOOK]`-oriented one (regression — episode 1 == movie behavior).
  - The grounding section still applies to non-recap sentences.
- [ ] **Step 2 — run, confirm failures.**
- [ ] **Step 3 — implement:** add `prior_context_text: str | None = None`; when
  set, derive `recap_mode=True`, inject the recap-source block and the recap
  directive, and adjust the act-structure / output-requirements text to allow
  `[RECAP]` as the opener. Recap sentences are tagged `<refs>recap</refs>`;
  everything else keeps the hard grounding rule.
- [ ] **Step 4 — run new + full Stage 2 suite green.**
- [ ] **Step 5 — commit:** `feat: Pass 2 story emits [RECAP] opening when prior context is present`

---

## Task 8: Stage 2 CLI `--prior-context`

**Files:** modify `app/pipeline/stage_2_build_prompt.py`; add to `tests/pipeline/test_stage_2_build_prompt.py`

- [ ] **Step 1 — failing tests:** `--prior-context PATH` in `--digest` and story
  modes loads the file and threads it into the builder (assert the prompt
  contains a marker from the prior-context file); absent flag → unchanged.
- [ ] **Step 2 — run, confirm failures.**
- [ ] **Step 3 — implement:** add the argument; read via `read_text_strict`; pass
  `prior_context_text=` into `build_digest_prompt` / `build_chunked_digest_prompts`
  / `build_story_prompt`.
- [ ] **Step 4 — run, confirm green.**
- [ ] **Step 5 — commit:** `feat: stage 2 CLI --prior-context threads series continuity`

---

## Task 9: Workbench series wiring

Make the steps series-aware and add the template. step_2 additionally assembles
prior context (episodes `< active`) into `stage2/prior_context.md`, passes it via
`--prior-context`, and harvests this episode's `承上启下` into `series_context.md`
once the digest is filled.

**Files:** create `workbench/configs/_series_template.toml`; modify `workbench/step_0..4_*.py`

- [ ] **Step 1 — template.** Write `_series_template.toml` per the spec's config block.
- [ ] **Step 2 — steps 0/1/3/4.** Replace the `load_config(DEFAULT_CONFIG)` +
  `build_paths` + `ensure_stage_dirs` trio with `ctx = resolve_run_context()`.
  Banners print the series + episode when `ctx.is_series` (e.g.
  `… for <series_title> · 第 2 集`). Behaviour for movie configs is unchanged.
- [ ] **Step 3 — step_2 inject + harvest.**
  - Before building the **digest** and **story** prompts in series mode with
    `episode_no > 1`: assemble prior context via
    `assemble_prior_context(series_context.md, episode_no)`, write it to
    `paths.stage2_dir/"prior_context.md"`, and append
    `--prior-context <that file>` to the CLI args.
  - When the **digest reply is filled** (story step or done): read
    `plot_digest.txt`, `extract_continuity_section`, and
    `update_series_context(...)` for `episode_no` → write `series_context.md`.
    Warn + write a placeholder block if the section is missing.
  - `--prior-context` is omitted for episode 1 and for movie mode → those paths
    are byte-for-byte unchanged.
- [ ] **Step 4 — manual smoke (documented in the task, not automated):** run
  step_2 against `_series_template.toml` filled with a 2-episode fixture; confirm
  episode 1 produces a `[HOOK]` story prompt and episode 2 a `[RECAP]` one.
- [ ] **Step 5 — full suite green; commit:** `feat: workbench steps run series episodes with continuity inject/harvest`

---

## Task 10: Integration test + docs

**Files:** create `tests/pipeline/test_series_integration.py`; update docs

- [ ] **Step 1 — integration test.** A 2-episode synthetic series (tiny
  visual_segments + subtitles per episode, hand-written scene_markers + digest
  with a `## 承上启下` section). Drive the prompt builders + continuity helpers
  directly (no real LLM): episode 1 → story prompt has `[HOOK]`, no prior block;
  harvest → `series_context.md` gets 第 1 集; episode 2 → prior block injected,
  story prompt emits `[RECAP]`. Assert post-validation passes on a hand-written
  episode-2 script whose recap sentences use `<refs>recap</refs>`.
- [ ] **Step 2 — docs.**
  - `docs/HANDBOOK.md`: a "Series mode" subsection (continuity model, `[RECAP]`).
  - `docs/TECHNICAL.md`: `series_context.py` surface, `_common` series functions,
    config/work-dir layout, `[RECAP]` marker.
  - `PROD.md`: TV-series inputs + the series workflow.
  - `workbench/README.md`: series config + episode loop.
  - `styles/niu-shu.md`: one additive note that `[RECAP]` is an allowed opener
    for series episodes (treated like `[HOOK]`), no voice/act-balance change.
- [ ] **Step 3 — full suite green; commit:** `feat: series integration test + docs for TV-series support`

---

## Verification checklist (run after Task 10)

- [ ] `pytest -q` fully green (movie regressions + new series tests).
- [ ] Movie-mode prompts are byte-identical to pre-change output (diff a sample).
- [ ] Episode 1 story prompt opens `[HOOK]`; episode 2 opens `[RECAP]` with
  `<refs>recap</refs>`.
- [ ] `series_context.md` accumulates one block per episode, idempotent on re-run.
- [ ] A `[RECAP]`-opened script flows through Stage 3 (MP3/SRT/manifest) and
  Stage 4 (cheatsheet) without errors; recap chunk carries no visual ranges.
