"""End-to-end harness for the Jujutsu Kaisen 0 integration test.

Drives Stages 0, 2 (manual), 3, 4, 5 from one file. The `auto` command walks
as far as it can and pauses when Stage 2 needs human input: you paste the
writer model's beats into `writer_beats.txt`, rerun `auto`, paste the
grounder model's final script into `grounded_script.txt`, rerun `auto`.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.stage0_index_visuals import main as stage0_main
from app.pipeline.stage2_generate_script import build_grounding_prompt, build_writer_prompt
from app.pipeline.stage3_generate_audio import (
    main as stage3_main,
    parse_script_chunks,
    validate_script_input,
)
from app.pipeline.stage4_video_processor import main as stage4_main
from app.pipeline.stage5_render_video import main as stage5_main


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = {
    "movie_dir": REPO_ROOT / "movies" / "呪術回戦0",
    "work_dir": REPO_ROOT / "tmp" / "e2e_jujutsu_5min",
    "style_path": REPO_ROOT / "styles" / "niu-shu.md",
    "movie_name": "呪術回戦0",
    "movie_title": "呪術回戦0 (Jujutsu Kaisen 0)",
    "genre": "action",
    "target_seconds": 300.0,
    "stage3_tag": "jujutsu5min",
}

PLACEHOLDER_BEATS = "<REPLACE_WITH_STAGE2A_WRITER_OUTPUT>\n"
PLACEHOLDER_GROUNDED = "<REPLACE_WITH_STAGE2B_GROUNDER_OUTPUT>\n"


@dataclass
class HarnessPaths:
    movie_dir: Path
    work_dir: Path
    style_path: Path
    video_path: Path
    subtitle_srt_path: Path
    subtitle_text_path: Path
    stage0_dir: Path
    stage2_dir: Path
    stage3_dir: Path
    stage4_dir: Path
    stage5_dir: Path
    visual_segments_path: Path
    writer_prompt_path: Path
    writer_beats_path: Path
    grounder_prompt_path: Path
    grounded_script_path: Path
    stage3_voiceover_path: Path
    stage3_manifest_path: Path
    final_video_path: Path

    def ensure_dirs(self) -> None:
        for path in (self.work_dir, self.stage0_dir, self.stage2_dir, self.stage3_dir, self.stage4_dir, self.stage5_dir):
            path.mkdir(parents=True, exist_ok=True)


def build_paths(args: argparse.Namespace) -> HarnessPaths:
    movie_dir = args.movie_dir.expanduser().resolve()
    work_dir = args.work_dir.expanduser().resolve()
    name = args.movie_name
    stage3_dir = work_dir / "stage3"
    return HarnessPaths(
        movie_dir=movie_dir,
        work_dir=work_dir,
        style_path=args.style.expanduser().resolve(),
        video_path=movie_dir / f"{name}.mkv",
        subtitle_srt_path=movie_dir / f"{name}.srt",
        subtitle_text_path=movie_dir / f"{name}.txt",
        stage0_dir=work_dir / "stage0",
        stage2_dir=work_dir / "stage2",
        stage3_dir=stage3_dir,
        stage4_dir=work_dir / "stage4",
        stage5_dir=work_dir / "stage5",
        visual_segments_path=work_dir / "stage0" / "visual_segments.json",
        writer_prompt_path=work_dir / "stage2" / "stage2_writer_prompt.txt",
        writer_beats_path=work_dir / "stage2" / "writer_beats.txt",
        grounder_prompt_path=work_dir / "stage2" / "stage2_grounder_prompt.txt",
        grounded_script_path=work_dir / "stage2" / "grounded_script.txt",
        stage3_voiceover_path=stage3_dir / f"voiceover_{args.stage3_tag}_voiceclone.mp3",
        stage3_manifest_path=stage3_dir / f"voiceover_{args.stage3_tag}_voiceclone.manifest.json",
        final_video_path=work_dir / "stage5" / "review_5min.mp4",
    )


def seed_placeholders(paths: HarnessPaths) -> None:
    if not paths.writer_beats_path.exists():
        paths.writer_beats_path.write_text(PLACEHOLDER_BEATS, encoding="utf-8")
    if not paths.grounded_script_path.exists():
        paths.grounded_script_path.write_text(PLACEHOLDER_GROUNDED, encoding="utf-8")


def is_ready(path: Path, placeholder: str) -> bool:
    return path.exists() and path.read_text(encoding="utf-8").strip() not in {"", placeholder.strip()}


def writer_override(args: argparse.Namespace) -> str:
    minutes = args.target_seconds / 60.0
    return (
        "# Harness Override\n"
        f"Ignore any default runtime target below. Target about {minutes:.1f} minutes of narration "
        f"(~{int(minutes * 180)}-{int(minutes * 280)} Chinese characters). "
        "Prefer an action-forward cut with strong fight coverage.\n\n"
    )


def grounder_override() -> str:
    return (
        "# Harness Override\n"
        "This run is action-forward. When multiple visual candidates are similarly valid, "
        "prefer clearer fighting, motion, or impact footage. Preserve beat wording unless a "
        "tiny fix is needed for grounding clarity.\n\n"
    )


def run_stage0(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    return stage0_main([
        "--video", str(paths.video_path),
        "--output", str(paths.visual_segments_path),
        "--tmp-dir", str(paths.stage0_dir / "tmp"),
    ])


def run_stage2_writer(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    seed_placeholders(paths)
    if not paths.visual_segments_path.exists():
        print(f"Stage 0 visual_segments.json missing: {paths.visual_segments_path}")
        return 1
    prompt = writer_override(args) + build_writer_prompt(
        style_path=paths.style_path,
        subtitle_srt_path=paths.subtitle_srt_path,
        visual_segments_path=paths.visual_segments_path,
        movie_title=args.movie_title,
        genre=args.genre,
    )
    paths.writer_prompt_path.write_text(prompt, encoding="utf-8")
    print(f"\nStage 2a ready. Paste writer model output into:\n  {paths.writer_beats_path}")
    print(f"Prompt: {paths.writer_prompt_path}")
    return 0


def run_stage2_grounder(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    seed_placeholders(paths)
    if not paths.visual_segments_path.exists():
        print(f"Stage 0 visual_segments.json missing: {paths.visual_segments_path}")
        return 1
    if not is_ready(paths.writer_beats_path, PLACEHOLDER_BEATS):
        print(f"Writer beats still empty or placeholder: {paths.writer_beats_path}")
        return 1
    prompt = grounder_override() + build_grounding_prompt(
        beats_path=paths.writer_beats_path,
        subtitle_srt_path=paths.subtitle_srt_path,
        visual_segments_path=paths.visual_segments_path,
        movie_title=args.movie_title,
    )
    paths.grounder_prompt_path.write_text(prompt, encoding="utf-8")
    print(f"\nStage 2b ready. Paste grounder model output into:\n  {paths.grounded_script_path}")
    print(f"Prompt: {paths.grounder_prompt_path}")
    return 0


def run_stage3(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    return stage3_main([
        "--script", str(paths.grounded_script_path),
        "--style", str(paths.style_path),
        "--output-dir", str(paths.stage3_dir),
        "--tag", args.stage3_tag,
    ])


def run_stage4(paths: HarnessPaths, _: argparse.Namespace) -> int:
    paths.ensure_dirs()
    return stage4_main([
        "--script", str(paths.grounded_script_path),
        "--video", str(paths.video_path),
        "--output-dir", str(paths.stage4_dir),
        "--visual-segments", str(paths.visual_segments_path),
    ])


def run_stage5(paths: HarnessPaths, _: argparse.Namespace) -> int:
    paths.ensure_dirs()
    return stage5_main([
        "--manifest", str(paths.stage3_manifest_path),
        "--voiceover", str(paths.stage3_voiceover_path),
        "--clips-dir", str(paths.stage4_dir / "clips"),
        "--keyframes-dir", str(paths.stage4_dir / "keyframes"),
        "--clip-manifest", str(paths.stage4_dir / "clip_manifest.json"),
        "--video", str(paths.video_path),
        "--visual-segments", str(paths.visual_segments_path),
        "--output", str(paths.final_video_path),
    ])


def run_post_grounding(paths: HarnessPaths, args: argparse.Namespace) -> int:
    if not (paths.stage3_voiceover_path.exists() and paths.stage3_manifest_path.exists()):
        rc = run_stage3(paths, args)
        if rc != 0:
            return rc
    else:
        print(f"Reusing Stage 3 outputs in {paths.stage3_dir}")

    if not (paths.stage4_dir / "clip_manifest.json").exists():
        rc = run_stage4(paths, args)
        if rc != 0:
            return rc
    else:
        print(f"Reusing Stage 4 outputs in {paths.stage4_dir}")

    rc = run_stage5(paths, args)
    if rc == 0:
        print(f"\n[done] final video: {paths.final_video_path}")
    return rc


def run_auto(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_dirs()
    seed_placeholders(paths)

    if not paths.visual_segments_path.exists():
        rc = run_stage0(paths, args)
        if rc != 0:
            return rc

    if not is_ready(paths.writer_beats_path, PLACEHOLDER_BEATS):
        return run_stage2_writer(paths, args)

    if not is_ready(paths.grounded_script_path, PLACEHOLDER_GROUNDED):
        return run_stage2_grounder(paths, args)

    grounded_text = paths.grounded_script_path.read_text(encoding="utf-8")
    try:
        validate_script_input(paths.grounded_script_path, grounded_text, parse_script_chunks(grounded_text))
    except ValueError as exc:
        print(f"Stage 2b output invalid: {exc}\nRefreshing grounder prompt.")
        return run_stage2_grounder(paths, args)

    return run_post_grounding(paths, args)


COMMANDS = {
    "auto": run_auto,
    "stage0": run_stage0,
    "stage2-writer": run_stage2_writer,
    "stage2-grounder": run_stage2_grounder,
    "stage3": run_stage3,
    "stage4": run_stage4,
    "stage5": run_stage5,
    "post-grounding": run_post_grounding,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-stage2b-stage5-slice-harness",
        description="End-to-end harness for the Jujutsu integration test.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("command", nargs="?", default="auto", choices=list(COMMANDS))
    parser.add_argument("--movie-dir", type=Path, default=DEFAULTS["movie_dir"])
    parser.add_argument("--work-dir", type=Path, default=DEFAULTS["work_dir"])
    parser.add_argument("--movie-name", default=DEFAULTS["movie_name"])
    parser.add_argument("--movie-title", default=DEFAULTS["movie_title"])
    parser.add_argument("--style", type=Path, default=DEFAULTS["style_path"])
    parser.add_argument("--genre", default=DEFAULTS["genre"])
    parser.add_argument("--target-seconds", type=float, default=DEFAULTS["target_seconds"])
    parser.add_argument("--stage3-tag", default=DEFAULTS["stage3_tag"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = build_paths(args)
    return COMMANDS[args.command](paths, args)


if __name__ == "__main__":
    raise SystemExit(main())
