# Style Contract

> **This file defines the rules every `*.md` style file in this folder must follow.**
> Read this before writing a new style or editing an existing one. The pipeline
> assumes all styles conform to this contract; deviations break Stage 2 prompts,
> Stage 3 chunking, or Stage 5 rendering.

---

## 1. What a "style" is and isn't

A style file describes **the voice and shape** of a 7-12 minute Chinese movie-review
script. It is consumed verbatim by Stage 2's writer-pass prompt as the "Style
Rulebook" — the LLM is told to follow it exactly.

| A style file owns | The pipeline owns (do NOT redefine in a style) |
|---|---|
| Voice, tone, perspective (first/third person, sarcastic, sincere, etc.) | The `[SCENE …]` marker format — see `app/pipeline/common/script_contract.py` |
| Hook strategy and signature opening phrase | The structural marker hierarchy — see §3 below |
| Character naming convention (archetypes vs original names) | Beat granularity targets — see §3 |
| Re-engagement beat *types* (sarcasm vs interior revelation vs …) | Stage 1 / Stage 0 / Stage 4 / Stage 5 contracts |
| Closing strategy and any signature sign-off | The 7-12 min total **duration** window (audience-retention anchor) |
| Genre-modulation guidance | Whether timestamps appear in the writer pass (they don't) |
| The Chinese-**character** window that maps to 7-12 min for this style's TTS pace | Whether `[BEAT N]` markers appear in the writer pass (they do) |
| Hard constraints unique to the style | |

If a style file contradicts the pipeline-owned contract, the pipeline contract
wins. Do not document `[SCENE …]` syntax in style files — the grounder pass
prompt is the single source of truth for that.

---

## 2. Required content sections

Every style file must contain these top-level sections, in this order. Section
*content* differs across styles; section *presence* does not.

| § | Section | Purpose |
|---|---------|---------|
| 0 | Title + frontmatter blurb | One-line identity (`# Style X: Name`), perspective, tone, target duration, language |
| 1 | **Mission** | The 3 jobs every style serves: hook in 10s, cover whole plot in 7-12 min, sustain attention with re-engagement |
| 2 | **Opening Hook** | The front-load rule, hook ranking criteria, hook patterns/formulas, failure modes, rewind transition |
| 3 | **Character/Protagonist Convention** | How people are named (archetype table OR original-name rules) and any pre-script selection workflow |
| 4 | **Narrative Structure** | Four-act table with per-act minutes, target chars, and per-act job |
| 5 | **Re-engagement Rhythm** | The 60-90s rule, beat-type budget table, self-check question |
| 6 | **Tone & Voice Rules** | Core principle, signature techniques, **Genre Modulation table** (mandatory) |
| 7 | **Plot Compression Rules** | What to keep, what to summarize, what to cut |
| 8 | **Closing** | Allowed closing patterns, optional sign-off rule |
| 9 | **Hard Constraints (红线)** | Numbered non-negotiables, including the universal ones in §4 below |
| 10 | **Script Output Format** | Skeleton showing the marker hierarchy with placeholder text |
| 11 | **Workflow** | Pre-script checklist (character mapping, hook ranking, etc.) producing a user-review block |

A new style is incomplete if any section is missing. A style may add further
sections if it has style-specific rules to document (e.g., niu-shu's
"Transition Phrases" section), but never at the cost of the eleven above.

---

## 3. Required output structure (immutable)

Every style emits a script with these structural markers, in this order:

```
[TITLE] …
[HOOK]
[ACT 1 - SETUP]
[ACT 2 - ESCALATION]
[ACT 3 - CLIMAX]      # or "[ACT 3 - REVEAL + CLIMAX]" — suffix may vary, "ACT 3" must not
[ACT 4 - RESOLUTION]  # suffix may vary
[CLOSING]
```

**What styles may vary:**
- The descriptive suffix after `ACT N` (e.g. `[ACT 3 - CLIMAX]` vs `[ACT 3 - REVEAL + CLIMAX]`).
  The parser regex (`script_contract.py:STRUCTURAL_MARKER_RE`) only requires `[ACT` + digit + arbitrary text + `]`.
- The internal sub-structure of any act (e.g., a `我叫[name]` self-introduction inside `[ACT 1 - SETUP]`).
- Per-act char targets, **as long as they sum to within the style's declared character-count window** (each style sets its own — see §4 constraint #5).

**What styles must NOT vary:**
- The marker names `[TITLE]`, `[HOOK]`, `[ACT N]`, `[CLOSING]`. Nothing else is recognized as structural.
- The 4-act count. Three or five acts will not be parsed correctly.
- Sub-markers like `[SELF-INTRO]`, `[BROLL]`, `[BEAT]` (the writer pass uses `[BEAT N]` internally and they are replaced with `[SCENE …]` by the grounder pass — no other sub-markers are honored downstream). Style-specific sub-markers must be expressed *inside* an act, not as a peer to it.
- The `[SCENE …]` marker format — see §5 below.

**Beat granularity (writer pass):**
- Aim for 30-60 `[BEAT N]` blocks across the whole script.
- Each beat is one breathable spoken sentence or one short paragraph (~30-90 Chinese chars).
- One beat → one `[SCENE …]` marker after the grounder pass → one cut in Stage 5.

---

## 4. Universal hard constraints

These appear (with the same numbers or otherwise) in every style's "Hard
Constraints" section. New styles may add more, but cannot weaken these:

1. **Front-load the hook.** The hook is never the movie's opening scene.
2. **Cover the complete ending.** No "watch the movie to find out" cop-outs.
3. **Re-engagement beat every 60-90 seconds.** No flat stretches longer than the equivalent of ~60-90 seconds at this style's pace.
4. **Total duration 7-12 min.** A style may narrow this range, never widen.
   The duration is universal because it is anchored to short-form-video audience
   retention, not to any TTS pace.
5. **Style declares its own character-count window.** Each style file must
   state, in its frontmatter, the Chinese-character window that maps to the
   7-12 min duration **for that style's TTS pace and sentence rhythm**. Niu
   Shu's dense fast delivery covers more characters per minute than first-person
   POV's short breathable sentences, so the same duration produces different
   char counts. The window must be empirically calibrated against an actual TTS
   render of that style — do not copy another style's number without
   re-rendering.
6. **Genre-match the voice.** Every style has a Genre Modulation table; the writer must pick a row before drafting.

A style is free to invent additional red lines (Niu Shu has "no exclamation-mark
spam"; first-person has "register shift at close"). Style-specific red lines
should be additive to, not in conflict with, the six above.

---

## 5. Scene-marker format is owned by the prompt, not the style

Earlier versions of this folder documented a legacy `[SCENE: HH:MM:SS-HH:MM:SS]`
format inside each style's "Script Output Format" section. **Don't do this in
new styles.** The grounder-pass prompt in `app/pipeline/stage2_generate_script.py`
prescribes the canonical attribute form:

```
[SCENE start=HH:MM:SS.mmm end=HH:MM:SS.mmm source=srt|visual confidence=0.00 evidence=srt:NNN|visual:NNN]
[SCENE source=ungrounded confidence=0.00 evidence=none]    # for ungrounded beats
```

Style files may *show* a placeholder `[SCENE …]` in their output skeleton (so
the LLM sees one structural example), but should not redefine its attributes,
and must not use the legacy two-timestamp form for new styles.

The script_contract parser still accepts the legacy form for compatibility with
existing scripts; for new work, write to the attribute form only.

---

## 6. Validation checklist for a new style

Before adding `styles/<your-style>.md` to the folder, verify:

- [ ] All 12 required sections (0-11) are present and in order.
- [ ] The output skeleton in §10 uses `[TITLE]` / `[HOOK]` / `[ACT 1-4 - …]` / `[CLOSING]` and nothing else as structural markers.
- [ ] Style frontmatter declares a Chinese-character window mapped to 7-12 min, with a one-line note explaining the TTS pace / sentence rhythm it assumes (see §4 constraint #5).
- [ ] The four-act table in §4 of the style file sums to a per-act char budget within the style's declared character-count window.
- [ ] Genre Modulation table is present and covers at least the genres expected for your target movie set.
- [ ] Hard Constraints section restates the five universal red lines.
- [ ] Hook section names a specific signature opening (Niu's `注意看`, first-person's in-medias-res confession, etc.) — not a generic "open with a strong scene."
- [ ] Closing section names a specific shape (sign-off phrase, register shift, etc.) — not just "wrap up."
- [ ] No section documents `[SCENE …]` attribute syntax. (Showing one as an example in the output skeleton is fine.)
- [ ] The style's character-naming convention is explicit (archetype table OR original-names rule) and consistent with §1's table.
- [ ] If your style has a signature sub-beat (Niu's `废话文学`, first-person's `我叫[name]`), it lives *inside* an act, not as a peer marker.

A style that fails any of these is not ready for use by Stage 2.

---

## 7. Existing styles (for reference)

| File | Perspective | Naming | Closing signature |
|------|-------------|--------|-------------------|
| `niu-shu.md` | Third-person omniscient, sarcastic | Archetypes (小帅, 小美, 丧彪 …) | `我们下期再见` sign-off (mandatory) |
| `first-person-pov.md` | First-person protagonist, sincere | Original character names | Register shift to reflection / image / blessing (no sign-off) |

The two styles have **opposite rules** on naming and stance. They are
intentionally extreme — most plausible new styles will land somewhere between
them on those two axes. When in doubt, model your new style on whichever of
the two is closer to the voice you want, and copy its section skeleton.
