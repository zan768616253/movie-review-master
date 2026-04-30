# Movie-Review-Master Handbook

> **NOTE (2026-04-27):** Stage 2 is being rewritten on the `develop` branch
> from a two-pass writer + grounder into a single planner-writer that
> co-plans visual anchors and narration. While that is in flight, the
> Stage 2 / Stage 5 sections below describe the **current** behaviour, not
> the target. See [`OVERHAUL_PLAN.md`](OVERHAUL_PLAN.md) for the target
> architecture and phased plan.

This handbook is the central source of truth for stable project knowledge: concepts, design decisions, pipeline logic, conventions, and style-system rules. It is intentionally not a progress log.

## 1. Documentation Map

Use each document for one job only:

- [PROD.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/PROD.md): product scope, success criteria, boundaries
- [docs/HANDBOOK.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/HANDBOOK.md): durable knowledge and system design
- [plan.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/plan.md): current status, priorities, next work
- [docs/TECHNICAL.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/TECHNICAL.md): code-facing architecture, contracts, pipeline, tools, tests
- `styles/*.md`: style-specific writing rulebooks
- [docs/style-c-xiaodao-research.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/style-c-xiaodao-research.md): supporting research for the unfinished Style C
- [docs/agent-rules/python-environment.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/agent-rules/python-environment.md): Python execution rule

## 2. System Goal

The project turns a full movie plus subtitles into a draft long-form review package. The package is designed for fast human finishing, not for fully autonomous final publishing.

The handoff model is deliberate:

- automation produces a draft render and all reusable assets
- DaVinci Resolve is used for final polish, retiming, and export
- source assets stay separate so edits remain flexible

## 3. Operating Model

The system is split across two environments:

- WSL2 Ubuntu runs Python, TTS, transcription, `ffmpeg`, and the build pipeline
- Windows runs DaVinci Resolve for manual finishing and export

Project assumptions:

- GPU: RTX 4060 class hardware
- primary language: Chinese
- primary plot source: subtitle text
- primary media tool: `ffmpeg`

## 4. Core Concepts

### Source Movie

The full `.mp4` or `.mkv` file that all clips are extracted from.

### Subtitle Source

The `.srt` or `.ass` file used to reconstruct plot structure, find dialogue anchors, and guide scene selection.

### Review Script

A style-constrained narration document that retells the full movie in review form. The script is not plain prose only; it also carries structural markers used by later pipeline steps.

### `[ANCHOR ...]`

The primary synchronization marker. Each `[ANCHOR]` binds one narrative beat to one or more source-movie shot ranges, with the narration text directly below it sized to fit those ranges.

Form:

```
[ANCHOR ranges="HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS" characters="Name A|Name B"]
narration text bounded by sum_of_range_seconds × chars_per_second
```

Rules:

- one narrative beat maps to one `[ANCHOR]`
- ranges are chronological `start-end` pairs from `[shot:NNN]` lines (not `[srt:NNN]`)
- each range must stay inside ONE source shot (the validator rejects shot-boundary crossings)
- each individual range duration ≤ 12s; each anchor's total range duration ≤ 12s
- multi-shot beats use multi-range anchors with one range per shot
- narration char count ≤ `sum(range_seconds) × chars_per_second` (the per-style planner budget)
- the marker is for pipeline coordination, not for spoken narration
- the `[CLOSING]` section contains narration but no `[ANCHOR]` — Stage 6 plays it over the most recent keyframe

### Narration Chunk

The unit of alignment between script, TTS, and rendering. Each `[ANCHOR]` block is one chunk; the closing passage (no anchor) is its own chunk.

### Voiceover Manifest

The manifest is the sync contract between audio generation and rendering. It records, per chunk:

- which script chunk was spoken
- the chunk's `ranges` (the source-movie windows the planner picked) and `characters`
- where that chunk starts and ends inside the final concatenated voiceover

### Subtitle Manifest

The subtitle manifest is the sync contract between Stage 4 and the draft renderer.
It records, in order:

- which chunk a subtitle cue belongs to
- the exact cue text shown on screen
- where that cue starts and ends inside the final concatenated voiceover

### Draft Render

`review.mp4` is the Stage 6 watchable draft. `final_video.mp4` is the Stage 7 upload-ready master created by remuxing the Stage 6 picture lock with the Stage 3 narration track.

## 5. End-to-End Pipeline Design

The logical pipeline has eight stages.

### Stage 0: Visual Indexing

Purpose:

- provide visual-only search metadata for the full movie
- generate `visual_segments.json` containing event-based segments (typical 2-8s, hard cap 12s) that cover action beats, reactions, transitions, and establishing shots

Grounding strategy:

- subtitles are the primary anchor for dialogue; Stage 0 exists to cover the non-dialogue gap, not to redescribe subtitle-covered moments
- the VLM is explicitly told to skip shot-reverse-shot dialogue scenes, since dialogue beats are grounded via SRT
- VLM chunking is only an input batching concern; a full movie should still yield many event-level candidates rather than a handful of broad summaries
- downstream matching works best when each segment describes one distinct visual event with characters and OCR when available

Timestamp accuracy (Gemini Fast):

- each chunk has its chunk-local PTS (HH:MM:SS.mmm) burned into the top-left corner of every frame so the VLM reads timestamps off the image instead of estimating them
- after inference, every segment's `start` and `end` are snapped to the nearest ffmpeg-detected shot cut within 1.5s; outside that tolerance the original timestamp is kept
- chunks are 5 minutes each to reduce context drift; this also gives the validator less room for long-range hallucinated spans

VLM trust boundary:

- VLMs (both Gemini and local Qwen2.5-VL) routinely return timestamps that exceed the movie duration or span implausible ranges. Stage 0's output is only trusted after it has been passed through `validate_visual_segments`, which clamps `end` to the real video duration, drops segments with inverted or out-of-range times, and drops segments longer than `MAX_VISUAL_SEGMENT_DURATION_S` (30s). Downstream stages must use the validated file, not the raw model response.

### Stage 1: Subtitle Intake

Purpose:

- normalize subtitle formats into downstream-friendly text and structured data
- preserve timing so later steps can recover exact scene locations

Accepted subtitle formats:

- `.srt`
- `.ass`

Design expectation:

- plain-text output is useful for reading and grep-style scene discovery
- structured output is useful for tooling and future automation

### Stage 2: Script Authoring

Purpose:

- convert movie plot into a review script in the selected style
- bind narration to specific source-movie shots via `[ANCHOR]` markers

Single-pass planner-writer (replaces the legacy writer + grounder two-pass design):

- one LLM call picks visual anchors AND writes narration in the selected style
- the prompt carries the style rulebook verbatim, an optional synopsis, and a chronological timeline mixing `[srt:NNN]` dialogue lines with per-shot `[shot:NNN]` entries
- each anchor is constrained by `chars(narration) ≤ sum(range_seconds) × chars_per_second` so narration can never outlast the chosen visuals — Stage 6 trims any small video slack shot-aware
- final output is an `[ANCHOR]`-bound script ready for Stage 3 audio generation

Shot-aware range contract:

- each anchor range stays inside ONE source shot (no shot-boundary crossings)
- each range duration ≤ 12s; each anchor's total duration ≤ 12s
- multi-shot beats use multi-range anchors with one range per shot
- range timestamps come from `[shot:NNN]` lines, not `[srt:NNN]` — SRT timestamps mark speech onset, not shot cuts
- the validator (`validate_anchored_script`) enforces all of the above against `build_shot_boundary_set(visual_segments)`

Why the contract: per-chunk durations are matched at the rendering layer, but inside an anchor audio runs at a uniform pace while source video runs at the editor's pace. Long anchors that span multiple internal beats let those paces diverge by several seconds, producing the perception that audio is "ahead" of the video describing the same beat. Constraining each range to one shot keeps every visible moment a single editorial beat, so audio cannot describe content the audience isn't yet watching.

The script stage must do two jobs at once:

1. create engaging narration in the chosen style's voice
2. bind that narration to shot-aligned ranges so the media pipeline plays content the audience is hearing about

Stable rules:

- the hook must front-load attention
- the full story arc must be covered
- style rules come from the chosen file in `styles/`
- ranges are shot-atomic; narration is sacred (never auto-trimmed)

### Stage 3: Voiceover Generation

Purpose:

- turn the script into a single narration track
- retain chunk timing through a manifest

Design decisions:

- TTS output is chunked by script structure, then concatenated
- the final voiceover is one audio file plus one timing manifest
- loudness normalization happens before render assembly

### Stage 4: Subtitle Alignment

Purpose:

- split long narration chunks into shorter subtitle cues
- align those cues to the real Stage 3 voiceover timing using pause detection
- emit a subtitle manifest that later stages can burn into the draft render

Stable alignment rules:

- cue timing is derived from the actual synthesized audio, not from character counts alone
- cue text stays in script order and never crosses chunk boundaries
- when the audio exposes clear pauses, cue boundaries should prefer those pauses
- when the audio has no usable pause inside a chunk, the stage may split timing proportionally inside that chunk rather than fabricating still more structure upstream

### Stage 5: Visual Extraction

Purpose:

- extract silent source clips for each primary scene
- extract fallback keyframes
- optionally extract B-roll clips attached to the same narration chunk

The extracted clips are not supposed to carry movie audio. The review soundtrack is built around narration-first timing.

High-precision extraction rules:

- primary hero clips are re-encoded instead of stream-copied so short beats do not drift on keyframe boundaries
- each extraction includes pre/post handles so Stage 6 can absorb small timing mismatches without an immediate freeze
- safe-boundary extension may stretch past the requested `end`, but only inside a capped window after Stage 0 validation has already clamped the visual index to the real movie duration

### Stage 6: Draft Render

Purpose:

- shape clip timing around narration timing
- assemble a coherent watchable draft
- keep enough intermediate structure for debugging and manual refinement

Stable render rules:

- narration duration is authoritative
- renderer follows a fixed fallback order: exact hero window, then extracted handles or safe-boundary extension, then explicit or semantic B-roll, then freeze as the last fallback
- B-roll is a style tool; hard freezes are a grounding failure signal and should stay rare
- subtitle timing should come from the Stage 4 subtitle manifest, not from one chunk-wide caption event
- the first working render can favor determinism over polish
- later iterations add transitions and richer audio mixing

### Stage 7: Upload Finalize

Purpose:

- preserve the Stage 6 picture lock
- remux the Stage 3 narration track onto that draft
- emit an upload-ready MP4 with `+faststart`

Stable finalize rules:

- Stage 7 takes video from `review.mp4`, not from the source movie
- Stage 7 takes audio from the Stage 3 voiceover, even if the Stage 6 draft already has muxed narration
- the final master should be directly playable and ready for YouTube upload without a manual remux step

### Post-Pipeline: DaVinci Handoff

The output folder is meant to be reopened and improved manually. This is part of the design, not a failure of automation.

### Grounding Quality Signals

Use these targets when judging whether alignment quality is acceptable:

- range provenance: every `[ANCHOR]` range should overlap a real `[shot:NNN]` or `[srt:NNN]` entry from the timeline; the validator's `range_provenance` check catches fabricated timestamps
- shot alignment: zero `range_shot_crossing` validator failures — every range stays inside one source shot
- freeze ratio should stay below 1% of runtime outside the closing chunk; smart-trim slack absorbs most timing mismatches without freezing
- extension-needed ratio should stay below 5%; chunks where audio overruns the chosen ranges fall back to post-handle extension and risk a still-fill
- hero clips should show no visible keyframe jitter
- a short slice review should read as "no audio-visual drift" to a human viewer

## 6. Style System

The project is built around style-specific narration rulebooks.

### Style A: Uncle Niu

- detached third-person narrator
- deadpan sarcasm
- archetype nicknames instead of original names
- best for high-energy or high-plot-density reviews

Source of truth: [styles/niu-shu.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/styles/niu-shu.md)

### Style B: First-Person Protagonist POV

- protagonist-led confession
- emotional, intimate, subjective narration
- original names are preserved

Source of truth: [styles/first-person-pov.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/styles/first-person-pov.md)

### Style C: Xiaodao

- warm narrator voice
- reflective, emotional, meaning-driven framing
- intended for classics, dramas, and high-emotion stories

Current research reference: [docs/style-c-xiaodao-research.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/style-c-xiaodao-research.md)

## 7. Technology Decisions

These are the cross-project decisions that should stay consistent unless deliberately replaced.

### Subtitle Parsing

- treat subtitle text as the primary semantic input
- support `.srt` and `.ass`
- preserve timing as numeric seconds for tooling

### TTS

- local TTS is preferred
- Qwen3-TTS has three relevant generation modes:
  - Voice Clone: clone from reference audio plus transcript
  - Custom Voice: use built-in preset speakers
  - Voice Design: synthesize a voice from a natural-language description
- Style A currently standardizes on Qwen3-TTS Voice Clone on the Base model, not Custom Voice and not Voice Design
- Stage 3 should receive the same `--style` input used in Stage 2, then default the voice reference from `styles/voice-assets/<style>/reference/`
- styles without a canonical `reference/clone_reference.{mp3,txt}` pair yet still need explicit `--ref-audio` / `--ref-text` overrides
- narration should be generated chunk-by-chunk on script scene boundaries, then concatenated into one voiceover file plus one manifest
- long-form output should be loudness-normalized before render assembly
- fallback hosted/preset TTS is acceptable only when the main local path is unavailable

### TTS Voice Characteristics For Style A

Useful distilled knowledge from the earlier validation work:

- target pace is fast, roughly around 6 Chinese characters per second
- delivery should feel dry, deadpan, and storyteller-like rather than theatrical
- short pauses work better than long dramatic pauses
- the winning implementation path favored recognizability of timbre over purely description-driven synthesis

### TTS Reference-Audio Caveats

- some older Uncle Niu sample files are mislabeled by nominal duration, so filenames alone are not a reliable measurement source
- background music in source samples can distort pitch and pause analysis
- if voice analysis is needed again, use a cleaner harmonic-focused measurement path instead of trusting raw full-mix readings
- a good fresh voice-clone reference should stay relatively short and clean; the current repo policy targets a 90-second single-speaker dialogue reference for ICL preparation, but shorter clips are still preferable when they capture the voice well
- Stage 3 now expects a prepared short transcript-conditioned ICL reference rather than trying to adapt long clips at runtime

### Video Processing

- `ffmpeg` is the baseline media engine
- extracted review clips are silent
- timing-critical hero clips are re-encoded instead of stream-copied so `[ANCHOR]` range boundaries stay stable
- GPU encoding is the default path on this project's target hardware (RTX 4060). Stages 4 and 5 pick `h264_nvenc` when the local ffmpeg advertises it, and fall back to `libx264 -preset fast` so CI and non-GPU hosts still work. Falling back to CPU encoding is expected to be 3-5x slower on 1080p re-encodes, which is acceptable but not a path to production throughput.

### Render Synchronization

- the manifest is the contract between TTS and render
- audio timing drives visual timing
- scene and B-roll markers are part of the script contract, not optional decoration
- grounded scene metadata such as `source`, `evidence`, and optional `characters` is part of that sync contract when available

### Rendering Baseline

- the first stable renderer should prefer deterministic alignment over visual polish
- stage-1 rendering can use hard cuts and stillframe fallback
- later polish layers include transitions, subtitles, and background-music mixing, but they should not weaken the core sync contract

## 8. Asset Model and Naming Conventions

Per-movie working directory:

```text
movies/<title>/
  <title>.mkv or <title>.mp4
  <subtitle>.srt or <subtitle>.ass
  <title>.txt or <title>.json
  script_<style>_draft.txt
  voiceover_<style>_voiceclone.mp3
  voiceover_<style>_voiceclone.manifest.json
  output/
    clips/
    keyframes/
    segments/
    final_video.mp4
```

Shared voice assets live under the `styles/` tree rather than inside per-movie folders:

```text
styles/
  niu-shu.md
  first-person-pov.md
  voice-assets/
    niu-shu/
      analysis/
      reference/
    first-person-pov/
      analysis/
    xiao-dao/
      analysis/
```

Naming rules:

- style-tagged files make side-by-side experiments possible
- manifest filename must track the voiceover filename
- output assets stay grouped under the movie directory, not in a global build folder
- `analysis/` holds audio and transcript pairs used for style study
- `reference/` holds the canonical clone source for a style when that style has a default reusable voice
- the default Stage 3 output tag should match the style filename stem unless the caller explicitly overrides it

## 9. Environment Rules

Python execution and dependency management are standardized:

- use the `py312_machine_learning` conda environment
- follow [docs/agent-rules/python-environment.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/agent-rules/python-environment.md) as the canonical command rule
- treat `pyproject.toml` as the dependency source of truth

## 10. Design Principles

These principles explain many of the specific choices above.

### Narration-First Assembly

The review is paced by the narration, not by the original film edit. Visuals are selected to serve the narration.

### Deterministic Contracts

Marker-driven contracts are preferred over fuzzy matching whenever possible. This is why scene markers and manifests are important.

### Draft First, Polish Later

The pipeline should first produce something coherent, inspectable, and re-editable. Production polish can be layered on once the deterministic path is stable.

### Keep Stable Knowledge Separate From Session Logs

Implementation status changes often. Core concepts and design rules should not.
