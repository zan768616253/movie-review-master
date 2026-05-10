# movie-review-master

Automates the slow parts of producing a long-form movie-review video.
Output: an LLM-written script, a voice-cloned MP3 narration, and a
matching SRT subtitle file you can drop into 剪映 (CapCut) to do the
final picture cut by hand.

## Quick start

```bash
# 0. Prepare inputs (visual indexing + subtitle parse)
conda run -n py312_machine_learning --no-capture-output python workbench/step_0_prepare_inputs.py

# 1. Build prompt; paste into LLM; save reply as workbench/work/<slug>/stage1/script.txt
conda run -n py312_machine_learning --no-capture-output python workbench/step_1_build_prompt.py

# 2. TTS the script into MP3 + SRT
conda run -n py312_machine_learning --no-capture-output python workbench/step_2_generate_audio.py

# 3. Open the MP3 + SRT in 剪映 alongside the source movie and cut by hand.
```

See [`workbench/README.md`](workbench/README.md) for the full per-step
reference, including the optional two-pass digest workflow.

## Documentation

- Product scope: [PROD.md](PROD.md)
- Stable design knowledge: [docs/HANDBOOK.md](docs/HANDBOOK.md)
- Code-facing implementation reference: [docs/TECHNICAL.md](docs/TECHNICAL.md)
- Pipeline harness: [workbench/README.md](workbench/README.md)
