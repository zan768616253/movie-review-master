# Product Requirements Document: movie-review-master

`PROD.md` is the root project document. It defines the product scope and points to the small set of remaining source-of-truth docs:

- [docs/HANDBOOK.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/HANDBOOK.md) for stable knowledge, design, and pipeline rules
- [plan.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/plan.md) for current progress and next work
- [docs/TECHNICAL.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/TECHNICAL.md) for coding-facing contracts and implementation reference

## 1. Product Goal

`movie-review-master` turns a movie file plus subtitles into a draft long-form movie-review video package:

- a chronological rough cut of high-information shots
- a narration script written against that rough cut
- an AI-generated voiceover
- a watchable draft render with burned subtitles
- separate assets that can be refined in DaVinci Resolve

The product is not trying to replace the final edit. It is trying to produce a strong first-pass review package that is fast to polish manually.

## 2. Target Workflow

The pipeline follows a **video-driven** ordering: visuals are picked first, narration is written against those visuals, audio is generated, then visuals are trimmed to fit the actual audio. This deliberately inverts an earlier "audio-first" design that produced structural sync mismatches.

The intended user flow is:

1. Provide a movie file and subtitle file.
2. Run shot detection.
3. Pick the high-information shots that should appear in the review.
4. Assemble a rough cut from those shots, ordered chronologically into 30–60s narrative beats.
5. Write one narration line per beat in the chosen review style.
6. Generate the voiceover.
7. Trim each beat's micro-shots so they match the actual audio duration.
8. Render a draft review video with burned subtitles.
9. Open the output folder in DaVinci Resolve for final polish and export.

Steps 3 and 5 are manual in the first iteration; everything else is automated. Each manual step is designed as a replaceable module so it can be automated incrementally.

## 3. Inputs

Required inputs:

| Input | Format | Notes |
|------|--------|-------|
| Movie | `.mp4` or `.mkv` | Full-length source movie |
| Subtitles | `.srt` or `.ass` | UTF-8 preferred; can be explicitly passed even if filename stem differs from the movie |

Preferred operating rule:

- Keep movie and generated assets inside the WSL filesystem, not under `/mnt/c/...`.
- Use subtitles as the primary plot context for narration writing.
- Treat direct audio transcription as fallback support, not the primary pipeline path.

## 4. Outputs

The main deliverable is a DaVinci-ready output folder next to the source movie.

Expected asset set:

```text
movies/<title>/
  output/
    review.mp4
    final_video.mp4
    rough_cut/                # selected-shot concatenation, beat-segmented
    fitted/                   # per-beat videos trimmed to TTS duration
    keyframes/                # fallback stills
  voiceover_<style>_voiceclone.mp3
  voiceover_<style>_voiceclone.manifest.json
  selected_shots.json
  narration.json
```

Product-level output rules:

- `review.mp4` is the watchable draft render.
- `final_video.mp4` is the upload-ready master emitted after final muxing.
- Original movie audio is not part of the review timeline.
- Separate assets must remain reusable so manual editing in DaVinci is easy.

## 5. Supported Review Styles

### Style A: Uncle Niu

- Third-person omniscient narrator
- Deadpan, fast, sarcastic
- Uses archetype nicknames instead of original character names
- Best fit for genre, action, thriller, and high-plot-density reviews

### Style B: First-Person Protagonist POV

- First-person confessional narrator
- Emotional, subjective, character-driven
- Uses original character names
- Best fit for immersive, protagonist-centered retellings

### Style C: Xiaodao

- Planned style direction
- Warm, reflective, emotional storyteller
- Uses original character names
- Best fit for dramas, classics, and high-emotion films

## 6. Functional Requirements

The product must:

1. Accept `.mp4` and `.mkv` movies plus `.srt` or `.ass` subtitles.
2. Detect shot boundaries and emit a per-shot summary.
3. Allow a human (v1) or scorer (v2) to select the high-information subset.
4. Assemble a rough cut from the selection, segmented into narrative beats.
5. Support style-constrained narration writing per beat.
6. Produce an AI voiceover track from the per-beat narration.
7. Trim each beat's micro-shots to fit the actual TTS duration.
8. Render a playable draft review video with burned subtitles.
9. Preserve separate assets needed for manual post-production.

## 7. Quality Requirements

The draft pipeline should produce:

- Chinese output as the primary path
- Visuals and narration that describe the same beat at the same time
- Mostly motion footage, not a slideshow
- Readable on-screen subtitles aligned to actual speech pauses
- Consistent voiceover loudness
- A folder structure that imports cleanly into DaVinci Resolve

## 8. Operating Constraints

- Primary runtime environment: WSL2 Ubuntu with an RTX 4060.
- Final polish/export environment: DaVinci Resolve on Windows.
- `ffmpeg` is the core media tool.
- Local TTS is preferred over paid hosted TTS.
- The design assumes Chinese-language narration first, with English as secondary support.

## 9. Success Criteria

A successful run means:

1. The project produces a playable `final_video.mp4`.
2. The voiceover, narration, rough cut, and manifests all exist.
3. The draft covers the full plot arc.
4. The chosen style's narrative rules are visibly followed.
5. The output folder is practical to reopen and finish in DaVinci Resolve.

## 10. Out of Scope

Not part of the core product target right now:

- automatic YouTube upload
- fully autonomous final mastering
- multi-movie batch orchestration
- advanced motion graphics packages
- AI-generated background music
