# Pipeline runner scripts (manual / debug-friendly)

These are not unit tests. They are scratch scripts that drive the real
pipeline stages (`app/pipeline/stage*.py`) end-to-end, with each stage
isolated to its own file so you can re-run / debug any single stage in
VSCode with one click.

> **Status (2026-05-04):** the audio-driven pipeline was retired. Only
> Stage 0 (shot detection) and Stage 1 (subtitle parse) have working
> step files right now. The rest of the new video-driven pipeline
> (stages 2–9) will get step files as those modules are implemented —
> see [`../plan.md`](../plan.md).

---

## Layout

```
tmp/
  configs/
    current_movie.toml            # the harness always reads this file
    _template.toml                # copy this when adding a new movie
    backup/                       # archived per-movie configs for reference
  _common.py                      # config loader, paths, helpers
  step_00_index_visuals.py        # ← open & press ▶ to run stage 0
  step_01_parse_subtitles.py
  README.md                       # this file

  work/<movie_slug>/              # all per-movie outputs land here
    stage0/                       # currently the only populated stage dir
```

Inputs (movie file, subtitle file, style file) stay where they already live
under `movies/` and `styles/`. Only outputs go into `tmp/work/`.

---

## Running a single step

1. Open the step file you want, e.g. `step_00_index_visuals.py`.
2. Skim the file — it prints all paths it will read/write before running.
3. Press the ▶ (Run Current File) button in VSCode, **or** from a terminal:

   ```bash
   conda run -n py312_machine_learning --no-capture-output \
     python tmp/step_00_index_visuals.py
   ```

To switch movies: overwrite `tmp/configs/current_movie.toml` with the movie
you want to run. If you want to keep the old one around, store a named copy
under `tmp/configs/backup/`.

---

## Debugging tips

- Each stage's outputs live under `tmp/work/<movie_slug>/stageN/`. Inspect
  files there to find where things went wrong.
- To force a stage to re-run, delete its output (e.g. delete
  `tmp/work/<slug>/stage0/visual_segments.json` to re-run Stage 0).
- The first lines printed by each step echo the exact input/output paths,
  so the log itself tells you where to look.

---

## Adding a new movie

1. Drop the movie file + subtitle into `movies/<some_folder>/`.
2. Copy `tmp/configs/_template.toml` to `tmp/configs/current_movie.toml` and
  fill it in.
3. If you want to preserve the old movie config, save a named copy under
  `tmp/configs/backup/` first.
4. **Optional but recommended:** drop `synopsis.md` into the movie folder
  (`movies/<some_folder>/synopsis.md`) with a plot summary and named cast
  list. Stage 0 auto-attaches it as a Cast Reference block in the VLM
  prompt so character names stay consistent across chunks. With no
  synopsis, the VLM falls back to the conservative per-chunk
  re-identification rule.
5. Run.
