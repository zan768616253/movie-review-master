# Product Requirements Document: movie-review-master

`PROD.md` defines the product scope and points to the small set of
source-of-truth docs:

- [docs/HANDBOOK.md](docs/HANDBOOK.md) — stable knowledge, design, pipeline rules
- [docs/TECHNICAL.md](docs/TECHNICAL.md) — code-facing contracts and implementation reference
- [workbench/README.md](workbench/README.md) — per-movie pipeline harness

## 1. Product Goal

`movie-review-master` automates the slow parts of producing a long-form
movie-review video so the operator only has to do the final timeline
assembly in 剪映 (CapCut). The automated output is:

- a structured plot prompt + LLM-written retelling script in the chosen style
- an AI voiceover MP3 of that script
- a matching SRT subtitle file
- per-chunk timing manifest for re-cutting

Final picture cut, B-roll, transitions, and BGM are done manually in 剪映
because that's where the operator's editing skill lives.

## 2. Target Workflow

1. Drop the movie file under `movies/<title>/` together with `synopsis.md`
   and a `characters/` face-gallery folder. A subtitle file (`.srt`/`.ass`)
   alongside is optional — Step 0 generates one when missing.
2. Update `workbench/configs/current_movie.toml` to point at the movie.
3. **Step 0 (optional)** — run `step_0_generate_subtitles.py`: faster-whisper
   transcribes the audio into a sibling `.srt`. Skipped automatically if the
   movie folder already has a `.srt` or `.ass`.
4. **Step 1** — run `step_1_prepare_inputs.py`: visual indexing + subtitle parse.
5. **Step 2** — run `step_2_build_prompt.py` (optionally `--digest` first
   for two-pass mode), paste the prompt into Gemini 3 Pro / DeepSeek / Qwen,
   paste the reply back as `script.txt`.
6. **Step 3** — run `step_3_generate_audio.py`: TTS the script into an MP3
   plus a matching SRT.
7. **Step 4 (manual)** — open the source movie, the voiceover MP3, and the
   SRT in 剪映. Cut the picture against the narration timeline.

Step 4 is the only manual data step. Steps 0–3 are fully automated; the
user only handles the LLM paste-paste in step 2.

### Series workflow (TV / anime, multi-episode)

Copy `_series_template.toml` to `workbench/configs/current.toml` (it sets
`[common].mode = "series"`) and list each episode plus an `active_episode`
pointer. Drop the episode files plus a shared `synopsis.md` and `characters/`
under `movies/<series_dir>/`. Run the same Steps 0–4 for the active episode,
then bump `active_episode` and repeat. The pipeline carries a running
"story-so-far" forward, and each episode after the first opens with a spoken
前情提要 recap. Assemble the per-episode outputs into one binge video in 剪映.

## 3. Inputs

| Input | Format | Notes |
|------|--------|-------|
| Movie | `.mp4` / `.mkv` | Full-length source |
| Subtitles | `.srt` / `.ass` | UTF-8 preferred |
| Synopsis | `synopsis.md` next to the movie | Plot summary + named cast |
| Face gallery | `characters/` next to the movie | Reference images for VLM character labelling |
| Style | `styles/<style>.md` | Defines narrator voice, naming rules, structure |

## 4. Outputs

```text
workbench/work/<movie_slug>/
  stage0/                    # reserved for Step 0 (SRT is written next to the video, not here)
  stage1/
    visual_segments.json
    subtitles.txt
  stage2/
    digest_prompt.txt        # only if two-pass mode
    plot_digest.txt          # only if two-pass mode
    story_prompt.txt
    script.txt
  stage3/
    voiceover_<style>.mp3
    voiceover_<style>.srt
    voiceover_<style>.manifest.json
```

The MP3 + SRT pair is the deliverable handed to 剪映. The manifest is
retained so a re-cut can map any timestamp back to the script chunk that
produced it.

## 5. Supported Review Styles

### Style A: Uncle Niu

- Third-person, deadpan, fast, sarcastic
- Archetype nicknames in place of character names
- Best for action, thriller, and high-plot-density reviews

### Style B: First-Person Protagonist POV

- First-person confessional narrator
- Emotional, subjective, character-driven
- Original names preserved

### Style C: Xiaodao (research only)

- Warm, reflective storyteller
- Best for dramas and classics
- Not yet runnable

## 6. Functional Requirements

The product must:

1. Accept `.mp4` / `.mkv` movies plus `.srt` / `.ass` subtitles.
2. Index shot boundaries with per-shot summary, OCR, and character labels.
3. Build a copy-pasteable LLM prompt (single-pass timeline mode or
   two-pass digest mode) that the operator runs against an external LLM.
4. TTS the user-pasted script into a voiceover MP3.
5. Generate burnable SRT cues aligned to real per-chunk audio durations.
6. Persist per-chunk timing so the editor can re-cut against any time range.

## 7. Quality Requirements

- Chinese output as the primary path.
- Voiceover stays loudness-consistent across chunks.
- SRT cues are short enough to read on a phone screen (~22 chars per line).
- The manual editor (剪映) can locate any narration timestamp and the
  script chunk that produced it.

## 8. Operating Constraints

- Primary runtime: Windows 11 + WSL2 with an RTX 4060 (NVENC + CUDA decode).
- Final cut: 剪映 (CapCut).
- `ffmpeg` is the core media tool.
- Local TTS is preferred over paid hosted TTS.
- Chinese narration first; English narration is secondary.

## 9. Success Criteria

A successful run means:

1. `voiceover_<style>.mp3` plays end-to-end with consistent loudness.
2. `voiceover_<style>.srt` is readable in 剪映 and aligned to speech pauses.
3. The script covers the full plot arc and follows the chosen style's
   narrative rules.
4. The manifest lets the operator jump to any chunk's audio range when
   editing.

## 10. Out of Scope

- Automatic picture cutting / final video assembly (done in 剪映).
- Automatic YouTube upload.
- Multi-movie batch orchestration.
- AI-generated background music.
- Advanced motion-graphics packages.
