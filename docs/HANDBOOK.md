# Movie-Review-Master Handbook

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

### `[SCENE: HH:MM:SS-HH:MM:SS]`

The primary synchronization marker. Each `[SCENE]` binds one narration chunk to one source-movie visual range.

Rules:

- one primary narration beat maps to one `[SCENE]`
- `[SCENE]` timestamps should point to the exact visual beat being described
- the marker is for pipeline coordination, not for spoken narration

### `[BROLL: ...]`

Optional supplemental visual ranges attached to the current scene. These are used to improve visual energy and genre fit when the primary scene alone is not enough.

### Narration Chunk

The unit of alignment between script, TTS, and rendering. In the current design, chunk boundaries follow scene boundaries.

### Voiceover Manifest

The manifest is the sync contract between audio generation and rendering. It records, in order:

- which script chunk was spoken
- which `[SCENE]` it belongs to
- where that chunk starts and ends inside the final concatenated voiceover
- any attached B-roll ranges

### Draft Render

`final_video.mp4` is a watchable draft. It is intentionally not the project’s final master. The master is expected to be produced after manual finishing.

## 5. End-to-End Pipeline Design

The logical pipeline has six stages.

### Stage 0: Visual Indexing

Purpose:

- provide fine-grained visual search metadata for the full movie
- generate `visual_segments.json` containing 3-5 second action beats
- solve the visual grounding gap by providing timestamps for non-dialogue moments

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
- include structural markers for visuals and later alignment

The script stage must do two jobs at once:

1. create engaging narration
2. define enough structure for the media pipeline to remain deterministic

Stable rules:

- the hook must front-load attention
- the full story arc must be covered
- style rules come from the chosen file in `styles/`
- scene markers must be specific and usable

### Stage 3: Voiceover Generation

Purpose:

- turn the script into a single narration track
- retain chunk timing through a manifest

Design decisions:

- TTS output is chunked by script structure, then concatenated
- the final voiceover is one audio file plus one timing manifest
- loudness normalization happens before render assembly

### Stage 4: Visual Extraction

Purpose:

- extract silent source clips for each primary scene
- extract fallback keyframes
- optionally extract B-roll clips attached to the same narration chunk

The extracted clips are not supposed to carry movie audio. The review soundtrack is built around narration-first timing.

### Stage 5: Draft Render

Purpose:

- shape clip timing around narration timing
- assemble a coherent watchable draft
- keep enough intermediate structure for debugging and manual refinement

Stable render rules:

- narration duration is authoritative
- clips are trimmed, padded, or replaced with stills to fit narration timing
- the first working render can favor determinism over polish
- later iterations add transitions, subtitles, and richer audio mixing

### Post-Pipeline: DaVinci Handoff

The output folder is meant to be reopened and improved manually. This is part of the design, not a failure of automation.

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
- Style A reference audio should come from `voice-assets/uncle_niu/reference/`
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

### Video Processing

- `ffmpeg` is the baseline media engine
- extracted review clips are silent
- source video can be stream-copied where possible for speed

### Render Synchronization

- the manifest is the contract between TTS and render
- audio timing drives visual timing
- scene and B-roll markers are part of the script contract, not optional decoration

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

Shared voice assets live outside per-movie folders:

```text
voice-assets/
  uncle_niu/
    analysis/
    reference/
  first_person_pov/
    analysis/
  xiaodao/
    analysis/
```

Naming rules:

- style-tagged files make side-by-side experiments possible
- manifest filename must track the voiceover filename
- output assets stay grouped under the movie directory, not in a global build folder
- `analysis/` holds audio and transcript pairs used for style study
- `reference/` holds the canonical clone source for a reusable voice profile
- Style A defaults to `voice-assets/uncle_niu/reference/clone_reference.{mp3,txt}`

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
