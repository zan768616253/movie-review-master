"""Step 2 — build the LLM prompts for the multi-pass script pipeline.

Default: auto-detect which pass to run based on which reply files have been
filled. Run the command once at each stage of the workflow:

    python workbench/step_2_build_prompt.py   # 1st run: writes outline_prompt.txt
    # paste LLM reply into scene_markers.json
    python workbench/step_2_build_prompt.py   # 2nd run: detects scene_markers, writes digest_prompt.txt
    # paste LLM reply into plot_digest.txt
    python workbench/step_2_build_prompt.py   # 3rd run: detects plot_digest, writes story_prompt.txt
    # paste LLM reply into script.txt
    python workbench/step_2_build_prompt.py   # 4th run: all done, ready for stage 3

Empty placeholder reply files are created alongside each generated prompt so
the editor shows you exactly where to paste the LLM output.

Override the auto-detection with one of these flags to force-rerun a step:

    --outline   regenerate outline_prompt.txt
    --digest    regenerate digest_prompt.txt
    --story     regenerate story_prompt.txt

Series mode (current_series.toml present): the active episode is processed like
a movie, plus continuity wiring. Every episode's digest requests a 承上启下
carryover that is harvested into series_context.md once plot_digest.txt is
filled; from episode 2 on, the prior episodes' context is injected into the
digest (background) and story (which then opens with a [RECAP] block).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import banner, fail, resolve_run_context

from app.pipeline.series_context import (
    assemble_prior_context,
    extract_continuity_section,
    update_series_context,
)
from app.pipeline.stage_2_build_prompt import main as stage_2_main


def _target_minutes(cfg: dict) -> float | None:
    seconds = cfg["common"].get("target_seconds")
    return seconds / 60.0 if seconds else None


def _common_inputs_present(paths) -> int | None:
    if not paths.visual_segments.is_file():
        return fail(f"visual segments not found: {paths.visual_segments}")
    if not paths.subtitles_text.is_file():
        return fail(f"subtitles not found: {paths.subtitles_text}")
    if not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")
    return None


def _is_filled(path: Path) -> bool:
    """A reply file counts as 'filled' when it exists with non-whitespace content."""
    if not path.is_file():
        return False
    try:
        return path.read_text(encoding="utf-8").strip() != ""
    except OSError:
        return False


def detect_next_step(scene_markers: Path, plot_digest: Path, script: Path) -> str:
    """Return the next pass to run based on reply-file state.

    Returns one of ``"outline"``, ``"digest"``, ``"story"``, ``"done"``.
    The progression is sequential — an unfilled earlier reply blocks later steps.
    """
    if not _is_filled(scene_markers):
        return "outline"
    if not _is_filled(plot_digest):
        return "digest"
    if not _is_filled(script):
        return "story"
    return "done"


# --- Series continuity --------------------------------------------------------


def _write_prior_context(ctx) -> Path | None:
    """Assemble prior episodes' context into stage2/prior_context.md.

    Returns the file path, or ``None`` when there is nothing prior (episode 1 or
    movie mode), in which case no --prior-context is passed.
    """
    if not ctx.is_series or not ctx.episode_no or ctx.episode_no <= 1:
        return None
    series_md = ""
    if ctx.series_context_path and ctx.series_context_path.is_file():
        series_md = ctx.series_context_path.read_text(encoding="utf-8")
    prior = assemble_prior_context(series_md, ctx.episode_no)
    if not prior.strip():
        print(
            "NOTE: no prior-episode continuity found in "
            f"{ctx.series_context_path} — episode {ctx.episode_no} will run without a recap."
        )
        return None
    out = ctx.paths.stage2_dir / "prior_context.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prior, encoding="utf-8")
    return out


def _harvest_continuity(ctx) -> None:
    """Once this episode's plot_digest.txt is filled, extract its 承上启下 section
    into series_context.md so later episodes can recap it. Idempotent per episode."""
    if not ctx.is_series or not ctx.episode_no or ctx.series_context_path is None:
        return
    if not _is_filled(ctx.paths.plot_digest):
        return

    carryover = extract_continuity_section(ctx.paths.plot_digest.read_text(encoding="utf-8"))
    if carryover is None:
        carryover = (
            "（待补充：本集 digest 缺少 ## 承上启下 段落，请手动填写本集结束时的剧情状态、"
            "未解悬念与留给下一集的钩子。）"
        )
        print(
            f"WARNING: plot_digest.txt for 第 {ctx.episode_no} 集 has no '## 承上启下' section; "
            f"wrote a placeholder block into {ctx.series_context_path} — edit it by hand."
        )

    series_md = ""
    if ctx.series_context_path.is_file():
        series_md = ctx.series_context_path.read_text(encoding="utf-8")
    title = ctx.cfg["common"].get("movie_title", "")
    updated = update_series_context(series_md, ctx.episode_no, title, carryover)
    ctx.series_context_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.series_context_path.write_text(updated, encoding="utf-8")
    print(f"Updated series continuity: {ctx.series_context_path} (第 {ctx.episode_no} 集)")


def _print_next_steps(
    *,
    prompt_file: Path,
    reply_file: Path,
    reply_format: str,
    next_pass_label: str,
) -> None:
    """Print copy/paste guidance after a prompt is generated.

    ``next_pass_label`` is what the user advances to ("Pass 1 — digest", etc.).
    """
    print()
    print("─" * 70)
    print("NEXT STEPS")
    print("─" * 70)
    print(f"  1. Copy the contents of this prompt file into your LLM "
          f"(Gemini / DeepSeek / Qwen):")
    print(f"       {prompt_file}")
    print(f"  2. Save the LLM's {reply_format} reply into this file "
          f"(an empty placeholder has been created for you):")
    print(f"       {reply_file}")
    print(f"  3. Re-run the same command to advance to {next_pass_label}:")
    print(f"       python workbench/step_2_build_prompt.py")
    print("─" * 70)


def _run_outline(ctx) -> int:
    cfg, paths = ctx.cfg, ctx.paths
    rc = _common_inputs_present(paths)
    if rc is not None:
        return rc

    banner(f"Stage 2 — outline (Pass 0) for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles       : {paths.subtitles_text}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"output          : {paths.outline_prompt}")

    args = [
        "--outline",
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.outline_prompt),
    ]
    rc = stage_2_main(args)
    if rc == 0:
        paths.scene_markers.touch(exist_ok=True)
        _print_next_steps(
            prompt_file=paths.outline_prompt,
            reply_file=paths.scene_markers,
            reply_format="JSON (scene_markers schema — character_glossary + scenes)",
            next_pass_label="Pass 1 (digest)",
        )
    return rc


def _run_digest(ctx) -> int:
    cfg, paths = ctx.cfg, ctx.paths
    rc = _common_inputs_present(paths)
    if rc is not None:
        return rc

    digest_mode = cfg["common"].get("digest_mode", "single")
    if digest_mode not in ("single", "chunked"):
        return fail(f"Invalid digest_mode: {digest_mode!r} (expected 'single' or 'chunked')")

    if not paths.scene_markers.is_file() or not _is_filled(paths.scene_markers):
        return fail(
            f"scene_markers.json is empty or missing: {paths.scene_markers}\n"
            "Run with --outline (or just rerun and it will auto-build the outline prompt) "
            "and paste the LLM reply into that file before requesting the digest prompt."
        )

    banner(f"Stage 2 — digest (Pass 1, {digest_mode}) for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles       : {paths.subtitles_text}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"scene markers   : {paths.scene_markers}")
    print(f"output          : {paths.digest_prompt}")

    args = [
        "--digest",
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--scene-markers", str(paths.scene_markers),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.digest_prompt),
    ]
    if paths.style.is_file():
        args.extend(["--style", str(paths.style)])
    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])
    target_minutes = _target_minutes(cfg)
    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])
    if digest_mode == "chunked":
        args.append("--chunked")
    if ctx.is_series:
        # Every series episode emits a carryover; episodes >1 also see prior context.
        args.append("--series-carryover")
        prior = _write_prior_context(ctx)
        if prior is not None:
            args.extend(["--prior-context", str(prior)])
            print(f"prior context   : {prior}")
    rc = stage_2_main(args)
    if rc != 0:
        return rc

    if digest_mode == "chunked":
        paths.plot_digest.touch(exist_ok=True)
        front = paths.digest_prompt.with_suffix(f".front{paths.digest_prompt.suffix}")
        climax = paths.digest_prompt.with_suffix(f".climax{paths.digest_prompt.suffix}")
        tail = paths.digest_prompt.with_suffix(f".tail{paths.digest_prompt.suffix}")
        print()
        print("─" * 70)
        print("NEXT STEPS (chunked digest mode)")
        print("─" * 70)
        print("  1. Copy EACH of these three prompt files into your LLM, one at a time:")
        print(f"       {front}")
        print(f"       {climax}")
        print(f"       {tail}")
        print("  2. Concatenate the three replies (front → climax → tail) into:")
        print(f"       {paths.plot_digest}")
        print("  3. Re-run to advance to Pass 2 (story):")
        print("       python workbench/step_2_build_prompt.py")
        print("─" * 70)
    else:
        paths.plot_digest.touch(exist_ok=True)
        _print_next_steps(
            prompt_file=paths.digest_prompt,
            reply_file=paths.plot_digest,
            reply_format="plot-digest text (Chinese; with 镜头: visual:NNN refs per beat)",
            next_pass_label="Pass 2 (story)",
        )
    return rc


def _run_story(ctx) -> int:
    cfg, paths = ctx.cfg, ctx.paths
    if not paths.style.is_file():
        return fail(f"style file not found: {paths.style}")

    use_digest = _is_filled(paths.plot_digest)
    if not use_digest:
        rc = _common_inputs_present(paths)
        if rc is not None:
            return rc
    elif not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")

    paths.script.touch(exist_ok=True)

    mode = "DIGEST (multi-pass)" if use_digest else "TIMELINE (single-pass)"
    banner(f"Stage 2 — story prompt for {cfg['common']['movie_title']} [{mode}]")
    print(f"style           : {paths.style}")
    print(f"synopsis        : {paths.synopsis}")
    if use_digest:
        print(f"plot digest     : {paths.plot_digest}")
    else:
        print(f"visual segments : {paths.visual_segments}")
        print(f"subtitles       : {paths.subtitles_text}")
    print(f"output prompt   : {paths.story_prompt}")

    args = [
        "--style", str(paths.style),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.story_prompt),
    ]
    if use_digest:
        args.extend(["--plot-digest", str(paths.plot_digest)])
    else:
        args.extend([
            "--visual-segments", str(paths.visual_segments),
            "--subtitles-txt", str(paths.subtitles_text),
        ])

    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])
    target_minutes = _target_minutes(cfg)
    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])
    if ctx.is_series:
        prior = _write_prior_context(ctx)
        if prior is not None:
            args.extend(["--prior-context", str(prior)])
            print(f"prior context   : {prior} (story opens with [RECAP])")
    rc = stage_2_main(args)
    if rc == 0:
        _print_next_steps(
            prompt_file=paths.story_prompt,
            reply_file=paths.script,
            reply_format="full script text (with <refs>visual:NNN</refs> on its own line above every sentence)",
            next_pass_label="Stage 3 (TTS); re-run this command first to confirm the script is filled",
        )
    return rc


def _report_done(ctx) -> int:
    cfg, paths = ctx.cfg, ctx.paths
    banner(f"Stage 2 — already complete for {cfg['common']['movie_title']}")
    print("All three reply files are filled:")
    print(f"  scene_markers : {paths.scene_markers}")
    print(f"  plot_digest   : {paths.plot_digest}")
    print(f"  script        : {paths.script}")
    print()
    print("─" * 70)
    print("NEXT STEP")
    print("─" * 70)
    print("  Stage 2 is complete. Run the audio generation step:")
    print("       python workbench/step_3_generate_audio.py")
    print("─" * 70)
    return 0


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--outline", action="store_true",
                      help="Force-regenerate the Pass 0 outline prompt.")
    mode.add_argument("--digest", action="store_true",
                      help="Force-regenerate the Pass 1 digest prompt.")
    mode.add_argument("--story", action="store_true",
                      help="Force-regenerate the Pass 2 story prompt.")
    args = parser.parse_args(argv)

    ctx = resolve_run_context()
    if ctx.is_series:
        print(f"[series mode] {ctx.cfg['common']['movie_title']} · 第 {ctx.episode_no} 集")
        # Keep series_context.md current once this episode's digest is filled.
        _harvest_continuity(ctx)

    if args.outline:
        return _run_outline(ctx)
    if args.digest:
        return _run_digest(ctx)
    if args.story:
        return _run_story(ctx)

    next_step = detect_next_step(ctx.paths.scene_markers, ctx.paths.plot_digest, ctx.paths.script)
    if next_step == "outline":
        return _run_outline(ctx)
    if next_step == "digest":
        return _run_digest(ctx)
    if next_step == "story":
        return _run_story(ctx)
    return _report_done(ctx)


if __name__ == "__main__":
    raise SystemExit(run())
