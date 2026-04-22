# Grounding Master Plan: The 100% Alignment Specification (V6)

**Status:** Draft — pending de-risk prototype (see §6, Task 0)
**Objective:** Solve the "40% Mismatch" via **SRT-first anchoring**, **visual gap-filling**, and a **dedicated alignment pass**.

---

## 1. Technical Diagnosis: The "Grounding Failure"
The mismatch is a failure of **Visual Anchoring**.
- **Information Asymmetry:** Stage 2 (Scripting) guesses timestamps without seeing the video.
- **I-Frame Jitter:** Fast extraction (`-c:v copy`) causes ±2s drift.
- **Rigid Rendering:** Mathematical time-splitting and "freeze-padding" make timing errors obvious.

### What we already have (and under-use)
The SRT file contains frame-accurate, ground-truth timestamps for every line of **dialogue**. For any narration beat that references a line someone says, SRT alone solves alignment — no VLM needed. Visual grounding is only required for **non-dialogue** moments: action beats, reactions, establishing shots, silent transitions. Treating SRT as primary anchor (not just input) is the cheapest win in this plan.

---

## 2. Stage 0: Visual Indexing (The Eyes)

**Scope:** Visual indexing covers the ~30-50% of movie time that is *not* dialogue. Dialogue moments come from SRT. Do not re-describe what subtitles already tell us.

### Granularity clarification
- **Input chunks:** movie is split into ~10-minute chunks for the VLM (context-window reason, not output granularity).
- **Output segments:** each chunk returns **many** fine-grained segments (target: one segment per distinct shot/action, typically 3-15s long). A 2hr movie should produce ~400-800 segments, not 9-10.

### Option A: Gemini 3 Flash (10-Min Native Chunks) - [PRIMARY, PENDING VALIDATION]
- **Model:** `gemini-3-flash` — claimed to support video-native understanding with timestamp grounding. **Must be validated in Task 0 before the rest of this plan commits to it.**
- **Workflow:** Feed each 10-min chunk to Gemini with a prompt asking for segment-level output (schema below). Prompt must explicitly request: shot boundaries, character identities (provided via a name→face reference sheet), action verbs, OCR of any on-screen text.
- **Output:** `visual_segments.json`
- **Schema:**
  ```json
  {
    "start": "00:05:10.500",
    "end": "00:05:18.200",
    "summary": "Hero punches villain, rain starts falling.",
    "ocr_text": "SIGN: NO PARKING",
    "is_action": true,
    "confidence": 0.99,
    "characters": ["Uncle Niu", "Rebel Girl"]
  }
  ```

### Option B: Local RTX 4060 + Qwen2.5-VL (3s Samples) - [FALLBACK]
- **Workflow:** Extract JPGs every 3s. Local VLM describes each.
- **Collapse rule:** adjacent frames are merged into one segment when (a) summary cosine similarity > 0.85 AND (b) character set is identical. Breaks produce segment boundaries.
- **Output:** same schema as Option A after the collapse step.

---

## 3. The Multi-Pass Workflow

### Stage 2a: Creative Writing (The Writer)
LLM writes the "Uncle Niu" narration focusing only on tone, plot, and character archetypes. **Ignore timestamps here.** Output: plain narration broken into **beats** (one sentence or short paragraph = one beat).

### Stage 2b: Grounded Anchoring (The Editor) — *the critical pass*
A second LLM pass takes **Narration Beats + Full SRT + visual_segments.json** and picks the best movie timestamp for each beat.

**Matching algorithm (per beat):**
1. **Classify the beat** as `DIALOGUE` (references something a character says) or `ACTION` (references something that happens visually).
2. **If DIALOGUE:** search SRT for the quoted/paraphrased line using keyword + semantic similarity. SRT timestamp wins. Visual segments are ignored.
3. **If ACTION:** search `visual_segments.json`. Rank candidates by:
   - Character-set overlap with the beat (hard filter: required characters must be present).
   - Semantic similarity between beat text and segment `summary`.
   - `is_action` flag if the beat describes motion.
4. **Confidence gate:** if top candidate score < threshold, mark the beat as `UNGROUNDED` rather than hallucinating a timestamp. Stage 4 will use generic B-roll from the same character pool instead.

**Output:** Script annotated with `[SCENE start=... end=... source=srt|visual confidence=...]` markers. Every marker must cite its evidence (SRT line number or visual segment ID).

### Alternative flow to consider: "Edit first, write to picture"
The current plan writes narration, *then* finds clips. The inverse — pre-select hero clips from SRT + visual index first, *then* write narration constrained to those clips — eliminates most of Stage 5's padding logic because beat duration is known up front. Worth prototyping against the current flow on the same 90-second slice before committing.

---

## 4. Stage 4 & 5: Precision Execution

### Stage 4: High-Precision Extraction
- **Rule:** Stop using `-c:v copy` for hero clips.
- **Action:** Re-encode with `-c:v libx264`.
- **Feature:** Add **±1.5s Handles**. If the script asks for 5s, extract 8s.

### Stage 5: Cinematic Padding Priority
When narration duration > clip duration, the renderer follows this priority:
1.  **Handles:** Use the extra 1.5s of pre/post-roll.
2.  **Shot Extension:** If the segment hasn't ended, keep playing into the next "safe" visual boundary.
3.  **Semantic B-Roll:** Pull a clip from the same "Tag" or "Character" pool in Stage 0.
4.  **Freeze (Last Resort):** Only freeze for <0.5s leftovers. **Never loop movie footage.**

---

## 5. Success Criteria & Metrics

We will consider the mismatch "Solved" when:
1.  **Evidence Coverage:** >95% of `[SCENE]` markers cite either an SRT line number or a `visual_segments.json` segment ID. (Renamed from "Visual Evidence" — SRT citations count too.)
2.  **Freeze Ratio:** <5% of final runtime is filled by freeze-frames. *(B-roll is a feature of the style, not a failure — only hard freezes indicate a timing failure.)*
3.  **Frame Accuracy:** Zero "Keyframe Jitter" (confirmed via re-encoding).
4.  **Ungrounded Beat Rate:** <10% of narration beats come back from Stage 2b as `UNGROUNDED`. If it's higher, either the narration is drifting from the movie or the visual index is too sparse.
5.  **Human Score:** The "90-Second Slice Test" achieves a "No visible drift" rating from the user.

---

## 6. Implementation Roadmap

### Task 0: De-risk prototype (do this first, ~1 day)
Before writing any pipeline code, validate the two highest-risk assumptions on **one 10-min chunk** of Jujutsu Kaisen 0:
- **0a.** Send the chunk to Gemini 3 Flash with the segment schema prompt. Check: does it actually return sub-second timestamps? Does it identify characters by name when given a reference sheet? Cost per chunk?
- **0b.** Hand-write the Stage 2b matching prompt. Take 5 narration beats from an existing Uncle Niu script and see if Claude picks the correct SRT line / visual segment for each. If it can't reliably match with the data provided, the rest of this plan won't help.

**Gate:** only proceed to Task 1 if both prototypes pass. If 0a fails, fall back to Option B (local Qwen2.5-VL). If 0b fails, redesign the matching prompt before building anything.

### Task 1: Visual index generator
Create `app/tools/visual_segments_generator.py`. Output must conform to the schema in §2. Include the collapse logic if Option B is used.

### Task 2: Stage 2 two-pass refactor
- **2a:** narration writer prompt (no timestamps).
- **2b:** grounding/matching prompt implementing the algorithm in §3. Outputs annotated script with evidence citations.

### Task 3: Stage 4 & 5 fixes
Re-encode hero clips, add handles, implement the padding priority in §4.

### Task 4: Measurement harness
Script that runs the 90-second slice test and reports the metrics in §5. Without this, "solved" is subjective.
