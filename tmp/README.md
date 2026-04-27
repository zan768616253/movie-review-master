# Pipeline runner scripts (manual / debug-friendly)

These are not unit tests. They are scratch scripts that drive the real
pipeline stages (`app/pipeline/stage*.py`) end-to-end, with each stage
isolated to its own file so you can re-run / debug any single stage in
VSCode with one click.

When this stabilises it will graduate into a proper orchestrator under `app/`.

---

## Layout

```
tmp/
  configs/
    jujutsu_kaisen_0.toml         # one TOML per movie
    _template.toml                # copy this when adding a new movie
  _common.py                      # config loader, paths, helpers
  step_00_index_visuals.py        # ← open & press ▶ to run stage 0
  step_01_parse_subtitles.py
  step_02_generate_script.py      # the manual paste-prompt-into-LLM step
  step_03_generate_audio.py
  step_04_video_processor.py
  step_05_render_video.py
  run_all.py                      # chains 0→1→3→4→5, stops at 2 for manual input
  README.md                       # this file
  TODO.md                         # pipeline notes (P0/P1/P2/P3)

  work/<movie_slug>/              # all per-movie outputs land here
    stage0/  stage1/  stage2/  stage3/  stage4/  stage5/
```

Inputs (movie file, subtitle file, style file) stay where they already live
under `movies/` and `styles/`. Only outputs go into `tmp/work/`.

---

## Running a single step

1. Open the step file you want, e.g. `step_03_generate_audio.py`.
2. Skim the file — it prints all paths it will read/write before running.
3. Press the ▶ (Run Current File) button in VSCode, **or** from a terminal:

   ```bash
   conda run -n py312_machine_learning --no-capture-output \
     python tmp/step_03_generate_audio.py
   ```

To switch movies: change the `CONFIG = "configs/<movie>.toml"` line at the
top of every step file (and `run_all.py`).

---

## Running the whole pipeline

```bash
conda run -n py312_machine_learning --no-capture-output \
  python tmp/run_all.py
```

Behaviour:

- Each stage **skips itself if its output already exists**, so re-running is
  cheap and safe.
- At Stage 2 it stops with a clear message — Stage 2 needs you to paste
  prompts into an LLM and paste the replies back. Run
  `step_02_generate_script.py` to handle that, then re-run `run_all.py`.

---

## Manual workflow for Stage 2 (the only non-automated stage)

Stage 2 produces the narration script via two LLM passes. The script files
live under `tmp/work/<movie_slug>/stage2/`.

1. Run `step_02_generate_script.py`. It writes `writer_prompt.txt`.
2. Paste `writer_prompt.txt` into your LLM. Paste the LLM reply into
   `writer_beats.txt` (overwriting the placeholder).
3. Run `step_02_generate_script.py` again. It writes `grounder_prompt.txt`.
4. Paste `grounder_prompt.txt` into your LLM. Paste the reply into
   `grounded_script.txt` (overwriting the placeholder).
5. Continue with `step_03_generate_audio.py` or `run_all.py`.

---

## Debugging tips

- Each stage's outputs live under `tmp/work/<movie_slug>/stageN/`. Inspect
  files there to find where things went wrong.
- To force a stage to re-run, delete its output (e.g. delete
  `tmp/work/jujutsu_kaisen_0/stage0/visual_segments.json` to re-run Stage 0).
- The first lines printed by each step echo the exact input/output paths,
  so the log itself tells you where to look.

---

## Adding a new movie

1. Drop the movie file + subtitle into `movies/<some_folder>/`.
2. Copy `tmp/configs/_template.toml` to `tmp/configs/<your_slug>.toml` and
   fill it in.
3. In each `step_*.py` file (and `run_all.py`), change the `CONFIG`
   constant at the top to point at your new TOML.
4. Run.
