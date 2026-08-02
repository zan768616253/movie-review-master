# Workbench — pipeline harness

The `workbench/` folder drives the per-movie pipeline. Each numbered step
corresponds to one phase of the workflow described in
[`../PROD.md`](../PROD.md).

```
workbench/
  configs/
    current.toml             # the single active config (every step reads it); [common].mode = "movie" | "series"
    _movie_template.toml     # copy to current.toml for a movie
    _series_template.toml    # copy to current.toml for a TV series
    backup/                  # archived per-title configs
  _common.py                    # config loader, paths, helpers
  step_0_generate_subtitles.py  # ▶ (optional) faster-whisper SRT; skipped if movie folder already has .srt/.ass
  step_1_prepare_inputs.py      # ▶ index visuals + parse subtitles
  step_2_build_prompt.py        # ▶ build LLM prompt (story by default; --digest for pass 1)
  step_3_generate_audio.py      # ▶ TTS the manual script into MP3 + SRT
  tools/                     # one-time-per-style asset prep
    prepare_voice_reference.py
    transcribe_audio.py
    voice_analysis.py
  work/<movie_slug>/
    stage0/                  # reserved for Step 0 (currently empty: SRT is written next to the video)
    stage1/
      visual_segments.json   # from step_1
      subtitles.txt          # from step_1
      indexing/              # intermediate chunked clips (gitignored)
    stage2/
      digest_prompt.txt      # optional, written by step_2 --digest
      plot_digest.txt        # optional, user-pasted LLM reply to digest_prompt
      story_prompt.txt       # written by step_2 (uses plot_digest if it exists)
      script.txt             # user-pasted LLM reply to story_prompt
    stage3/
      voiceover_<style>.mp3
      voiceover_<style>.srt
      voiceover_<style>.manifest.json
```

## End-to-end flow

```bash
# 0. (Optional) Generate an SRT via faster-whisper when no .srt/.ass exists
#    in the movie folder. No-op when one already does.
conda run -n py312_machine_learning --no-capture-output python workbench/step_0_generate_subtitles.py

# 1. Prepare inputs
conda run -n py312_machine_learning --no-capture-output python workbench/step_1_prepare_inputs.py

# 2a. (Optional, two-pass mode) Build digest prompt, paste into LLM,
#     save reply as workbench/work/<slug>/stage2/plot_digest.txt
conda run -n py312_machine_learning --no-capture-output python workbench/step_2_build_prompt.py --digest

# 2b. Build story prompt (auto-detects digest mode), paste into LLM,
#     save reply as workbench/work/<slug>/stage2/script.txt
conda run -n py312_machine_learning --no-capture-output python workbench/step_2_build_prompt.py

# 3. Generate voiceover MP3 + SRT
conda run -n py312_machine_learning --no-capture-output python workbench/step_3_generate_audio.py

# 4. Open the MP3 + SRT (and the source movie) in 剪映 for the manual edit.
```

## Series mode (TV / anime)

Copy `configs/_series_template.toml` to `configs/current.toml` and fill in the
`[[episodes]]` list plus `active_episode`. Because the copied template sets
`[common].mode = "series"`, every step runs in series mode for the active
episode — no filename magic. Switch back to a movie by copying
`_movie_template.toml` over `current.toml` (`mode = "movie"`). The run commands
are unchanged in both modes.

```bash
# Edit active_episode in current.toml, then run the same steps:
conda run -n py312_machine_learning --no-capture-output python workbench/step_1_prepare_inputs.py
conda run -n py312_machine_learning --no-capture-output python workbench/step_2_build_prompt.py   # repeat per pass
conda run -n py312_machine_learning --no-capture-output python workbench/step_3_generate_audio.py
conda run -n py312_machine_learning --no-capture-output python workbench/step_4_build_cheatsheet.py
# Bump active_episode and repeat for the next episode.
```

Layout: episodes nest under the series, with shared inputs at the series root.

```
movies/<series_dir>/
  synopsis.md  characters/      # shared by all episodes
  EP01.mp4  EP01.ass  EP02.mp4  EP02.ass  ...
workbench/work/<series_slug>/
  series_context.md             # running story-so-far (auto-seeded from each digest)
  ep01/  ep02/  ...             # per-episode stage0..4, same as a movie
```

Continuity is harvested from each episode's `## 承上启下` digest section into
`series_context.md` once `plot_digest.txt` is filled, then injected into later
episodes' prompts. Episodes after the first open with a `[RECAP]` block whose
sentences use `<refs>recap</refs>` (the editor pulls prior-episode footage).

## Switching titles

Overwrite `workbench/configs/current.toml` with the movie (or series) you want
to run — copy from `_movie_template.toml` / `_series_template.toml`. Keep the
previous one under `configs/backup/` if you want to come back. `[common].mode`
tells you (and every step) which kind of run it is.

Each new movie folder needs:

1. Movie file under `movies/<folder>/`. A subtitle file (`.srt` or `.ass`)
   alongside is optional — Step 0 will generate one if it's missing.
2. `movies/<folder>/synopsis.md` — plot summary and named cast list.
3. `movies/<folder>/characters/` — non-empty folder of character reference
   images (Stage 1 uses these to keep names consistent across chunks).

## Re-running a step

Each step echoes the exact paths it reads and writes before doing work, so
the log itself tells you where to look. To force a step to re-run, delete
its outputs (e.g. `workbench/work/<slug>/stage1/visual_segments.json`).

## Style asset prep (one-time per voice)

The `workbench/tools/*.py` scripts wrap the asset-prep CLIs in `app.tools.*`.
They are not part of the per-movie loop — run them once when adding or
tuning a voice clone:

- `prepare_voice_reference.py` — slice a reference clip and place it under
  `styles/voice-assets/<style>/reference/`.
- `transcribe_audio.py` — transcribe the reference clip with Whisper.
- `voice_analysis.py` — emit prosody stats for tuning `voice_clone.toml`.
