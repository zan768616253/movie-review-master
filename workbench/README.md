# Workbench — pipeline harness

The `workbench/` folder drives the per-movie pipeline. Each numbered step
corresponds to one phase of the workflow described in
[`../PROD.md`](../PROD.md).

```
workbench/
  configs/
    current_movie.toml       # active movie config (always read by every step)
    _template.toml           # copy this when adding a new movie
    backup/                  # archived per-movie configs
  _common.py                 # config loader, paths, helpers
  step_0_prepare_inputs.py   # ▶ index visuals + parse subtitles
  step_1_build_prompt.py     # ▶ build LLM prompt (story by default; --digest for pass 1)
  step_2_generate_audio.py   # ▶ TTS the manual script into MP3 + SRT
  tools/                     # one-time-per-style asset prep
    prepare_voice_reference.py
    transcribe_audio.py
    voice_analysis.py
  work/<movie_slug>/
    stage0/
      visual_segments.json   # from step_0
      subtitles.txt          # from step_0
      indexing/              # intermediate chunked clips (gitignored)
    stage1/
      digest_prompt.txt      # optional, written by step_1 --digest
      plot_digest.txt        # optional, user-pasted LLM reply to digest_prompt
      story_prompt.txt       # written by step_1 (uses plot_digest if it exists)
      script.txt             # user-pasted LLM reply to story_prompt
    stage2/
      voiceover_<style>.mp3
      voiceover_<style>.srt
      voiceover_<style>.manifest.json
```

## End-to-end flow

```bash
# 0. Prepare inputs
conda run -n py312_machine_learning --no-capture-output python workbench/step_0_prepare_inputs.py

# 1a. (Optional, two-pass mode) Build digest prompt, paste into LLM,
#     save reply as workbench/work/<slug>/stage1/plot_digest.txt
conda run -n py312_machine_learning --no-capture-output python workbench/step_1_build_prompt.py --digest

# 1b. Build story prompt (auto-detects digest mode), paste into LLM,
#     save reply as workbench/work/<slug>/stage1/script.txt
conda run -n py312_machine_learning --no-capture-output python workbench/step_1_build_prompt.py

# 2. Generate voiceover MP3 + SRT
conda run -n py312_machine_learning --no-capture-output python workbench/step_2_generate_audio.py

# 3. Open the MP3 + SRT (and the source movie) in 剪映 for the manual edit.
```

## Switching movies

Overwrite `workbench/configs/current_movie.toml` with the movie you want to
run. Keep the previous one under `configs/backup/` if you want to come back.

Each new movie folder needs:

1. Movie file + subtitle file under `movies/<folder>/`.
2. `movies/<folder>/synopsis.md` — plot summary and named cast list.
3. `movies/<folder>/characters/` — non-empty folder of character reference
   images (Stage 0 uses these to keep names consistent across chunks).

## Re-running a step

Each step echoes the exact paths it reads and writes before doing work, so
the log itself tells you where to look. To force a step to re-run, delete
its outputs (e.g. `workbench/work/<slug>/stage0/visual_segments.json`).

## Style asset prep (one-time per voice)

The `workbench/tools/*.py` scripts wrap the asset-prep CLIs in `app.tools.*`.
They are not part of the per-movie loop — run them once when adding or
tuning a voice clone:

- `prepare_voice_reference.py` — slice a reference clip and place it under
  `styles/voice-assets/<style>/reference/`.
- `transcribe_audio.py` — transcribe the reference clip with Whisper.
- `voice_analysis.py` — emit prosody stats for tuning `voice_clone.toml`.
