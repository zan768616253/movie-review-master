# Product Requirements Document: movie-review-master

`PROD.md` is the root project document. It defines the product scope and points to the small set of remaining source-of-truth docs:

- [docs/HANDBOOK.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/HANDBOOK.md) for stable knowledge, design, and pipeline rules
- [plan.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/plan.md) for current progress and next work
- [docs/TECHNICAL.md](/home/ericw/Project/Learn/AI/agent-skills/movie-review-master/docs/TECHNICAL.md) for coding-facing contracts and implementation reference

## 1. Product Goal

`movie-review-master` turns a movie file plus subtitles into a draft long-form movie-review video package:

- a narration script
- an AI-generated voiceover
- extracted review clips and fallback keyframes
- a watchable draft render
- separate assets that can be refined in DaVinci Resolve

The product is not trying to replace the final edit. It is trying to produce a strong first-pass review package that is fast to polish manually.

## 2. Target Workflow

The intended user flow is:

1. Provide a movie file and subtitle file.
2. Choose a review style.
3. Generate or refine the review script.
4. Generate voiceover audio.
5. Extract scene clips and fallback stills.
6. Render a draft review video.
7. Open the output folder in DaVinci Resolve for final polish and export.

## 3. Inputs

Required inputs:

| Input | Format | Notes |
|------|--------|-------|
| Movie | `.mp4` or `.mkv` | Full-length source movie |
| Subtitles | `.srt` or `.ass` | UTF-8 preferred; can be explicitly passed even if filename stem differs from the movie |

Preferred operating rule:

- Keep movie and generated assets inside the WSL filesystem, not under `/mnt/c/...`.
- Use subtitles as the primary plot source.
- Treat direct audio transcription as fallback support, not the primary pipeline path.

## 4. Outputs

The main deliverable is a DaVinci-ready output folder next to the source movie.

Expected asset set:

```text
movies/<title>/
  output/
    final_video.mp4
    clips/
    keyframes/
    segments/                # debug/intermediate render segments
  voiceover_<style>_voiceclone.mp3
  voiceover_<style>_voiceclone.manifest.json
  script_<style>_draft.txt
```

Product-level output rules:

- `final_video.mp4` is a draft render, not the final upload master.
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
2. Parse subtitles into reusable downstream text and structured data.
3. Support style-constrained script generation.
4. Produce an AI voiceover track for the script.
5. Align narration chunks to explicit scene markers.
6. Extract silent clips and fallback keyframes from the source movie.
7. Render a playable draft review video.
8. Preserve separate assets needed for manual post-production.

## 7. Quality Requirements

The draft pipeline should produce:

- Chinese output as the primary path
- Clear scene-to-narration alignment
- Mostly motion footage, not a slideshow
- Readable on-screen structure for later subtitle/render work
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
2. The voiceover, script, clips, and manifest all exist.
3. The draft covers the full plot arc.
4. The chosen style’s narrative rules are visibly followed.
5. The output folder is practical to reopen and finish in DaVinci Resolve.

## 10. Out of Scope

Not part of the core product target right now:

- automatic YouTube upload
- fully autonomous final mastering
- multi-movie batch orchestration
- advanced motion graphics packages
- AI-generated background music
