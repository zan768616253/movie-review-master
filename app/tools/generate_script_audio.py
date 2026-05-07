"""Generate a voice-cloned MP3 + manifest from a manual script file.

Supports both:

- plain sectioned scripts like `tmp/work/<movie>/tools/scripts.txt`

Each structural block (`[HOOK]`, `[ACT ...]`, `[CLOSING]`) becomes one chunk.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from app.pipeline.common.json_io import dump_json
from app.pipeline.common.subtitle_utils import (
    TimedChunk,
    build_subtitle_cues,
    render_srt,
)


BASE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
REPO_ROOT = Path(__file__).resolve().parents[2]
STYLES_DIR = REPO_ROOT / "styles"
DEFAULT_STYLE_PATH = STYLES_DIR / "niu-shu.md"
REFERENCE_AUDIO_FILENAME = "clone_reference.mp3"
REFERENCE_TEXT_FILENAME = "clone_reference.txt"

STRUCTURAL_MARKER_RE = re.compile(r"^\[(?P<label>TITLE|HOOK|CLOSING|ACT[^\]]*)\]$")


@dataclass
class Chunk:
    """One narration chunk from the script."""

    index: int
    section: str
    text: str


@dataclass(frozen=True)
class VoiceReference:
    style_path: Path
    reference_dir: Path
    audio_path: Path
    text_path: Path


def resolve_optional_path(path: Optional[Path]) -> Optional[Path]:
    if path is None:
        return None
    return path.expanduser().resolve()


def resolve_reference_dir(style_path: Path) -> Path:
    return style_path.parent / "voice-assets" / style_path.stem / "reference"


def resolve_voice_reference(
    style_path: Path,
    ref_audio: Optional[Path],
    ref_text: Optional[Path],
) -> VoiceReference:
    reference_dir = resolve_reference_dir(style_path)
    return VoiceReference(
        style_path=style_path,
        reference_dir=reference_dir,
        audio_path=resolve_optional_path(ref_audio) or reference_dir / REFERENCE_AUDIO_FILENAME,
        text_path=resolve_optional_path(ref_text) or reference_dir / REFERENCE_TEXT_FILENAME,
    )


def resolve_output_tag(style_path: Path, explicit_tag: Optional[str]) -> str:
    if explicit_tag:
        return explicit_tag
    return style_path.stem


def parse_structural_marker(line: str) -> Optional[str]:
    match = STRUCTURAL_MARKER_RE.match(line)
    if match is None:
        return None
    return match.group("label").strip()


def parse_script_chunks(script_text: str) -> list[Chunk]:
    """Split a script into spoken chunks.

    Each structural block after `[HOOK]` becomes one chunk.
    """
    lines = [raw.strip() for raw in script_text.splitlines()]

    chunks: list[Chunk] = []
    current_section: Optional[str] = None
    pending_lines: list[str] = []
    in_script = False

    def flush() -> None:
        nonlocal pending_lines
        if pending_lines:
            chunks.append(
                Chunk(
                    index=len(chunks) + 1,
                    section=current_section or "SCRIPT",
                    text="\n".join(pending_lines),
                )
            )
        pending_lines = []

    for line in lines:
        if not line:
            continue

        marker = parse_structural_marker(line)
        if marker == "TITLE":
            continue

        if marker == "HOOK":
            flush()
            current_section = marker
            in_script = True
            continue

        if not in_script:
            continue

        if marker is not None:
            flush()
            current_section = marker
            continue

        pending_lines.append(line)

    flush()
    return chunks


def validate_script_input(script_path: Path, script_text: str, chunks: list[Chunk]) -> None:
    if not script_text.strip():
        raise ValueError(f"Script is empty: {script_path}")
    if not chunks:
        raise ValueError(
            f"No narration chunks found in {script_path}. Add [HOOK] and narration text."
        )


def load_model():
    import torch
    from qwen_tts import Qwen3TTSModel as LoadedQwen3TTSModel

    if torch.cuda.is_available():
        dtype = torch.float16
        device_summary = f"CUDA ({torch.cuda.get_device_name(0)})"
    else:
        # Half precision on CPU is a bad fallback for this workload; use fp32
        # and emit a direct warning so users do not mistake CPU inference for a hang.
        dtype = torch.float32
        device_summary = "CPU"
        print(
            f"[warn] CUDA is unavailable in this Python environment (torch={torch.__version__}). "
            "Qwen TTS will run on CPU and may be extremely slow. "
            "On Windows this usually means a CPU-only PyTorch build is installed.",
            file=sys.stderr,
        )

    print(f"[load] {BASE_MODEL_ID} on {device_summary} (dtype={dtype})")
    t0 = time.time()
    model = LoadedQwen3TTSModel.from_pretrained(
        BASE_MODEL_ID,
        dtype=dtype,
        device_map="auto",
    )
    print(f"[load] model ready in {time.time() - t0:.1f}s")
    return model


def build_voice_prompt(
    model,
    ref_audio: Path,
    ref_text_path: Path,
) -> object:
    if not ref_text_path.exists():
        raise FileNotFoundError(f"Reference transcript not found: {ref_text_path}")
    ref_text = ref_text_path.read_text(encoding="utf-8").strip()
    if not ref_text:
        raise ValueError(f"Reference transcript is empty: {ref_text_path}")

    print(
        f"[prompt] ref audio {ref_audio.name}, transcript {len(ref_text)} chars, mode=icl"
    )
    return model.create_voice_clone_prompt(ref_audio=str(ref_audio), ref_text=ref_text)


def generate_chunks(
    model,
    chunks: list[Chunk],
    voice_prompt: object,
) -> tuple[list[np.ndarray], int]:
    import torch

    wavs: list[np.ndarray] = []
    sample_rate: Optional[int] = None
    total = len(chunks)

    for chunk in chunks:
        t0 = time.time()
        out_wavs, out_sr = model.generate_voice_clone(
            text=chunk.text,
            voice_clone_prompt=voice_prompt,
            language="chinese",
        )
        if not out_wavs:
            raise RuntimeError(f"TTS returned no audio for chunk {chunk.index}")

        wav = np.asarray(out_wavs[0], dtype=np.float32)
        wavs.append(wav)
        sample_rate = out_sr
        audio_s = len(wav) / out_sr
        location = chunk.section
        print(
            f"[gen  {chunk.index:>3}/{total}] "
            f"{location:>16} "
            f"{len(chunk.text):>3}ch "
            f"-> {audio_s:5.1f}s audio in {time.time() - t0:5.1f}s"
        )
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    assert sample_rate is not None
    return wavs, sample_rate


def concat_and_normalize(
    wavs: list[np.ndarray],
    sample_rate: int,
    out_mp3: Path,
    *,
    run_cmd=subprocess.run,
) -> list[tuple[float, float]]:
    """Concatenate chunk audio, normalize it, and return each chunk's time span."""
    import torch
    import torchaudio

    if not wavs:
        raise ValueError("No audio chunks to concatenate")

    audio_ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for wav in wavs:
        duration_s = len(wav) / sample_rate
        audio_ranges.append((round(cursor, 3), round(cursor + duration_s, 3)))
        cursor += duration_s

    full = np.concatenate(wavs).astype(np.float32)
    if full.size == 0:
        raise ValueError("Generated audio is empty")

    peak = float(np.max(np.abs(full)))
    if peak > 1.0:
        full = full / peak

    wav_tmp = out_mp3.with_suffix(".wav")
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(wav_tmp), torch.from_numpy(full).unsqueeze(0), sample_rate, format="wav")
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(wav_tmp),
            "-af",
            "loudnorm=I=-14:TP=-1.5:LRA=11",
            "-b:a",
            "192k",
            str(out_mp3),
        ],
        check=True,
    )
    wav_tmp.unlink(missing_ok=True)
    return audio_ranges


def write_manifest(
    chunks: list[Chunk],
    audio_ranges: list[tuple[float, float]],
    out_path: Path,
) -> None:
    payload = [
        {
            "index": chunk.index,
            "section": chunk.section,
            "ranges": [],
            "characters": [],
            "text": chunk.text,
            "audio_start_s": start_s,
            "audio_end_s": end_s,
        }
        for chunk, (start_s, end_s) in zip(chunks, audio_ranges)
    ]
    dump_json(out_path, payload)


def write_subtitles(
    chunks: list[Chunk],
    audio_ranges: list[tuple[float, float]],
    out_path: Path,
) -> None:
    timed_chunks = [
        TimedChunk(
            index=chunk.index,
            text=chunk.text,
            start_s=start_s,
            end_s=end_s,
        )
        for chunk, (start_s, end_s) in zip(chunks, audio_ranges)
    ]
    cues = build_subtitle_cues(timed_chunks, max_chars_per_cue=22)
    if not cues:
        print("[warn] No subtitle cues generated", file=sys.stderr)
        return

    payload = render_srt(cues)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")


def print_chunk_summary(script_path: Path, chunks: list[Chunk]) -> None:
    total_chars = sum(len(chunk.text) for chunk in chunks)
    print(f"Script: {script_path}")
    print(f"  {len(chunks)} chunks, {total_chars} total narration chars")
    for chunk in chunks[:5]:
        preview = chunk.text[:40] + ("…" if len(chunk.text) > 40 else "")
        print(
            f"  chunk {chunk.index}: [{chunk.section}] "
            f"{len(chunk.text)}ch :: {preview}"
        )
    if len(chunks) > 5:
        print(f"  ... ({len(chunks) - 5} more)")


def run_full_generation(
    model,
    chunks: list[Chunk],
    voice_prompt: object,
    mp3_path: Path,
    manifest_path: Path,
    subtitle_path: Path,
    *,
    run_cmd=subprocess.run,
) -> None:
    wavs, sample_rate = generate_chunks(model, chunks, voice_prompt)
    audio_ranges = concat_and_normalize(wavs, sample_rate, mp3_path, run_cmd=run_cmd)
    write_manifest(chunks, audio_ranges, manifest_path)
    write_subtitles(chunks, audio_ranges, subtitle_path)

    total_audio_s = audio_ranges[-1][1] if audio_ranges else 0.0
    print(f"\n[done] {len(chunks)} chunks -> {total_audio_s:.1f}s audio ({total_audio_s / 60:.1f} min)")
    print(f"[done] {mp3_path}")
    print(f"[done] {manifest_path}")
    print(f"[done] {subtitle_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-script-audio",
        description="TTS a manual script into one voiceover MP3 + manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--script", type=Path, required=True,
                        help="Input script text file. Supports anchored or plain structural scripts.")
    parser.add_argument(
        "--style",
        type=Path,
        default=DEFAULT_STYLE_PATH,
        help="Style .md file used to derive the default voice reference and output tag.",
    )
    parser.add_argument(
        "--ref-audio",
        type=Path,
        default=None,
        help="Optional reference-audio override. Defaults to styles/voice-assets/<style>/reference/clone_reference.mp3.",
    )
    parser.add_argument(
        "--ref-text",
        type=Path,
        default=None,
        help="Optional transcript override for --ref-audio. Defaults to styles/voice-assets/<style>/reference/clone_reference.txt.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--tag",
        default=None,
        help="Optional filename tag. Defaults to the style filename stem.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    load_model_fn=load_model,
    run_cmd=subprocess.run,
) -> int:
    args = build_parser().parse_args(argv)

    script_path = args.script.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    style_path = args.style.expanduser().resolve()

    try:
        if not script_path.exists():
            raise FileNotFoundError(f"Script file not found: {script_path}")
        if not style_path.exists():
            raise FileNotFoundError(f"Style file not found: {style_path}")

        voice_reference = resolve_voice_reference(
            style_path,
            args.ref_audio,
            args.ref_text,
        )
        if not voice_reference.audio_path.exists():
            if args.ref_audio is None:
                raise FileNotFoundError(
                    f"Reference audio not found: {voice_reference.audio_path}. "
                    f"Add {REFERENCE_AUDIO_FILENAME} under {voice_reference.reference_dir} or pass --ref-audio."
                )
            raise FileNotFoundError(f"Reference audio not found: {voice_reference.audio_path}")

        if not voice_reference.text_path.exists():
            if args.ref_text is None:
                raise FileNotFoundError(
                    f"Reference transcript not found: {voice_reference.text_path}. "
                    f"Add {REFERENCE_TEXT_FILENAME} under {voice_reference.reference_dir} or pass --ref-text."
                )
            raise FileNotFoundError(f"Reference transcript not found: {voice_reference.text_path}")

        script_text = script_path.read_text(encoding="utf-8")
        chunks = parse_script_chunks(script_text)
        print_chunk_summary(script_path, chunks)
        validate_script_input(script_path, script_text, chunks)

        output_dir.mkdir(parents=True, exist_ok=True)
        output_tag = resolve_output_tag(style_path, args.tag)
        mp3_path = output_dir / f"voiceover_{output_tag}.mp3"
        manifest_path = output_dir / f"voiceover_{output_tag}.manifest.json"
        subtitle_path = output_dir / f"voiceover_{output_tag}.srt"

        try:
            import torch

            if torch.cuda.is_available():
                print(
                    f"[cuda] {torch.cuda.get_device_name(0)} "
                    f"({torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB)"
                )
        except Exception:
            pass

        total_t0 = time.time()
        model = load_model_fn()
        voice_prompt = build_voice_prompt(
            model,
            voice_reference.audio_path,
            voice_reference.text_path,
        )
        run_full_generation(
            model,
            chunks,
            voice_prompt,
            mp3_path,
            manifest_path,
            subtitle_path,
            run_cmd=run_cmd,
        )
        print(f"[done] wall time {(time.time() - total_t0) / 60:.1f} min")
        return 0
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())