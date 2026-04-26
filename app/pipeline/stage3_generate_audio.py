"""Stage 3 voiceover generation for the current Style A path.

The script is split on [SCENE] markers, spoken chunk by chunk through Qwen3
voice cloning, concatenated into one normalized voiceover, and written with a
manifest that keeps the render sync contract intact.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import torch

from app.pipeline.common.json_io import dump_json
from app.pipeline.common.script_contract import (
    BROLL_LINE_RE,
    STRUCTURAL_MARKER_RE,
    SceneMarker,
    parse_broll_ranges,
    parse_scene_marker,
)


BASE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
REPO_ROOT = Path(__file__).resolve().parents[2]
STYLES_DIR = REPO_ROOT / "styles"
DEFAULT_STYLE_PATH = STYLES_DIR / "niu-shu.md"
REFERENCE_AUDIO_FILENAME = "clone_reference.mp3"
REFERENCE_TEXT_FILENAME = "clone_reference.txt"


@dataclass
class Chunk:
    index: int
    scene: Optional[SceneMarker]
    text: str
    broll: list[tuple[str, str]] = field(default_factory=list)

    # Flat accessors the manifest writer and CLI summary still want.
    @property
    def scene_start(self) -> Optional[str]:
        return self.scene.start if self.scene else None

    @property
    def scene_end(self) -> Optional[str]:
        return self.scene.end if self.scene else None

    @property
    def scene_source(self) -> Optional[str]:
        return self.scene.source if self.scene else None

    @property
    def scene_characters(self) -> list[str]:
        return list(self.scene.characters) if self.scene else []


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


def parse_script_chunks(script_text: str) -> list[Chunk]:
    """Split a marked script into narration chunks."""
    chunks: list[Chunk] = []
    current_scene: Optional[SceneMarker] = None
    pending_lines: list[str] = []
    pending_broll: list[tuple[str, str]] = []
    in_script = False

    def flush() -> None:
        nonlocal pending_lines, pending_broll
        if pending_lines:
            chunks.append(Chunk(
                index=len(chunks) + 1,
                scene=current_scene,
                text="\n".join(pending_lines),
                broll=list(pending_broll) if current_scene is not None else [],
            ))
        pending_lines = []
        pending_broll = []

    for raw in script_text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("[TITLE]"):
            in_script = True
            continue

        if not in_script:
            continue

        structural = STRUCTURAL_MARKER_RE.match(line)
        if structural:
            if structural.group(1).upper() == "CLOSING":
                flush()
                current_scene = None
            continue

        scene_marker = parse_scene_marker(line)
        if scene_marker is not None:
            flush()
            current_scene = scene_marker
            continue

        broll_match = BROLL_LINE_RE.search(line)
        if broll_match:
            pending_broll.extend(parse_broll_ranges(broll_match.group(1)))
            continue

        pending_lines.append(line)

    flush()
    return chunks


def validate_script_input(script_path: Path, script_text: str, chunks: list[Chunk]) -> None:
    if not script_text.strip():
        raise ValueError(f"Script is empty: {script_path}")
    if not chunks:
        raise ValueError(f"No narration chunks found in {script_path}")


def load_model():
    from qwen_tts import Qwen3TTSModel as LoadedQwen3TTSModel

    print(f"[load] {BASE_MODEL_ID}")
    t0 = time.time()
    model = LoadedQwen3TTSModel.from_pretrained(
        BASE_MODEL_ID,
        torch_dtype=torch.float16,
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
    print(
        f"[prompt] ref audio {ref_audio.name}, transcript {len(ref_text)} chars, mode=icl"
    )
    return model.create_voice_clone_prompt(ref_audio=str(ref_audio), ref_text=ref_text)


def generate_chunks(
    model,
    chunks: list[Chunk],
    voice_prompt: object,
) -> tuple[list[np.ndarray], int]:
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

        wav = out_wavs[0]
        wavs.append(wav)
        sample_rate = out_sr
        audio_s = len(wav) / out_sr
        print(
            f"[gen  {chunk.index:>3}/{total}] "
            f"{chunk.scene_start or '(closing)':>8} "
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
) -> list[tuple[float, float]]:
    """Concatenate chunk audio, normalize it, and return each chunk's time span."""
    import soundfile as sf

    if not wavs:
        raise ValueError("No audio chunks to concatenate")

    audio_ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for wav in wavs:
        duration_s = len(wav) / sample_rate
        audio_ranges.append((round(cursor, 3), round(cursor + duration_s, 3)))
        cursor += duration_s

    full = np.concatenate(wavs).astype(np.float32)
    peak = float(np.max(np.abs(full)))
    if peak > 1.0:
        full = full / peak

    wav_tmp = out_mp3.with_suffix(".wav")
    sf.write(str(wav_tmp), full, sample_rate)
    subprocess.run(
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
            "scene_start": chunk.scene_start,
            "scene_end": chunk.scene_end,
            "scene_source": chunk.scene_source,
            "scene_characters": chunk.scene_characters,
            "text": chunk.text,
            "broll": [[start, end] for (start, end) in chunk.broll],
            "audio_start_s": start_s,
            "audio_end_s": end_s,
        }
        for chunk, (start_s, end_s) in zip(chunks, audio_ranges)
    ]
    dump_json(out_path, payload)


def print_chunk_summary(script_path: Path, chunks: list[Chunk]) -> None:
    total_chars = sum(len(chunk.text) for chunk in chunks)
    print(f"Script: {script_path}")
    print(f"  {len(chunks)} chunks, {total_chars} total narration chars")
    for chunk in chunks[:5]:
        print(
            f"  chunk {chunk.index}: [{chunk.scene_start or '--:--:--'}-{chunk.scene_end or '--:--:--'}] "
            f"{len(chunk.text)}ch :: {chunk.text[:40]}…"
        )
    if len(chunks) > 5:
        print(f"  ... ({len(chunks) - 5} more)")


def run_full_generation(
    model,
    chunks: list[Chunk],
    voice_prompt: object,
    mp3_path: Path,
    manifest_path: Path,
) -> None:
    wavs, sample_rate = generate_chunks(model, chunks, voice_prompt)
    audio_ranges = concat_and_normalize(wavs, sample_rate, mp3_path)
    write_manifest(chunks, audio_ranges, manifest_path)

    total_audio_s = audio_ranges[-1][1] if audio_ranges else 0.0
    print(f"\n[done] {len(chunks)} chunks -> {total_audio_s:.1f}s audio ({total_audio_s / 60:.1f} min)")
    print(f"[done] {mp3_path}")
    print(f"[done] {manifest_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate-audio",
        description="Stage 3: TTS a marked script into one voiceover and manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument(
        "--style",
        type=Path,
        default=DEFAULT_STYLE_PATH,
        help="Style .md file used in Stage 2. It also selects default reference assets from styles/voice-assets/<style>/reference/ and the default output tag.",
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


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    script_path = args.script.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    style_path = args.style.expanduser().resolve()

    if not script_path.exists():
        print(f"Script file not found: {script_path}", file=sys.stderr)
        return 1
    if not style_path.exists():
        print(f"Style file not found: {style_path}", file=sys.stderr)
        return 1

    voice_reference = resolve_voice_reference(
        style_path,
        args.ref_audio,
        args.ref_text,
    )
    if not voice_reference.audio_path.exists():
        if args.ref_audio is None:
            print(
                f"Reference audio not found: {voice_reference.audio_path}. "
                f"Add {REFERENCE_AUDIO_FILENAME} under {voice_reference.reference_dir} or pass --ref-audio.",
                file=sys.stderr,
            )
        else:
            print(f"Reference audio not found: {voice_reference.audio_path}", file=sys.stderr)
        return 1

    if not voice_reference.text_path.exists():
        if args.ref_text is None:
            print(
                f"Reference transcript not found: {voice_reference.text_path}. "
                f"Add {REFERENCE_TEXT_FILENAME} under {voice_reference.reference_dir} or pass --ref-text.",
                file=sys.stderr,
            )
        else:
            print(f"Reference transcript not found: {voice_reference.text_path}", file=sys.stderr)
        return 1

    script_text = script_path.read_text(encoding="utf-8")
    chunks = parse_script_chunks(script_text)

    print_chunk_summary(script_path, chunks)

    try:
        validate_script_input(script_path, script_text, chunks)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    output_tag = resolve_output_tag(style_path, args.tag)
    mp3_path = output_dir / f"voiceover_{output_tag}_voiceclone.mp3"
    manifest_path = output_dir / f"voiceover_{output_tag}_voiceclone.manifest.json"

    if torch.cuda.is_available():
        print(
            f"[cuda] {torch.cuda.get_device_name(0)} "
            f"({torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB)"
        )

    total_t0 = time.time()
    model = load_model()
    voice_prompt = build_voice_prompt(
        model,
        voice_reference.audio_path,
        voice_reference.text_path,
    )
    run_full_generation(model, chunks, voice_prompt, mp3_path, manifest_path)
    print(f"[done] wall time {(time.time() - total_t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())