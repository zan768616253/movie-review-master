"""Stage 2: Script Authoring — placeholder + prompt assembler.

Turns a parsed movie plot + a chosen style rulebook into a Chinese review
script with `[SCENE: ...]` and optional `[BROLL: ...]` markers.

Today this stage is **manual**: you assemble the prompt here, paste it
into Claude Code (or any LLM), paste the response into a draft file, and
continue to Stage 3. The file intentionally carries almost no logic —
its job is to document the step and produce a clean, reproducible
prompt contract that a future automated backend (Anthropic API, local
LLM, etc.) can drop into without changing upstream expectations.

================================================================
HOW TO USE (manual flow, today)
================================================================

Prerequisites — all must exist before you run this step:

  1. The movie at            movies/<title>/<movie>.mkv
  2. The subtitle at         movies/<title>/<movie>.srt   (.ass also fine)
  3. Parsed plain-text plot  movies/<title>/<movie>.txt   (produced by Stage 1)
  4. A chosen style file     styles/niu-shu.md            (Style A), or
                             styles/first-person-pov.md   (Style B)
  5. Your own knowledge of the movie's dominant genre
     (action / horror / thriller / romance / drama / comedy / supernatural / crime).
     This drives the Section 5.5b "Genre Visual Focus" rule in the style file.

Run:

    python -m app.pipeline.stage2_generate_script \\
        --style styles/niu-shu.md \\
        --subtitle-text movies/呪術回戦0/呪術回戦0.txt \\
        --subtitle-srt  movies/呪術回戦0/呪術回戦0.srt \\
        --movie-title "呪術回戦0 (Jujutsu Kaisen 0)" \\
        --genre action \\
        > /tmp/stage2_prompt.txt

Then:

  1. Paste the contents of /tmp/stage2_prompt.txt into Claude Code (or
     a fresh Claude conversation).
  2. Claude produces the script.
  3. Save Claude's response into  movies/<title>/script_<style>_draft.txt.
  4. Run the Stage 2 quality checks below. Iterate with Claude if needed.
  5. Proceed to Stage 3:
         python -m app.pipeline.stage3_generate_audio --script ...

================================================================
WHAT THE PROMPT CONTAINS (and why)
================================================================

The assembled prompt is structured so the LLM has everything it needs
to produce a compliant script in one pass:

  1. ROLE        — one-line instruction pinning the LLM to the
                   scriptwriter role in the chosen style.
  2. STYLE RULEBOOK — the FULL contents of the chosen style .md file.
                   The style file is the single source of truth for:
                     * Mission (audience-attention framing)
                     * Hook rules (front-load the best scene)
                     * Character-mapping rules (archetypes for Style A,
                       original names for Style B)
                     * Tone & pacing rules
                     * Section 5.5   Genre Modulation (tonal)
                     * Section 5.5b  Genre Visual Focus (clip-budget
                       minimums for action/horror/etc.)
                     * [SCENE] + [BROLL] output format
                     * Hard constraints (red lines)
                   Pasting it verbatim means the script rules and the
                   review rules never drift.
  3. MOVIE METADATA — title + genre. Genre explicitly anchors which
                   Section 5.5b budget the LLM must satisfy.
  4. PLOT SOURCE  — parsed-subtitle plain text. This is what the LLM
                   reads to understand the plot.
  5. SRT PREVIEW  — first 40 lines of the actual SRT. This shows the LLM
                   the exact timestamp format (`HH:MM:SS,mmm`) it should
                   mirror in its `[SCENE: HH:MM:SS-HH:MM:SS]` markers.
                   Without this, LLMs often invent wrong timestamp shapes.
  6. INSTRUCTIONS — explicit output requirements restated in imperative
                   form: length target, marker granularity, character
                   mapping table, hook-candidate ranking, genre
                   modulation declaration, closing rules.

================================================================
WHAT GOOD STAGE 2 OUTPUT LOOKS LIKE
================================================================

Saved as  movies/<title>/script_<style>_draft.txt.  Shape:

    ================================================================
    DRY-RUN SCRIPT — <style> style, <movie title>
    ================================================================
    角色对照表 (Character Mapping)  — Style A only
      <original name> → <archetype> (role)
    钩子候选 (Hook candidates, ranked)
      1. [SELECTED] ...
      2. ...
      3. ...
    选定类型修饰 (Genre modulation) — cites Section 5.5 + 5.5b
    ================================================================
    FINAL SCRIPT (read as continuous narration; [MARKERS] stripped)
    ================================================================
    [TITLE] ...
    [HOOK]
    [SCENE: HH:MM:SS-HH:MM:SS]
    [BROLL: ...optional...]
    <narration>
    [ACT 1 - SETUP]
    [SCENE: ...]
    ...
    [CLOSING]
    <final narration lines — no [SCENE] here>

================================================================
QUALITY CHECKS (run before Stage 3)
================================================================

  1. SCENE COUNT. `grep -c '^\\[SCENE:' draft.txt` should be 30-80
     for a 7-12 min review. <30 means clips will be too long (the
     "broad-range" bug); >80 means chunks too short to read
     naturally.
  2. HERO-CLIP GRANULARITY. Each [SCENE] window should be 5-10s.
     `grep '^\\[SCENE:' draft.txt` and eyeball — any windows >30s
     should be split.
  3. GENRE BUDGET. For action / horror / thriller, count [SCENE]+[BROLL]
     entries pointing at action/scare footage. Must meet or exceed the
     minimum in the style file Section 5.5b (e.g., action ≥40%).
     If short: add [BROLL: ...] lines to non-action narration chunks.
  4. HOOK IS NOT MOVIE OPENING. First [SCENE] timestamp must NOT be
     near 00:00:00. It must be the most gripping moment in the movie,
     front-loaded out of sequence.
  5. FULL ARC COVERED. Last [SCENE] timestamp should be near the
     movie's ending. Scan chronologically — no big unexplained gaps.
  6. STYLE A CHECK: No original names in narration. Replace every real
     character name with the archetype decided at the top.
  7. CLOSING HAS NO [SCENE]. The narration after [CLOSING] must have
     no [SCENE] marker — rendering uses the last keyframe or a
     title card.

================================================================
ITERATION (common fixes after draft lands)
================================================================

  - "Scene X is off" → re-grep the SRT near that narration's subject
    for a better timestamp, edit the marker, re-run Stage 4 + Stage 5.
  - "Not enough action footage" → insert [BROLL: ...] lines above
    non-action [SCENE] markers, pulling timestamps from the real
    action scenes. See docs/HANDBOOK.md §6.1.
  - "Narration is dry / not attracting enough" → ask Claude to
    rewrite act N with more 废话文学 / sarcasm / dialogue punches.
    Keep [SCENE] markers stable so Stage 4 doesn't need re-extract.
  - "Draft is too short / too long" → ask Claude to cut or expand
    to hit the 1,800-2,800 char target.

================================================================
WHY THIS FILE IS MOSTLY A DOCSTRING
================================================================

This step is the creative core of the pipeline. Automating it
prematurely would either:
  - produce generic scripts that don't match the style's voice, or
  - require an LLM API call, which couples the pipeline to an
    external paid service.

Keeping Stage 2 manual lets us tune the prompt contract against real
reviews until it's stable. When it is, `build_prompt()` below stays
the contract and an automated backend just calls it + an LLM.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_WRITER_ROLE = (
    "You are a Chinese movie-review scriptwriter. You strictly follow "
    "the style rulebook provided below. You write in Simplified Chinese. "
    "Your output must be a complete review script with [SCENE] markers "
    "at hero-clip granularity and optional [BROLL] markers for "
    "genre-visual cross-cuts."
)

SRT_PREVIEW_LINES = 40


def build_prompt(
    style_path: Path,
    subtitle_text_path: Path,
    subtitle_srt_path: Path,
    movie_title: str,
    genre: str,
) -> str:
    """Assemble the script-writer prompt ready to paste into an LLM.

    The returned string is the stable "prompt contract" for Stage 2.
    Future automated backends (Anthropic API, local LLM, etc.) should
    call this function and pass its output as the user prompt.
    """
    style_text = style_path.read_text(encoding="utf-8")
    plot_text = subtitle_text_path.read_text(encoding="utf-8")
    srt_text = subtitle_srt_path.read_text(encoding="utf-8")
    srt_preview = "\n".join(srt_text.splitlines()[:SRT_PREVIEW_LINES])

    return f"""# Role
{SCRIPT_WRITER_ROLE}

# Style Rulebook
The rulebook below is the single source of truth for tone, structure,
character naming, genre modulation, and output format. Follow every
rule exactly.

<<<STYLE_RULEBOOK_START>>>
{style_text}
<<<STYLE_RULEBOOK_END>>>

# Movie
Title: {movie_title}
Genre: {genre}

# Plot Source — parsed subtitle plain text, in movie order
<<<PLOT_START>>>
{plot_text}
<<<PLOT_END>>>

# SRT Preview — first {SRT_PREVIEW_LINES} lines
Use this as the reference format for the `HH:MM:SS` timestamps inside
your `[SCENE: HH:MM:SS-HH:MM:SS]` markers.
<<<SRT_PREVIEW_START>>>
{srt_preview}
<<<SRT_PREVIEW_END>>>

# Output requirements

1. Length target: 7-12 minutes of spoken Chinese, which is
   approximately 1,800-2,800 Chinese characters of narration.
2. Open the output with:
   - For Style A: a character-mapping table (original name → archetype).
   - A hook-candidate ranking (top 3, one marked [SELECTED]).
   - A declared genre modulation per style file Sections 5.5 + 5.5b,
     citing the genre "{genre}".
3. Output the script with structural markers in this order:
   [TITLE], [HOOK], [ACT 1 - SETUP], [ACT 2 - ESCALATION],
   [ACT 3 - CLIMAX], [ACT 4 - RESOLUTION], [CLOSING].
4. Every narration beat gets one [SCENE: HH:MM:SS-HH:MM:SS] marker.
   Target 30-80 total markers. Each window must be 5-10 seconds of
   source footage, anchored to a specific visual moment.
5. Cross-reference the SRT to anchor [SCENE] windows on real dialogue
   or visual beats. For silent action beats with no dialogue, infer
   from surrounding anchors and keep the window tight.
6. Apply the Section 5.5b genre visual-focus minimum. When narration
   alone does not hit the minimum for the declared genre, add
   `[BROLL: HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS]` lines between the
   `[SCENE]` and its narration. [BROLL] clips are cross-cut over the
   narration during rendering.
7. The [CLOSING] block has narration but NO [SCENE] — rendering uses
   the last keyframe or a title card.

# Produce
Output only the script itself. No preamble. No code fences. The
response must be ready to save directly as
`script_<style>_draft.txt`."""

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="stage2-generate-script",
        description=(
            "Print the assembled script-writer prompt to stdout. "
            "Stage 2 is currently a manual LLM handoff — see the file's "
            "module docstring for the full workflow."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See app/pipeline/stage2_generate_script.py module docstring for instructions.",
    )
    parser.add_argument("--style", type=Path, required=True, help="Path to the style .md file")
    parser.add_argument("--subtitle-text", type=Path, required=True, help="Parsed plain-text plot (from Stage 1)")
    parser.add_argument("--subtitle-srt", type=Path, required=True, help="Source SRT file (for the timestamp-shape reference)")
    parser.add_argument("--movie-title", required=True, help="Movie title with optional language")
    parser.add_argument("--genre", required=True, help="Genre keyword (action, horror, thriller, romance, drama, comedy, supernatural, crime)")
    args = parser.parse_args(argv)
    for path_arg in (args.style, args.subtitle_text, args.subtitle_srt):
        if not path_arg.exists():
            print(f"Input not found: {path_arg}", file=sys.stderr)
            return 1
    print(build_prompt(args.style, args.subtitle_text, args.subtitle_srt, args.movie_title, args.genre))
    return 0


if __name__ == "__main__":
    sys.exit(main())
