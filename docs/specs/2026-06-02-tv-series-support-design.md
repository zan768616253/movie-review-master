# TV-series (multi-episode) support

**Date:** 2026-06-02
**Status:** Draft — awaiting sign-off before implementation
**Scope:** `workbench/` harness (config + step scripts), `app/pipeline/stage_2/*` (prompt builders + post-validation), a narrow additive change to `app/pipeline/stage_3_generate_audio.py` (recognize a `[RECAP]` block).
**Out of scope:** Stage 1 (visual indexing, subtitle parsing) and Stage 4 (cheatsheet) logic — they run per-episode unchanged. `styles/niu-shu.md` voice/act-balance rules. TTS engine. Automatic concatenation of episode videos (still done in 剪映).

## Problem

The pipeline produces a one-shot review of a single self-contained movie. TV
shows and anime (e.g. *Stranger Things*, 《隐秘的角落》, 《咒术回战》第三季) differ in
two ways the current pipeline cannot express:

1. **Continuity.** Each episode's plot depends on earlier episodes. A digest or
   script written for episode 5 in isolation cannot reason about a betrayal set
   up in episode 2, and will either omit the causal chain or invent it.
2. **Recap framing.** Binge-review videos (the「一口氣看完 1~7 集」format the
   operator is targeting) bridge each episode with a short 前情提要 recap before
   diving into new material. The current script always opens with a movie-style
   `[HOOK]`, which has no notion of "where we left off."

The operator wants to produce these **one episode at a time** (technically the
same per-title pipeline) while the output reads as **one continuous binge
review**, and wants the day-to-day commands to feel the same as the movie flow.

## Goals

- Run a multi-episode series through the existing Stage 0–4 pipeline with
  **per-episode** work dirs, reusing Stage 1/3/4 unchanged.
- Carry a running **"story-so-far"** forward so each episode's Stage 2 prompts
  know prior events (for causality and consistent character names) **without**
  letting prior events leak into the grounded narration (the hallucination
  guard in `memory/hallucinated_plot_problem.md` still holds for footage).
- Open each episode after the first with a spoken **前情提要 recap** in the
  narrator's voice, ending on a forward tease.
- Keep the operator's workflow nearly identical to the movie flow: one active
  config, the same `step_*` commands, advance episodes by editing one number.

## Non-goals

- Replacing the paste-into-web-LLM workflow. Every pass is still a single
  copy-paste prompt; this design adds **zero** new LLM round-trips per episode
  (continuity is harvested from the digest the operator already produces).
- Auto-merging per-episode MP3/SRT into one video. The final binge assembly is
  done in 剪映, consistent with the project's "draft first, polish in the
  editor" principle. The recap segments are the seams the editor cuts on.
- Touching the style file's voice rules. A single additive `[RECAP]` structural
  marker is documented; nothing else in `styles/niu-shu.md` changes.
- Cross-episode visual grounding. Episode N's index only contains episode N's
  shots. Recap sentences are deliberately ungrounded (see `<refs>recap</refs>`).

## Core idea: an episode is a movie; a series is a thin layer above

Each episode is processed exactly like a movie — its own slug, its own
`stage0..4` work dir, its own `visual_segments.json` / `script.txt` /
`voiceover_*.mp3`. The only new machinery is:

1. A **series config** that lists episodes and points at the active one.
2. A **running continuity file** (`series_context.md`) at the series root,
   auto-seeded from each episode's digest.
3. **Prompt injection** in Stage 2: prior context as background (digest + story)
   and a recap-opening directive (story).
4. A **one-line additive change** in Stage 3 to recognize `[RECAP]` as an
   opening narrated block (same handling as `[HOOK]`).

## Config (`workbench/configs/current_series.toml`)

A new active-config file. The `step_*` scripts read the **series** config when
`configs/current_series.toml` is present and non-empty; otherwise they fall back
to today's `configs/current_movie.toml` (movie mode). Switching back to a movie
= delete/rename `current_series.toml`. Commands are unchanged in both modes.

```toml
# Pipeline config for a TV series / anime. Paths are relative to the repo root.

[common]
series_slug    = "jujutsu_kaisen_s3"
series_dir     = "movies/咒术回战第三季"     # holds synopsis.md + characters/
series_title   = "咒术回战 第三季 (Jujutsu Kaisen S3)"
style_path     = "styles/niu-shu.md"
genre          = "Action"
active_episode = 1            # the episode every step operates on

digest_mode    = "single"     # "single" | "chunked" (per-episode, same as movies)
target_seconds = 720.0        # per-episode review length (soft hint)

[[episodes]]
episode_no    = 1
title         = "第1集 起"
video_file    = "EP01.mp4"
subtitle_file = "EP01.ass"
# synopsis_file = "EP01.synopsis.md"   # optional; defaults to series-level synopsis.md

[[episodes]]
episode_no    = 2
title         = "第2集 承"
video_file    = "EP02.mp4"
subtitle_file = "EP02.ass"
```

- `synopsis.md` and `characters/` live once at `series_dir` and are shared by
  every episode (cast is consistent within a series). An episode may override
  the synopsis via `synopsis_file`.
- `[tools.*]` tables (TTS overrides etc.) work exactly as in the movie config.

### Input directory layout

```text
movies/<series_dir>/
  synopsis.md            # whole-series cast + arc (shared)
  characters/            # shared face gallery
  EP01.mp4  EP01.ass
  EP02.mp4  EP02.ass
  ...
```

## Work-directory layout

Episodes nest under the series; series-shared state sits at the series root:

```text
workbench/work/<series_slug>/
  series_context.md          # running "story-so-far", auto-seeded per episode
  ep01/
    stage0/ stage1/ stage2/ stage3/ stage4/   # identical to a movie run
  ep02/
    stage0/ ...
```

Implementation: the harness synthesizes a movie-shaped `common` dict for the
active episode with `movie_slug = "<series_slug>/ep<NN>"`, so the **existing**
`build_paths()` produces `workbench/work/<series_slug>/ep<NN>/stageN/` with no
changes to the per-stage path logic. `series_context.md` is resolved separately
at `workbench/work/<series_slug>/series_context.md`.

## Continuity: the running "story-so-far"

### Source — harvested from the digest (no extra LLM call)

Pass 1's digest output gains one final section:

```
## 承上启下 (Continuity Carryover) — 写给下一集
（3–5 句中文：本集结束时的故事状态——谁在哪、哪些线索悬而未决、留下的钩子。
这是观众进入下一集前必须记住的内容。）
```

When the operator advances past a **filled** `plot_digest.txt`, the series
harness extracts this section (everything under the `## 承上启下` header up to the
next `##` or EOF) and writes it into `series_context.md` as that episode's block:

```markdown
## 第 1 集 回顾
<extracted continuity text>

## 第 2 集 回顾
<...>
```

Writes are idempotent per episode (re-running overwrites only that episode's
block). If the section is missing, the harness warns and leaves a placeholder
the operator can fill by hand — `series_context.md` is always human-editable.

### Injection — prior episodes only

When building episode N's prompts, the harness reads
`series_context.md` and assembles the text of episodes `1..N-1` (never episode N
itself). For episode 1 this is empty → behaves exactly like a movie.

- **Pass 1 (digest)** receives the prior context as a `# Previously in the
  series` background block: "use this only to recognize returning characters and
  ongoing threads and keep their established names; these events are NOT in this
  episode's timeline — do **not** cite footage for them." The digest still ends
  with its own `## 承上启下` carryover.
- **Pass 2 (story)** receives the same prior context as the **recap source**
  plus a recap-opening directive (below).

## The `[RECAP]` opening block

| Episode | Opening block | Rationale |
|---|---|---|
| 1 | `[HOOK]` (unchanged) | First episode opens the whole binge video; nothing to recap. |
| 2…N | `[RECAP]` (replaces `[HOOK]`) | Bridge from prior context, end on a forward tease into the new episode. A separate dramatic hook is redundant. |

The story prompt, when prior context is present, instructs:

- Open with a `[RECAP]` block: a tight 前情提要 of where the story left off, in the
  narrator's voice, ending with a one-line pull into this episode.
- Every recap sentence is tagged `<refs>recap</refs>` on its own line. This is a
  **sentinel ref-class**, not a `visual:NNN` — it tells the editor "pull footage
  from a previous episode here," and tells post-validation "intentionally
  ungrounded; do not flag." All non-recap sentences keep the normal hard
  grounding requirement (real `visual:NNN` from this episode).
- After `[RECAP]`, the script continues with `[ACT …]`/`[CLOSING]` as today.

### Stage 3 change (additive, minimal)

- `STRUCTURAL_MARKER_RE` gains `RECAP`.
- The opening-block branch becomes `if marker in ("HOOK", "RECAP")` so a
  `[RECAP]`-opened script turns `in_script` on (otherwise the whole script is
  skipped). `[RECAP]` becomes one manifest chunk just like `[HOOK]`.
- `<refs>recap</refs>` already parses to zero visual ranges via the existing
  digit-only `REF_TOKEN_RE`, so the recap prose is still spoken and simply
  carries no visual ranges in the manifest. No change needed there; covered by a
  regression test.

### post-validation change

- `_ACT_HEADER_RE` gains `RECAP`.
- A `<refs>recap</refs>` (or any non-`visual:` sentinel) marks the following
  sentence as intentionally ungrounded: it is **not** flagged as missing-refs and
  **not** checked against scene ranges. Naked recap sentences (no `<refs>` at
  all) are still flagged, so the operator can't accidentally drop the sentinel.

## Workflow (operator's view)

```bash
# One-time: create movies/<series_dir>/ with synopsis.md + characters/ + EPxx files,
# write workbench/configs/current_series.toml, set active_episode = 1.

# Per episode (identical commands to the movie flow):
python workbench/step_1_prepare_inputs.py      # indexes ep<NN>, parses its subs
python workbench/step_2_build_prompt.py         # outline → digest → story (auto-detect)
#   ↑ on the digest→story hop, harvests 承上启下 into series_context.md
#   ↑ from episode 2 on, injects prior context + emits a [RECAP] story prompt
python workbench/step_3_generate_audio.py       # per-episode MP3 + SRT + manifest
python workbench/step_4_build_cheatsheet.py     # per-episode editor cheatsheet

# Advance: bump active_episode to 2 in current_series.toml, repeat.
# Assemble all episodes into one binge video in 剪映, cutting on the recap seams.
```

## File outputs (per series)

| File | Producer | Consumer |
|---|---|---|
| `work/<slug>/series_context.md` | step_2 (harvest) + operator edits | step_2 prompt injection for later episodes |
| `work/<slug>/ep<NN>/stage2/*` | per-episode Stage 2 (as movies) | downstream stages |
| `work/<slug>/ep<NN>/stage3/voiceover_*.{mp3,srt}` | per-episode Stage 3 | 剪映 |

## Testing

- **Config**: series detection, episode lookup, synthesized episode `common`,
  episode-nested work dir, series-level synopsis + per-episode override.
- **Continuity**: `## 承上启下` extraction (present / missing / multiple `##`);
  idempotent per-episode update of `series_context.md`; "episodes 1..N-1 only"
  assembly.
- **Prompt builders**: digest injects prior context as no-footage background and
  keeps the carryover section; story emits a `[RECAP]`-opening directive with
  `<refs>recap</refs>` when prior context is present and falls back to `[HOOK]`
  when it is absent (episode 1 == today's behavior — regression).
- **Stage 3**: a `[RECAP]`-opened script parses (script not skipped), `[RECAP]`
  is one chunk, recap prose is spoken with empty ranges.
- **post-validation**: `recap` sentinel sentences are not flagged; naked recap
  sentences still are; normal `visual:NNN` validation unchanged.
- **Integration**: a 2-episode synthetic series runs episode 1 (HOOK, empty
  context) then episode 2 (context injected, RECAP emitted, carryover harvested).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Digest omits the `## 承上启下` section | Harness warns + writes an editable placeholder; `series_context.md` is human-editable. |
| Operator advances `active_episode` before filling the digest | Continuity harvest only runs on a *filled* digest; otherwise prior context for the next episode is simply incomplete and flagged in the log. |
| Recap narration drifts into ungrounded plot for the *current* episode | Only `<refs>recap</refs>`-tagged sentences are exempt; everything else keeps hard grounding + post-validation. |
| `series_context.md` grows large over many episodes | Carryover is 3–5 sentences/episode; even 12 episodes stays well under prompt-size limits. Long series can prune old blocks by hand. |
| Two active-config files confuse the operator | Series config is preferred only when present; the log banner states which mode + which episode is active on every step. |

## Open questions (resolved during planning)

- Whether `series_context.md` injection should include the *full* accumulated
  context or only the last K episodes. Default: full (small); revisit if size
  becomes an issue.
- Whether to add a series-level `step_4` "season cheatsheet" linking all
  episodes. Deferred — per-episode cheatsheets ship first.
