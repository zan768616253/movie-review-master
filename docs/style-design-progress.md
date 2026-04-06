# Style System Design — Progress Tracker

**Status:** Style A complete; Style C research complete but transcript pending; Style B not started
**Last Updated:** 2026-04-06
**Recommended Next Style Task:** Transcribe `transcripts/xiaodao_greenline.mp3`, then write `styles/xiaodao.md`

---

## What This Document Tracks

This file tracks the status of the **style library**, not the full engineering pipeline.

The planned style files are:

- `styles/niu-shu.md` — Style A: Uncle Niu / sarcastic third-person narrator
- `styles/first-person-pov.md` — Style B: protagonist POV / immersive first-person narrator
- `styles/xiaodao.md` — Style C: warm, reflective, emotional narrator

For code and execution planning, use `docs/project-status-and-plan.md`.

---

## Current Style Inventory

| Style | File | Status | Notes |
|------|------|--------|-------|
| Style A | `styles/niu-shu.md` | ✅ written | strongest and most concrete style doc right now |
| Style B | `styles/first-person-pov.md` | ❌ missing | concept exists, file not started |
| Style C | `styles/xiaodao.md` | ❌ missing | research done, transcript and file still missing |

---

## What Is Already Backed By Evidence

### Style A — Uncle Niu

Evidence already available:

- `styles/niu-shu.md` exists.
- 7 source MP3 files exist in `transcripts/uncle_niu/`.
- 7 transcript `.txt` files also exist.
- Voice reference samples exist in `voice-samples/uncle_niu/`.

This means Style A is no longer just a theory document. It now has enough source material to support a second refinement pass later.

### Style C — Xiaodao

Evidence already available:

- `docs/style-c-xiaodao-research.md` exists.
- `transcripts/xiaodao_greenline.mp3` exists.
- Channel positioning and title-pattern research are already documented.

What is still missing:

- the actual transcript
- the style definition file
- confirmation of sentence rhythm, transition phrases, and closing pattern from real narration

### Style B — First-Person POV

This remains a design-only idea. There is no transcript research file and no style file yet.

---

## Confirmed Style Differences

These are the three style directions as currently understood:

| Dimension | Style A: Uncle Niu | Style B: First-Person POV | Style C: Xiaodao |
|-----------|--------------------|---------------------------|------------------|
| Perspective | Third-person omniscient | First-person protagonist | Warm narrator addressing viewer |
| Tone | Deadpan, sarcastic, compressed | Emotional, immersive, subjective | Sincere, reflective, sentimental |
| Character naming | Archetypes only | Real names | Real names |
| Main hook | `注意看` and conflict/shock | Immediate lived tension | Emotional truth / life meaning |
| Pacing | Fast, information-dense | Suspense-led | Measured, lingering |
| Best fit | Genre / action / plot-heavy movies | Character-centered movies | Classics, dramas, emotional films |

---

## Open Style Work

### Priority 1 — Finish Style C

1. Transcribe `transcripts/xiaodao_greenline.mp3`.
2. Extract the real opening pattern, transition phrases, and ending style.
3. Write `styles/xiaodao.md` in the same level of detail as `styles/niu-shu.md`.

### Priority 2 — Design Style B

1. Define protagonist selection logic.
2. Define knowledge-boundary rules.
3. Define emotional calibration rules.
4. Write `styles/first-person-pov.md`.

### Priority 3 — Refine Style A With Transcript Evidence

1. Measure how fast Uncle Niu actually moves through plot beats.
2. Check how often he re-hooks the audience.
3. Verify whether the current 10-minute structure in `styles/niu-shu.md` matches the real samples.

---

## Recommended Style Work Order

Use this order unless the project direction changes:

1. Finish Xiaodao transcript.
2. Write `styles/xiaodao.md`.
3. Draft `styles/first-person-pov.md`.
4. Revisit `styles/niu-shu.md` with transcript-based refinements.

This keeps the style library moving forward without blocking the main parser/transcription engineering work.

---

## Session Log

### 2026-03-31

- Downloaded 7 Uncle Niu audio files.
- Researched archetype naming, opening hooks, and transition phrases.
- Wrote `styles/niu-shu.md`.
- Prepared Uncle Niu voice-cloning sample clips.

### 2026-04-01

- Identified Xiaodao as the Style C candidate.
- Downloaded `transcripts/xiaodao_greenline.mp3`.
- Analyzed 40 Xiaodao video titles and documented the research in `docs/style-c-xiaodao-research.md`.

### 2026-04-06

- Reviewed the repository against the earlier planning docs.
- Confirmed that Style A is supported by real transcript assets.
- Confirmed that Style C is still blocked only by transcription and file writing.
- Realigned this tracker so it reflects the actual repository state rather than the earlier research-only snapshot.

---

## Short Summary

Style A is the only finished style file today. Style C has enough research to become the next completed style once the Xiaodao audio is transcribed. Style B is still a blank page and should be treated as a design task after Style C is grounded in real transcript data.