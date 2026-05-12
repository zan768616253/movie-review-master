# Movie-Review-Master Handbook

The central source of truth for stable project knowledge: concepts, design
decisions, pipeline logic, conventions, and style-system rules. Not a
progress log.

## 1. Documentation Map

- [PROD.md](../PROD.md): product scope, success criteria, boundaries
- [docs/HANDBOOK.md](HANDBOOK.md): durable knowledge and system design (this file)
- [docs/TECHNICAL.md](TECHNICAL.md): code-facing architecture, contracts, entry points, tests
- [workbench/README.md](../workbench/README.md): per-movie pipeline harness
- `styles/*.md`: style-specific writing rulebooks
- [docs/agent-rules/python-environment.md](agent-rules/python-environment.md): Python execution rule

## 2. System Goal

Turn a full movie plus subtitles into a draft long-form review package the
user can finish quickly. Automation handles the laborious parts (shot
indexing, prompt assembly, TTS, SRT generation); the final cut is done
manually in 剪映 (CapCut).

## 3. Operating Model

- WSL2 / Windows: Python, TTS, transcription, `ffmpeg`, the harness.
- 剪映: timeline assembly using the generated voiceover MP3 + SRT and the
  source movie.
- GPU: RTX 4060 class hardware (NVENC + CUDA hwaccel decode).
- Primary language: Chinese.
- Primary plot source: subtitle text.
- Primary media tool: `ffmpeg`.

## 4. Pipeline Shape

The pipeline is three automated steps plus one manual edit:

| # | Step | Role | Auto/Manual |
|---|---|---|---|
| 0 | Prepare Inputs | Visual indexing + subtitle parse | Auto |
| 1 | Build Prompt | Assemble LLM prompt; user pastes reply as the script | Manual paste; auto assembly |
| 2 | Generate Audio | TTS the script into MP3 + SRT manifest | Auto |
| 3 | Manual Edit | Combine source movie, voiceover MP3, and SRT in 剪映 | Manual |

Step 1 supports an optional **two-pass digest mode**: build a digest
prompt first, paste the reply back as `plot_digest.txt`, then build the
story prompt — which embeds the digest instead of the raw timeline.
Two-pass mode produces tighter scripts on long movies because the LLM
plans the plot before stylizing it.

The contract between automated and manual stages is intentionally simple:
Step 2 produces a voiceover MP3 + matching SRT cues. Everything else is
human judgment in the editor.

## 5. Core Concepts

### Source Movie & Subtitle Source

The full `.mp4` / `.mkv` plus `.srt` / `.ass`. The subtitle file is the
plot-context source — it does not drive sync.

### Visual Segment

A continuous take detected by the VLM during indexing. Visual segments
are the granularity at which the prompt builder describes "what is
happening on screen" to the LLM.

### Plot Digest (optional, two-pass mode)

A structured plain-text extraction the LLM produces in Pass 1 of the
two-pass workflow. Captures characters, power dynamics, plot beats with
causal chains, reviewable moments, and the full ending. Pass 2 reads the
digest instead of the raw timeline.

### Script

The LLM's final retelling, structured into `[HOOK]`, `[ACT ...]`,
`[CLOSING]` blocks. Each block becomes one TTS chunk and one SRT cue
group.

### Voiceover Manifest

Per-chunk record of `{index, section, text, audio_start_s, audio_end_s}`.
Lets you reopen the audio output later and know which script block
maps to which time range — useful when re-cutting in 剪映.

## 6. Style System

Style markdown files define narrator voice, pacing, naming rules, hook
strategy, and the act-structure headers the script must use.

### Style A: Uncle Niu

- detached third-person narrator
- deadpan sarcasm, fast pacing
- archetype nicknames instead of original names
- best for high-energy or high-plot-density reviews

Source of truth: [styles/niu-shu.md](../styles/niu-shu.md)

### Style B: First-Person Protagonist POV

- protagonist-led confession
- emotional, intimate, subjective narration
- original names preserved

Source of truth: [styles/first-person-pov.md](../styles/first-person-pov.md)

### Style C: Xiaodao (research only)

Warm, reflective, meaning-driven framing. Research materials live under
`styles/voice-assets/xiao-dao/analysis/`. Not yet runnable.

## 7. Technology Decisions

### Visual Indexing

- Gemini 3 Flash via `google-genai`.
- Long movies are split into chunks (currently 7 minutes) before VLM calls.
- The strategy interface (`VisualIndexerStrategy`) is preserved so a
  second backend could be added later without touching Stage 1's CLI.

### Prompt Assembly

- Style markdown is embedded verbatim — the LLM transfers style by reading
  the rulebook, not by paraphrasing examples.
- A genre example script (e.g. `styles/genres/niu-shu/Action.txt`) is
  appended when present, with its opening lines repeated as a "rhythm
  reminder" right before the output gate.
- A `synopsis.md` next to the movie file is the authoritative source for
  character names and relationships.
- The data block (timeline or digest) is placed before the instructional
  block so the model's most recent attention is on the rules, not the noise.

### TTS

- Qwen3-TTS Voice Clone on `Qwen/Qwen3-TTS-12Hz-1.7B-Base`.
- Per-chunk synthesis followed by concatenation and loudness normalization.
- Sampling resolves CLI > per-movie config > per-style `voice_clone.toml`
  > built-in defaults.
- Cap-hit detection (output length == `max_new_tokens`) triggers a
  halve-and-retry sub-split so long sentences don't truncate.
- Reference voice lives at `styles/voice-assets/<style>/reference/clone_reference.{mp3,txt}`.

### Subtitle Generation

- One SRT cue per Chinese sentence boundary inside each script chunk.
- Cue length capped at ~22 characters per line for readability in 剪映.
- Cue timestamps are computed from the real measured per-chunk audio
  ranges — never from character counts.

### Video / GPU

- `ffmpeg` is the baseline media engine.
- Stage 1 chunking uses NVENC + CUDA hwaccel decoding when available.
- Final cutting happens in 剪映, not in code; the project no longer
  ships its own video assembly stage.

## 8. Asset Model and Naming Conventions

### Per-movie input directory

```text
movies/<title>/
  <title>.{mkv,mp4}           # source movie
  <title>.{srt,ass}           # source subtitle
  synopsis.md                 # required: plot summary + named cast
  characters/                 # required: face-gallery reference images
    <character_name>.jpg
    ...
```

### Per-movie working directory

```text
workbench/work/<movie_slug>/
  stage0/
    visual_segments.json
    subtitles.txt
    indexing/                 # intermediate VLM-chunk clips (gitignored)
  stage1/
    digest_prompt.txt         # optional, only in two-pass mode
    plot_digest.txt           # optional, user-pasted LLM reply
    story_prompt.txt
    script.txt                # user-pasted LLM reply
  stage2/
    voiceover_<style>.mp3
    voiceover_<style>.srt
    voiceover_<style>.manifest.json
```

### Shared voice assets

```text
styles/
  niu-shu.md
  first-person-pov.md
  voice-assets/
    <style>/
      reference/
        clone_reference.mp3
        clone_reference.txt
        clone_reference.analysis.json
      analysis/               # study materials
      voice_clone.toml        # per-style TTS sampling overrides (optional)
```

Naming rules:

- Style-tagged voiceover filenames allow side-by-side experiments.
- Manifest filename tracks the voiceover filename.
- `analysis/` holds audio + transcript pairs used for style study.
- `reference/` holds the canonical clone source for a style.

## 9. Environment Rules

- Use the `py312_machine_learning` conda environment.
- Follow [docs/agent-rules/python-environment.md](agent-rules/python-environment.md)
  as the canonical command rule (`conda run -n py312_machine_learning --no-capture-output ...`).
- `pyproject.toml` is the dependency source of truth; sync with
  `pip install -e .` after edits.

## 10. Design Principles

### Less code is the goal

Manual stages get one thin Python harness file each. Automated stages
delegate to a CLI in `app/`. There are no skeleton modules waiting for
future features — if it's not implemented, it's not in the tree.

### One source of truth per fact

Style rules live in `styles/<style>.md`. Pipeline shape lives here.
Implementation details live in `docs/TECHNICAL.md`. Active workflow
commands live in `workbench/README.md`. Cross-reference; do not duplicate.

### Replaceable manual stages

Step 1's "user pastes the LLM reply" is the only manual data step. The
input/output contracts (prompts in, `script.txt` out) are stable enough
that an automated direct-LLM-call replacement could be dropped in later
without changing Step 0 or Step 2.

### Draft first, polish in the editor

The repo's job is to produce a strong draft voiceover + subtitle pair.
Polishing the picture cut, BGM, and transitions is the editor's job (剪映).
The repo intentionally does not own that step.
