"""Temporary end-to-end harness for a ~5 minute Jujutsu Kaisen 0 pipeline run.

This file is meant to be the quickest place to understand and drive the current
manual pipeline:

1. Stage 0 visual indexing with Gemini.
2. Stage 2a writer prompt generation.
3. Stage 2b grounding prompt generation.
4. Stage 3 audio generation.
5. Stage 4 clip extraction.
6. Stage 5 final render.

Quick start:

  conda run -n py312_machine_learning --no-capture-output python \
      tmp/run_stage2b_stage5_slice_harness.py guide

That command writes a step-by-step README under the working directory with the
exact commands for each stage.
"""

from __future__ import annotations

import argparse
import shlex
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.stage0_index_visuals import main as stage0_main
from app.pipeline.stage2_generate_script import build_grounding_prompt, build_writer_prompt
from app.pipeline.stage3_generate_audio import main as stage3_main, parse_script_chunks, validate_script_input
from app.pipeline.stage4_video_processor import main as stage4_main
from app.pipeline.stage5_render_video import main as stage5_main


CONDA_PREFIX_PARTS = ["conda", "run", "-n", "py312_machine_learning", "--no-capture-output"]
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_MOVIE_DIR = REPO_ROOT / "movies" / "呪術回戦0"
DEFAULT_STYLE_PATH = REPO_ROOT / "styles" / "niu-shu.md"
DEFAULT_WORK_DIR = REPO_ROOT / "tmp" / "e2e_jujutsu_5min"
DEFAULT_TARGET_SECONDS = 300.0
DEFAULT_MOVIE_TITLE = "呪術回戦0 (Jujutsu Kaisen 0)"
DEFAULT_GENRE = "action"
DEFAULT_STAGE0_STRATEGY = "gemini"
DEFAULT_STAGE0_CHUNK_MINUTES = 10
DEFAULT_STAGE3_TAG = "jujutsu5min"
DEFAULT_CHARACTERS = "Yuta Okkotsu,Rika Orimoto,Satoru Gojo,Maki Zenin,Toge Inumaki,Panda,Suguru Geto"
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
    stage5_final_video_path: Path
    readme_path: Path
    status_path: Path

    def ensure_directories(self) -> None:
        for path in (self.work_dir, self.stage0_dir, self.stage2_dir, self.stage3_dir, self.stage4_dir, self.stage5_dir):
            path.mkdir(parents=True, exist_ok=True)


def quote_text(value: str) -> str:
    return shlex.quote(value)


def target_char_range(target_seconds: float) -> tuple[int, int]:
    minutes = target_seconds / 60.0
    return int(minutes * 180), int(minutes * 280)


def build_paths(args: argparse.Namespace) -> HarnessPaths:
    movie_dir = args.movie_dir.expanduser().resolve()
    work_dir = args.work_dir.expanduser().resolve()
    style_path = args.style.expanduser().resolve()
    movie_name = args.movie_name

    video_path = movie_dir / f"{movie_name}.mkv"
    subtitle_srt_path = movie_dir / f"{movie_name}.srt"
    subtitle_text_path = movie_dir / f"{movie_name}.txt"

    stage0_dir = work_dir / "stage0"
    stage2_dir = work_dir / "stage2"
    stage3_dir = work_dir / "stage3"
    stage4_dir = work_dir / "stage4"
    stage5_dir = work_dir / "stage5"

    stage3_voiceover_path = stage3_dir / f"voiceover_{args.stage3_tag}_voiceclone.mp3"
    stage3_manifest_path = stage3_dir / f"voiceover_{args.stage3_tag}_voiceclone.manifest.json"

    return HarnessPaths(
        movie_dir=movie_dir,
        work_dir=work_dir,
        style_path=style_path,
        video_path=video_path,
        subtitle_srt_path=subtitle_srt_path,
        subtitle_text_path=subtitle_text_path,
        stage0_dir=stage0_dir,
        stage2_dir=stage2_dir,
        stage3_dir=stage3_dir,
        stage4_dir=stage4_dir,
        stage5_dir=stage5_dir,
        visual_segments_path=stage0_dir / "visual_segments.json",
        writer_prompt_path=stage2_dir / "stage2_writer_prompt.txt",
        writer_beats_path=stage2_dir / "writer_beats.txt",
        grounder_prompt_path=stage2_dir / "stage2_grounder_prompt.txt",
        grounded_script_path=stage2_dir / "grounded_script.txt",
        stage3_voiceover_path=stage3_voiceover_path,
        stage3_manifest_path=stage3_manifest_path,
        stage5_final_video_path=stage5_dir / "review_5min.mp4",
        readme_path=work_dir / "README.md",
        status_path=work_dir / "STATUS.md",
    )


def ensure_placeholders(paths: HarnessPaths) -> None:
    if not paths.writer_beats_path.exists():
        paths.writer_beats_path.write_text(PLACEHOLDER_BEATS, encoding="utf-8")
    if not paths.grounded_script_path.exists():
        paths.grounded_script_path.write_text(PLACEHOLDER_GROUNDED, encoding="utf-8")


def validate_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def validate_placeholder_replaced(path: Path, placeholder: str, label: str) -> None:
    validate_exists(path, label)
    if path.read_text(encoding="utf-8").strip() == placeholder.strip():
        raise ValueError(f"{label} still contains the placeholder marker: {path}")


def is_ready(path: Path, placeholder: str) -> bool:
    if not path.exists():
        return False
    return path.read_text(encoding="utf-8").strip() not in {"", placeholder.strip()}


def write_status(paths: HarnessPaths, title: str, lines: list[str]) -> None:
    text = "\n".join([f"# {title}", "", *lines]) + "\n"
    paths.status_path.write_text(text, encoding="utf-8")


def stage3_outputs_exist(paths: HarnessPaths) -> bool:
    return paths.stage3_voiceover_path.exists() and paths.stage3_manifest_path.exists()


def stage4_outputs_exist(paths: HarnessPaths) -> bool:
    return (
        (paths.stage4_dir / "clips").exists()
        and (paths.stage4_dir / "keyframes").exists()
        and (paths.stage4_dir / "clip_manifest.json").exists()
    )


def build_writer_prompt_with_override(paths: HarnessPaths, args: argparse.Namespace) -> str:
    min_chars, max_chars = target_char_range(args.target_seconds)
    override = f"""# Harness Override
Ignore any default runtime target below.
For this test run, target approximately {args.target_seconds / 60:.1f} minutes of narration.
That usually means about {min_chars}-{max_chars} Chinese characters.
Prefer a visibly action-forward cut with strong fight coverage and faster pacing.

"""
    base_prompt = build_writer_prompt(
        style_path=paths.style_path,
        subtitle_text_path=paths.subtitle_text_path,
        subtitle_srt_path=paths.subtitle_srt_path,
        movie_title=args.movie_title,
        genre=args.genre,
    )
    return override + base_prompt


def build_grounder_prompt_with_override(paths: HarnessPaths, args: argparse.Namespace) -> str:
    override = """# Harness Override
This run is action-forward.
When multiple visual candidates are similarly valid, prefer clearer fighting, motion, or impact footage.
Preserve the beat text unless a tiny wording fix is needed for grounding clarity.

"""
    base_prompt = build_grounding_prompt(
        beats_path=paths.writer_beats_path,
        subtitle_srt_path=paths.subtitle_srt_path,
        visual_segments_path=paths.visual_segments_path,
        movie_title=args.movie_title,
    )
    return override + base_prompt


def command_flags(args: argparse.Namespace) -> list[str]:
    target_seconds_text = str(int(args.target_seconds) if args.target_seconds.is_integer() else args.target_seconds)
    return [
        "--work-dir",
        str(args.work_dir),
        "--movie-dir",
        str(args.movie_dir),
        "--movie-name",
        args.movie_name,
        "--movie-title",
        args.movie_title,
        "--style",
        str(args.style),
        "--genre",
        args.genre,
        "--target-seconds",
        target_seconds_text,
        "--stage0-strategy",
        args.stage0_strategy,
        "--stage0-chunk-minutes",
        str(args.stage0_chunk_minutes),
        "--stage3-tag",
        args.stage3_tag,
        "--characters",
        args.characters,
    ]


def build_self_command(command: str, args: argparse.Namespace) -> str:
    parts = [*CONDA_PREFIX_PARTS, "python", str(SCRIPT_PATH), command, *command_flags(args)]
    return " ".join(quote_text(part) for part in parts)


def build_readme(paths: HarnessPaths, args: argparse.Namespace) -> str:
    guide_lines = [
        "# End-to-End Harness",
        "",
        "This tmp harness groups the current manual pipeline into one place.",
        "Default goal: a ~5 minute, action-forward Jujutsu Kaisen 0 review.",
        "",
        "## Defaults",
        f"- Movie dir: {paths.movie_dir}",
        f"- Video: {paths.video_path}",
        f"- Subtitle text: {paths.subtitle_text_path}",
        f"- Subtitle SRT: {paths.subtitle_srt_path}",
        f"- Style: {paths.style_path}",
        f"- Stage 0 strategy: {args.stage0_strategy}",
        f"- Working dir: {paths.work_dir}",
        f"- Runtime target: {args.target_seconds / 60:.1f} minutes",
        "",
        "## Output Files",
        f"- Stage 0 visual segments: {paths.visual_segments_path}",
        f"- Stage 2 writer prompt: {paths.writer_prompt_path}",
        f"- Stage 2 writer beats: {paths.writer_beats_path}",
        f"- Stage 2 grounder prompt: {paths.grounder_prompt_path}",
        f"- Stage 2 grounded script: {paths.grounded_script_path}",
        f"- Stage 3 voiceover: {paths.stage3_voiceover_path}",
        f"- Stage 3 manifest: {paths.stage3_manifest_path}",
        f"- Stage 5 final video: {paths.stage5_final_video_path}",
        f"- Current status: {paths.status_path}",
        "",
        "## Recommended Workflow",
        "1. Run the single `auto` command below.",
        "2. If it stops for Stage 2a, open the writer prompt and paste only the model's writer output into the writer beats file.",
        "3. Run the same `auto` command again.",
        "4. If it stops for Stage 2b, open the grounder prompt and paste only the model's final grounded script into the grounded script file.",
        "5. Run the same `auto` command again to finish Stage 3 through Stage 5.",
        "6. Check STATUS.md at any time to see what is pending.",
        "",
        "## Commands",
        "",
        "### Recommended: Advance As Far As Possible Automatically",
        build_self_command("auto", args),
        "",
        "### 0. Write This Guide Again",
        build_self_command("guide", args),
        "",
        "### 1. Stage 0 Visual Indexing With Gemini",
        build_self_command("stage0", args),
        "",
        "### 2. Stage 2a Writer Prompt",
        build_self_command("stage2-writer-prompt", args),
        f"Then paste only the writer model output into: {paths.writer_beats_path}",
        "",
        "### 3. Stage 2b Grounder Prompt",
        build_self_command("stage2-grounder-prompt", args),
        f"Then paste only the final grounded-script output into: {paths.grounded_script_path}",
        "",
        "### 4. Stage 3 Audio",
        build_self_command("stage3", args),
        "",
        "### 5. Stage 4 Clip Extraction",
        build_self_command("stage4", args),
        "",
        "### 6. Stage 5 Final Render",
        build_self_command("stage5", args),
        "",
        "### 7. Convenience: Run Stage 3, Stage 4, and Stage 5 After Grounding",
        build_self_command("post-grounding", args),
        "",
        "## Notes",
        "- Stage 2 is still manual. This harness writes the exact prompt files and target output paths.",
        "- Stage 0 defaults to Gemini because this run is intended to exercise the real visual-indexing path.",
        "- The final review length depends on the grounded script you paste into the Stage 2 grounded script file.",
    ]
    return "\n".join(guide_lines) + "\n"


def run_stage0(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    return stage0_main(
        [
            "--video",
            str(paths.video_path),
            "--output",
            str(paths.visual_segments_path),
            "--strategy",
            args.stage0_strategy,
            "--chunk-minutes",
            str(args.stage0_chunk_minutes),
            "--tmp-dir",
            str(paths.stage0_dir / "tmp"),
            "--characters",
            args.characters,
        ]
    )


def run_stage2_writer_prompt(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    ensure_placeholders(paths)
    prompt_text = build_writer_prompt_with_override(paths, args)
    paths.writer_prompt_path.write_text(prompt_text, encoding="utf-8")
    write_status(
        paths,
        "Waiting For Stage 2a Writer Output",
        [
            "The pipeline has prepared everything before Stage 2.",
            f"Writer prompt: {paths.writer_prompt_path}",
            f"Paste only the Stage 2a writer model output into: {paths.writer_beats_path}",
            f"Then rerun: {build_self_command('auto', args)}",
        ],
    )
    print(f"Writer prompt -> {paths.writer_prompt_path}")
    print(f"Paste only the writer model output into -> {paths.writer_beats_path}")
    print(f"Status -> {paths.status_path}")
    return 0


def run_stage2_grounder_prompt(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    ensure_placeholders(paths)
    validate_exists(paths.visual_segments_path, "Stage 0 visual segments")
    validate_placeholder_replaced(paths.writer_beats_path, PLACEHOLDER_BEATS, "Stage 2 writer beats")
    prompt_text = build_grounder_prompt_with_override(paths, args)
    paths.grounder_prompt_path.write_text(prompt_text, encoding="utf-8")
    write_status(
        paths,
        "Waiting For Stage 2b Grounded Script",
        [
            "Stage 2a is complete and the grounder prompt is ready.",
            f"Grounder prompt: {paths.grounder_prompt_path}",
            f"Paste only the grounder model's final grounded script into: {paths.grounded_script_path}",
            f"Then rerun: {build_self_command('auto', args)}",
        ],
    )
    print(f"Grounder prompt -> {paths.grounder_prompt_path}")
    print(f"Paste only the final grounded script into -> {paths.grounded_script_path}")
    print(f"Status -> {paths.status_path}")
    return 0


def run_stage3(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    validate_placeholder_replaced(paths.grounded_script_path, PLACEHOLDER_GROUNDED, "Stage 2 grounded script")
    return stage3_main(
        [
            "--script",
            str(paths.grounded_script_path),
            "--output-dir",
            str(paths.stage3_dir),
            "--tag",
            args.stage3_tag,
        ]
    )


def run_stage4(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    validate_placeholder_replaced(paths.grounded_script_path, PLACEHOLDER_GROUNDED, "Stage 2 grounded script")
    validate_exists(paths.visual_segments_path, "Stage 0 visual segments")
    return stage4_main(
        [
            "--script",
            str(paths.grounded_script_path),
            "--video",
            str(paths.video_path),
            "--output-dir",
            str(paths.stage4_dir),
            "--visual-segments",
            str(paths.visual_segments_path),
        ]
    )


def run_stage5(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    validate_exists(paths.stage3_manifest_path, "Stage 3 manifest")
    validate_exists(paths.stage3_voiceover_path, "Stage 3 voiceover")
    validate_exists(paths.stage4_dir / "clips", "Stage 4 clips dir")
    validate_exists(paths.stage4_dir / "keyframes", "Stage 4 keyframes dir")
    validate_exists(paths.visual_segments_path, "Stage 0 visual segments")
    return stage5_main(
        [
            "--manifest",
            str(paths.stage3_manifest_path),
            "--voiceover",
            str(paths.stage3_voiceover_path),
            "--clips-dir",
            str(paths.stage4_dir / "clips"),
            "--keyframes-dir",
            str(paths.stage4_dir / "keyframes"),
            "--clip-manifest",
            str(paths.stage4_dir / "clip_manifest.json"),
            "--video",
            str(paths.video_path),
            "--visual-segments",
            str(paths.visual_segments_path),
            "--output",
            str(paths.stage5_final_video_path),
        ]
    )


def run_post_grounding(paths: HarnessPaths, args: argparse.Namespace) -> int:
    if not stage3_outputs_exist(paths):
        stage3_rc = run_stage3(paths, args)
        if stage3_rc != 0:
            return stage3_rc
    else:
        print(f"Reusing existing Stage 3 outputs in {paths.stage3_dir}")

    if not stage4_outputs_exist(paths):
        stage4_rc = run_stage4(paths, args)
        if stage4_rc != 0:
            return stage4_rc
    else:
        print(f"Reusing existing Stage 4 outputs in {paths.stage4_dir}")

    stage5_rc = run_stage5(paths, args)
    if stage5_rc == 0:
        write_status(
            paths,
            "Pipeline Complete",
            [
                "All stages finished successfully.",
                f"Final video: {paths.stage5_final_video_path}",
            ],
        )
        print(f"Status -> {paths.status_path}")
    return stage5_rc


def run_guide(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    ensure_placeholders(paths)
    readme_text = build_readme(paths, args)
    paths.readme_path.write_text(readme_text, encoding="utf-8")
    print(readme_text)
    return 0


def run_auto(paths: HarnessPaths, args: argparse.Namespace) -> int:
    paths.ensure_directories()
    ensure_placeholders(paths)
    run_guide(paths, args)

    if not paths.visual_segments_path.exists():
        print("Running Stage 0 before Stage 2 handoff...")
        stage0_rc = run_stage0(paths, args)
        if stage0_rc != 0:
            write_status(
                paths,
                "Stage 0 Failed",
                [
                    f"Stage 0 visual indexing failed for: {paths.video_path}",
                    f"Retry with: {build_self_command('stage0', args)}",
                ],
            )
            return stage0_rc

    if not is_ready(paths.writer_beats_path, PLACEHOLDER_BEATS):
        print("Stage 2a input is missing. Preparing the writer prompt and pausing.")
        return run_stage2_writer_prompt(paths, args)

    if not is_ready(paths.grounded_script_path, PLACEHOLDER_GROUNDED):
        print("Stage 2b input is missing. Preparing the grounder prompt and pausing.")
        return run_stage2_grounder_prompt(paths, args)

    grounded_script_text = paths.grounded_script_path.read_text(encoding="utf-8")
    try:
        validate_script_input(
            paths.grounded_script_path,
            grounded_script_text,
            parse_script_chunks(grounded_script_text),
        )
    except ValueError as exc:
        print(f"Stage 2b output is invalid: {exc}")
        print("Refreshing the grounder prompt and pausing for a corrected Stage 2b output.")
        return run_stage2_grounder_prompt(paths, args)

    print("Stage 2 is complete. Running Stage 3 through Stage 5.")
    return run_post_grounding(paths, args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run-stage2b-stage5-slice-harness",
        description="Temporary end-to-end harness for a ~5 minute Gemini-based pipeline run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="guide",
        choices=[
            "auto",
            "guide",
            "stage0",
            "stage2-writer-prompt",
            "stage2-grounder-prompt",
            "stage3",
            "stage4",
            "stage5",
            "post-grounding",
        ],
    )
    parser.add_argument("--movie-dir", type=Path, default=DEFAULT_MOVIE_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--movie-name", default="呪術回戦0")
    parser.add_argument("--movie-title", default=DEFAULT_MOVIE_TITLE)
    parser.add_argument("--style", type=Path, default=DEFAULT_STYLE_PATH)
    parser.add_argument("--genre", default=DEFAULT_GENRE)
    parser.add_argument("--target-seconds", type=float, default=DEFAULT_TARGET_SECONDS)
    parser.add_argument("--stage0-strategy", choices=["gemini", "ollama"], default=DEFAULT_STAGE0_STRATEGY)
    parser.add_argument("--stage0-chunk-minutes", type=int, default=DEFAULT_STAGE0_CHUNK_MINUTES)
    parser.add_argument("--stage3-tag", default=DEFAULT_STAGE3_TAG)
    parser.add_argument("--characters", default=DEFAULT_CHARACTERS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = build_paths(args)

    if args.command == "guide":
        return run_guide(paths, args)
    if args.command == "auto":
        return run_auto(paths, args)
    if args.command == "stage0":
        return run_stage0(paths, args)
    if args.command == "stage2-writer-prompt":
        return run_stage2_writer_prompt(paths, args)
    if args.command == "stage2-grounder-prompt":
        return run_stage2_grounder_prompt(paths, args)
    if args.command == "stage3":
        return run_stage3(paths, args)
    if args.command == "stage4":
        return run_stage4(paths, args)
    if args.command == "stage5":
        return run_stage5(paths, args)
    if args.command == "post-grounding":
        return run_post_grounding(paths, args)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())