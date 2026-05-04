# Pipeline Sync Hardening Plan

**Status:** Core overhaul is done; sync hardening is still in progress.  
**Owner:** Eric.  
**Goal:** Make final video generation reliably fast, low-cost, and structurally safe for audio/video sync.

This document replaces the old "overhaul nearly finished" status. The single-pass `[ANCHOR]` planner-writer architecture is already in place, but recent SPL2 runs showed that the remaining quality problems are now concentrated in **Stage 2 structural fit** and **Stage 6 residual fallback behavior**.

---

## 1. What is already done

### Completed architectural shifts
- **Single-pass Stage 2 planner-writer** is live. The LLM now selects visual anchors and writes narration in one pass.
- **Shot-aware range contract** is live:
  - each range must stay inside one source shot,
  - each anchor caps at 12s total,
  - validators reject shot-crossing and oversized anchors.
- **Stage 6 boundary parity fix** is live:
  - Stage 6 now respects the same inner-cut collapse model as Stage 2/validator,
  - hidden micro-cuts no longer cause pathological early snaps.
- **Stage 6 snap-back threshold** is live:
  - clean shot-boundary snaps are only used when close to the desired trim point,
  - otherwise Stage 6 falls back to mid-shot trim.
- **Stage 2 macro budget controls** are live:
  - `target_seconds` is the single runtime authority,
  - validator checks both global under-length and global over-coverage,
  - prompt includes local act budgets and anchor-fill guidance.

### What these fixes solved
- The old Stage 6 collapse-mismatch freeze bug is no longer the main blocker.
- Stage 2 now correctly rejects scripts that are too short, too over-covered, or structurally invalid.

---

## 2. Current blocker

The remaining problem is **not** that the validator is wrong. The validator is surfacing real failures that the LLM still produces.

### Observed failure shapes

Two bad Stage 2 shapes are now confirmed:

1. **Over-coverage shape**  
   The LLM selects 2x-3x too much source footage for the narration.  
   Result: Stage 6 must discard too much of the chosen visual beat sequence, causing semantic mismatch.

2. **Under-coverage / over-dense shape**  
   The LLM selects too few anchors, mostly single-range, and writes too much text on short shots.  
   Result: many anchors exceed local budget, total script runtime is too short, and later stages are forced into risky extension/fallback behavior.

### Concrete SPL2 evidence
- Prior over-coverage run:
  - ~2053s selected coverage for ~795s spoken audio
  - coverage/audio ratio ~2.58x
- Later under-coverage run:
  - 70 anchors, all single-range
  - 3332 chars vs 4125 min for a 720s target
  - 501s coverage vs 687.5s min
  - 34 budget overruns + 4 warnings

**Conclusion:** LLM voice generation is good enough; LLM structural self-enforcement is not reliable enough.

---

## 3. Design decision on local VL models

### Recommendation

**Use local VL only as an optional, targeted QA/helper layer. Do not make it a required core stage.**

This is the best tradeoff for:
- **fast generation**
- **low cost**
- **predictable runtime**
- **good enough semantic review**

### Why local VL is not useless
It can help with decisions that deterministic code cannot make confidently:
- whether an adjacent shot is still the **same beat**
- whether two candidate shots both fit the narration, and which fits better
- whether a suspicious rendered chunk is a true semantic mismatch or just a harmless trim

### Why local VL should not be the backbone
It is a poor fit for:
- enforcing arithmetic (`chars <= duration x cps`)
- reviewing the full 10-12 minute video every run
- acting as the only source of truth for sync correctness
- replacing deterministic repair logic

### Working assumption for RTX 4060
A local quantized VLM can be useful for:
- short suspicious chunks,
- sampled frames + anchor narration text,
- ranking 2-4 candidate nearby shots.

It is **not** a good default for:
- whole-video review,
- raw audio/video end-to-end judgment,
- always-on pipeline gating.

### Decision
- **Default pipeline path:** deterministic only
- **Optional QA path:** local VL on flagged chunks only
- **If local VL is unavailable:** pipeline must still work end-to-end

---

## 4. Required next phase — Stage 2.5 deterministic repair

This is the main missing piece.

### Why it is required
Right now the LLM is still trusted to satisfy structural rules that are fundamentally mathematical and contract-based. That is the wrong responsibility split.

### Stage 2.5 mission
Insert a deterministic repair pass between:
- **Stage 2 LLM output**, and
- **Stage 2 validation / Stage 3 audio generation**

### Stage 2.5 responsibilities

#### A. Repair local budget failures
For each anchor that exceeds `duration x chars_per_second`:
- compute required minimum coverage from narration length,
- search nearby legal shot candidates,
- extend only when candidates appear to stay inside the **same beat**,
- keep total anchor duration <= 12s,
- preserve shot-boundary legality.

#### B. Repair structural range failures
For:
- `range_too_long`
- `anchor_too_long`
- `range_shot_crossing`

Stage 2.5 should deterministically:
- split at legal shot boundaries,
- produce multiple anchors when necessary,
- preserve stable ids (`chunk-024`, `chunk-024b`, etc.),
- avoid illegal merged ranges.

#### C. Repair global under-coverage / under-length
When the whole script is short:
- identify under-covered act regions,
- find gap windows in the shot menu,
- issue a **small targeted LLM addendum prompt** that adds anchors only in those gaps,
- do not ask for a full-script rewrite unless the script is broadly unsalvageable.

### What Stage 2.5 must NOT do
- **Do not blindly append the next adjacent shot** just because it is nearby in time.
- **Do not proportionally split narration by character count** and pretend that is narratively correct.
- **Do not silently turn semantically wrong anchors into technically valid ones.**

### Repair policy

Use a triage model:

1. **Mild local overrun**
   - deterministic range growth is allowed
   - only if same-beat evidence is strong

2. **Severe local overrun (e.g. 2x-3x budget)**
   - treat as anchor-shape failure
   - split and/or request targeted micro-rewrite

3. **Global shortfall**
   - add new anchors in known gaps
   - avoid full-script regeneration by default

### Deliverables
- new Stage 2.5 repair module
- repair report artifact
- rerun validator automatically after repair
- fail closed if script still violates hard constraints

---

## 5. Required follow-up — Stage 6 conservative safety net

Stage 6 should remain a **last-mile safety layer**, not the primary fix.

### Keep
- boundary parity
- snap-back threshold
- post-handle extension
- black-frame splitting/clamping

### Add
- prefer moving visual continuation over freeze when a tiny residual shortfall remains
- only use this for small residual drift

### Safety order
1. trim/extend inside current legal range
2. extend inside same source clip / post-handle
3. if still short, use conservative local continuation logic
4. freeze only as the last fallback

### Guardrail
Do not casually borrow from the next anchor unless timeline ownership and downstream segment boundaries are updated coherently.

---

## 6. Optional Phase — local VL semantic QA

This phase is optional and should be added only after Stage 2.5 exists.

### Best use
Run local VL only on suspicious chunks flagged by cheap heuristics:
- high trim percentage
- `extension-needed`
- black-split / splice events
- short anchor with dense narration
- ambiguous Stage 2.5 repair choices

### Inputs
- current anchor narration text
- 4-8 sampled frames from the chosen chunk or candidate shots
- optionally 2-4 neighboring candidate shots

### Expected outputs
- `same_beat_yes_no`
- `best_candidate`
- `issue_type`
- `confidence`

### Good uses
- rank candidate extension shots
- confirm whether a suspicious rendered chunk is semantically mismatched
- help residual QA before export

### Bad uses
- full-video review every run
- hard gating the pipeline
- replacing deterministic validation

### Success criterion
VL should reduce false repair choices on a **small flagged subset**, not become a new always-on cost center.

---

## 7. Verification plan

We should stop using "looks better" as the main success criterion.

### Required metrics
- total spoken chars
- projected audio seconds from narration text
- total selected anchor coverage
- coverage/audio ratio
- anchors by shape:
  - single-range
  - multi-range
  - <5s
  - 5-8s
  - 8-12s
  - >12s
- validator counts by failure type
- Stage 6 trim distribution
- Stage 6 residual still/freeze seconds
- chunks with >=1s residual still
- chunks with >=2s residual still

### Minimum acceptance for a "good" run
- Stage 2 validator passes with no hard failures
- selected coverage lands inside the configured window
- projected audio is close to `target_seconds`
- Stage 6 residual still/freeze is small and concentrated only in edge cases
- subjective spot-check confirms no obvious narration/visual mismatch in flagged areas

---

## 8. Implementation order

### Priority 1 — required
1. Build **Stage 2.5 deterministic repair**
2. Add **verification metrics** artifact/report
3. Audit residual Stage 6 freeze/still cases after repaired Stage 2 output

### Priority 2 — strongly recommended
4. Add conservative Stage 6 residual-motion fallback

### Priority 3 — optional
5. Add local VL review for flagged chunks only

### Priority 4 — cleanup
6. Update remaining docs (`docs/TECHNICAL.md`, `tmp/README.md`)
7. Delete this file only after sync hardening is complete and verification is green

---

## 9. Final recommendation

The next load-bearing change is **not** "use a VL model everywhere."

The next load-bearing change is:

> **Move structural fit out of the LLM and into deterministic Stage 2.5 repair.**

Then, if desired:

> **Use local VL as a cheap, targeted semantic judge on a small set of suspicious chunks.**

That gives the best balance of:
- generation speed
- local cost control
- stable sync behavior
- better semantic fit in the final video
