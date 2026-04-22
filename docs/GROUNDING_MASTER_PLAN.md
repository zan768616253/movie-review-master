# Grounding Master Plan: The 100% Alignment Specification (V5)

**Status:** Final Technical Specification (Updated for Gemini 3 Flash)
**Objective:** Solve the "40% Mismatch" via **Visual Grounding** and **Segment-based Anchoring**.

---

## 1. Technical Diagnosis: The "Grounding Failure"
The mismatch is a failure of **Visual Anchoring**.
- **Information Asymmetry:** Stage 2 (Scripting) guesses timestamps without seeing the video.
- **I-Frame Jitter:** Fast extraction (`-c:v copy`) causes ±2s drift.
- **Rigid Rendering:** Mathematical time-splitting and "freeze-padding" make timing errors obvious.

---

## 2. Stage 0: Visual Indexing (The Eyes)

### Option A: Gemini 3 Flash (10-Min Native Chunks) - [PRIMARY]
- **Model:** `gemini-3-flash` (Optimized for high-fidelity video understanding and precise time-alignment).
- **Workflow:** Split movie into ~9-10 segments. Gemini "watches" each for motion, character presence, and scene transitions.
- **Output:** `visual_segments.json` (Segment-based schema).
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
- **Output:** Point-based map, must be "collapsed" into segments during Pass 2.

---

## 3. The Multi-Pass Workflow

### Stage 2a: Creative Writing (The Writer)
LLM writes the "Uncle Niu" narration focusing only on tone, plot, and character archetypes. **Ignore timestamps here.**

### Stage 2b: Grounded Anchoring (The Editor)
A second LLM pass (Claude Code) takes the **Script + Full SRT + visual_segments.json**.
- **Task:** Match narration beats to the *actual* visual segment that contains that action.
- **Output:** Script with `[SCENE]` and `[BROLL]` markers pointing to verified boundaries.

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
1.  **Visual Evidence Score:** >95% of `[SCENE]` markers have a corresponding entry in `visual_segments.json`.
2.  **Padding Ratio:** <10% of segments require B-roll insertion or freezing to match audio.
3.  **Frame Accuracy:** Zero "Keyframe Jitter" (confirmed via re-encoding).
4.  **Human Score:** The "90-Second Slice Test" achieves a "No visible drift" rating from the user.

---

## 6. Implementation Roadmap
1.  **Task 1:** Create `app/tools/visual_segments_generator.py` (Default to Gemini 3 Flash).
2.  **Task 2:** Update Stage 2 prompt to accept the segment map and full SRT.
3.  **Task 3:** Fix Stage 4 extraction flags and Stage 5 padding logic.
