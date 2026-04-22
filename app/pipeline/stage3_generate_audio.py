"""Stage 3 voiceover generation for the current Style A path.

The script is split on [SCENE] markers, spoken chunk by chunk through Qwen3
voice cloning, concatenated into one normalized voiceover, and written with a
manifest that keeps the render sync contract intact.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import torch


BASE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
REPO_ROOT = Path(__file__).resolve().parents[2]
VOICE_ASSETS_DIR = REPO_ROOT / "voice-assets"
DEFAULT_REF_AUDIO = VOICE_ASSETS_DIR / "uncle_niu" / "reference" / "clone_reference.mp3"
DEFAULT_REF_TEXT = VOICE_ASSETS_DIR / "uncle_niu" / "reference" / "clone_reference.txt"

SCENE_RE = re.compile(
    r"\[SCENE:\s*(\d{2}:\d{2}:\d{2})\s*-\s*(\d{2}:\d{2}:\d{2})\s*\]"
)
BROLL_LINE_RE = re.compile(r"\[BROLL:\s*([^\]]+?)\s*\]")
BROLL_RANGE_RE = re.compile(r"(\d{2}:\d{2}:\d{2})\s*-\s*(\d{2}:\d{2}:\d{2})")
STRUCTURAL_MARKER_RE = re.compile(r"^\s*\[(TITLE|HOOK|ACT\s*\d+[^\]]*|CLOSING)\]")


@dataclass
class Chunk:
    index: int
    scene_start: Optional[str]
    scene_end: Optional[str]
    text: str
    broll: list[tuple[str, str]] = field(default_factory=list)


def parse_broll_ranges(text: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in BROLL_RANGE_RE.finditer(text)]


def append_chunk(
    chunks: list[Chunk],
    scene: Optional[tuple[str, str]],
    lines: list[str],
    broll: list[tuple[str, str]],
) -> None:
    if not lines:
        return

    scene_start, scene_end = scene if scene is not None else (None, None)
    chunks.append(
        Chunk(
            index=len(chunks) + 1,
            scene_start=scene_start,
            scene_end=scene_end,
            text="\n".join(lines),
            broll=list(broll) if scene is not None else [],
        )
    )


def parse_script_chunks(script_text: str) -> list[Chunk]:
    """Split a marked script into narration chunks."""
    chunks: list[Chunk] = []
    current_scene: Optional[tuple[str, str]] = None
    pending_lines: list[str] = []
    pending_broll: list[tuple[str, str]] = []
    in_script = False

    def flush() -> None:
        append_chunk(chunks, current_scene, pending_lines, pending_broll)

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
                pending_lines = []
                pending_broll = []
                current_scene = None
            continue

        scene_match = SCENE_RE.search(line)
        if scene_match:
            flush()
            pending_lines = []
            pending_broll = []
            current_scene = (scene_match.group(1), scene_match.group(2))
            continue

        broll_match = BROLL_LINE_RE.search(line)
        if broll_match:
            pending_broll.extend(parse_broll_ranges(broll_match.group(1)))
            continue

        pending_lines.append(line)

    flush()
    return chunks


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
    ref_text = ref_text_path.read_text(encoding="utf-8").strip()
    print(f"[prompt] ref audio {ref_audio.name}, transcript {len(ref_text)} chars")
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


def build_manifest_payload(
    chunks: list[Chunk],
    audio_ranges: list[tuple[float, float]],
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for chunk, (start_s, end_s) in zip(chunks, audio_ranges):
        payload.append(
            {
                "index": chunk.index,
                "scene_start": chunk.scene_start,
                "scene_end": chunk.scene_end,
                "text": chunk.text,
                "broll": [[start, end] for (start, end) in chunk.broll],
                "audio_start_s": start_s,
                "audio_end_s": end_s,
            }
        )
    return payload


def write_manifest(
    chunks: list[Chunk],
    audio_ranges: list[tuple[float, float]],
    out_path: Path,
) -> None:
    out_path.write_text(
        json.dumps(build_manifest_payload(chunks, audio_ranges), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_manifest_timings(manifest_path: Path) -> list[tuple[float, float]]:
    existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        (float(entry["audio_start_s"]), float(entry["audio_end_s"]))
        for entry in existing
    ]


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


def rewrite_manifest_only(chunks: list[Chunk], manifest_path: Path) -> int:
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}. Run without --manifest-only first.", file=sys.stderr)
        return 1

    audio_ranges = load_manifest_timings(manifest_path)
    if len(audio_ranges) != len(chunks):
        print(
            f"Chunk count mismatch: script has {len(chunks)}, manifest has {len(audio_ranges)}. "
            f"Full TTS rerun required.",
            file=sys.stderr,
        )
        return 1

    write_manifest(chunks, audio_ranges, manifest_path)
    print(f"[done] manifest-only update: {manifest_path}")
    return 0


def run_full_generation(
    model,
    chunks: list[Chunk],
    voice_prompt: object,
    mp3_path: Path,
    manifest_path: Path,
) -> float:
    wavs, sample_rate = generate_chunks(model, chunks, voice_prompt)
    audio_ranges = concat_and_normalize(wavs, sample_rate, mp3_path)
    write_manifest(chunks, audio_ranges, manifest_path)

    total_audio_s = audio_ranges[-1][1] if audio_ranges else 0.0
    print(f"\n[done] {len(chunks)} chunks -> {total_audio_s:.1f}s audio ({total_audio_s / 60:.1f} min)")
    print(f"[done] {mp3_path}")
    print(f"[done] {manifest_path}")
    return total_audio_s


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate-audio",
        description="Stage 3: TTS a marked script into one voiceover and manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--script", type=Path, required=True)
    parser.add_argument(
        "--ref-audio",
        type=Path,
        default=DEFAULT_REF_AUDIO,
        help="Voice clone reference.",
    )
    parser.add_argument(
        "--ref-text",
        type=Path,
        default=DEFAULT_REF_TEXT,
        help="Transcript of reference audio.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--tag",
        default="niu-shu",
        help="Filename tag, used in voiceover_<tag>_voiceclone.{mp3,manifest.json}",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the chunk summary, skip TTS")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N chunks")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Skip TTS and rewrite the manifest using existing timings. Requires the same chunk count.",
    )
    args = parser.parse_args(argv)

    script_text = args.script.read_text(encoding="utf-8")
    chunks = parse_script_chunks(script_text)

    if args.limit is not None:
        chunks = chunks[: args.limit]

    print_chunk_summary(args.script, chunks)

    if not chunks:
        print(f"No narration chunks found in {args.script}", file=sys.stderr)
        return 1

    if args.dry_run:
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    mp3_path = args.output_dir / f"voiceover_{args.tag}_voiceclone.mp3"
    manifest_path = args.output_dir / f"voiceover_{args.tag}_voiceclone.manifest.json"

    if args.manifest_only:
        return rewrite_manifest_only(chunks, manifest_path)

    if torch.cuda.is_available():
        print(
            f"[cuda] {torch.cuda.get_device_name(0)} "
            f"({torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB)"
        )

    total_t0 = time.time()
    model = load_model()
    voice_prompt = build_voice_prompt(model, args.ref_audio, args.ref_text)
    run_full_generation(model, chunks, voice_prompt, mp3_path, manifest_path)
    print(f"[done] wall time {(time.time() - total_t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())