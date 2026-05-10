"""Harness for app.tools.generate_script_audio using tmp/configs/current_movie.toml."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import (
    DEFAULT_CONFIG,
    banner,
    build_paths,
    ensure_stage_dirs,
    fail,
    get_optional_tool_path,
    get_tool_value,
    load_config,
)

from app.tools.generate_script_audio import main as generate_script_audio_main


CONFIG = DEFAULT_CONFIG


def run() -> int:
    cfg = load_config(CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    script_path = get_optional_tool_path(cfg, "generate_script_audio", "script") or paths.tools_dir / "scripts.txt"
    style_path = get_optional_tool_path(cfg, "generate_script_audio", "style") or paths.style
    output_dir = get_optional_tool_path(cfg, "generate_script_audio", "out_dir") or paths.tools_dir
    ref_audio = get_optional_tool_path(cfg, "generate_script_audio", "ref_audio")
    ref_text = get_optional_tool_path(cfg, "generate_script_audio", "ref_text")
    tag = get_tool_value(cfg, "generate_script_audio", "tag")
    max_chars_per_request = get_tool_value(cfg, "generate_script_audio", "max_chars_per_request")
    temperature = get_tool_value(cfg, "generate_script_audio", "temperature")
    top_p = get_tool_value(cfg, "generate_script_audio", "top_p")
    top_k = get_tool_value(cfg, "generate_script_audio", "top_k")
    repetition_penalty = get_tool_value(cfg, "generate_script_audio", "repetition_penalty")
    max_new_tokens = get_tool_value(cfg, "generate_script_audio", "max_new_tokens")

    if not script_path.is_file():
        return fail(f"script not found: {script_path}")
    if not style_path.is_file():
        return fail(f"style file not found: {style_path}")

    banner(f"Tool — generate script audio for {cfg['common']['movie_title']}")
    print(f"script     : {script_path}")
    print(f"style      : {style_path}")
    print(f"output dir : {output_dir}")
    print(f"tag        : {tag or '(default, derived from style filename)'}")
    if ref_audio is not None:
        print(f"ref audio  : {ref_audio}")
    if ref_text is not None:
        print(f"ref text   : {ref_text}")

    args = [
        "--script", str(script_path),
        "--style", str(style_path),
        "--output-dir", str(output_dir),
    ]
    if ref_audio is not None:
        args.extend(["--ref-audio", str(ref_audio)])
    if ref_text is not None:
        args.extend(["--ref-text", str(ref_text)])
    if tag:
        args.extend(["--tag", str(tag)])
    if max_chars_per_request is not None:
        args.extend(["--max-chars-per-request", str(max_chars_per_request)])
    if temperature is not None:
        args.extend(["--temperature", str(temperature)])
    if top_p is not None:
        args.extend(["--top-p", str(top_p)])
    if top_k is not None:
        args.extend(["--top-k", str(top_k)])
    if repetition_penalty is not None:
        args.extend(["--repetition-penalty", str(repetition_penalty)])
    if max_new_tokens is not None:
        args.extend(["--max-new-tokens", str(max_new_tokens)])
    return generate_script_audio_main(args)


if __name__ == "__main__":
    raise SystemExit(run())