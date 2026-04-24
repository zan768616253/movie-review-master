"""Stage 3 voiceover generation for the current Style A path.

The script is split on [SCENE] markers, spoken chunk by chunk through Qwen3
voice cloning, concatenated into one normalized voiceover, and written with a
manifest that keeps the render sync contract intact.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import torch

from app.pipeline.common.script_contract import (
    BROLL_LINE_RE,
    STRUCTURAL_MARKER_RE,
    SceneMarker,
    parse_broll_ranges,
    parse_scene_marker,
)


BASE_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
REPO_ROOT = Path(__file__).resolve().parents[2]
VOICE_ASSETS_DIR = REPO_ROOT / "voice-assets"
DEFAULT_REF_AUDIO = VOICE_ASSETS_DIR / "uncle_niu" / "reference" / "clone_reference.mp3"
DEFAULT_REF_TEXT = VOICE_ASSETS_DIR / "uncle_niu" / "reference" / "clone_reference.txt"
DEFAULT_VOICE_CLONE_MODE = "auto"
DEFAULT_MAX_ICL_REFERENCE_SECONDS = 30.0
DEFAULT_MAX_XVECTOR_REFERENCE_SECONDS = 30.0
PROMPT_TEMPLATE_MARKERS = (
    "<<<BEATS_START>>>",
    "<<<SRT_REFERENCE_START>>>",
    "<<<VISUAL_REFERENCE_START>>>",
    "# Grounding algorithm",
    "# Output contract",
)
MAX_CHARS_PER_CHUNK = 12000


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
    def scene_confidence(self) -> Optional[float]:
        return self.scene.confidence if self.scene else None

    @property
    def scene_evidence(self) -> Optional[str]:
        return self.scene.evidence if self.scene else None

    @property
    def scene_characters(self) -> list[str]:
        return list(self.scene.characters) if self.scene else []


def parse_script_chunks(script_text: str) -> list[Chunk]:
    """Split a marked script into narration chunks."""
    chunks: list[Chunk] = []
    current_scene: Optional[SceneMarker] = None
    pending_lines: list[str] = []
    pending_broll: list[tuple[str, str]] = []
    in_script = False

    def flush() -> None:
        nonlocal pending_lines, pending_broll, current_scene
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


def count_scene_markers(script_text: str) -> int:
    return sum(1 for raw in script_text.splitlines() if parse_scene_marker(raw.strip()) is not None)


def validate_script_input(script_path: Path, script_text: str, chunks: list[Chunk]) -> None:
    if any(marker in script_text for marker in PROMPT_TEMPLATE_MARKERS):
        raise ValueError(
            f"{script_path} looks like the Stage 2 grounding prompt, not the final grounded script. "
            "Paste only the grounder model's final output into grounded_script.txt. "
            "Do not include prompt headers, SRT references, visual references, or <<<...>>> blocks."
        )

    if "[BEAT " in script_text:
        raise ValueError(
            f"{script_path} still contains [BEAT N] markers. Stage 3 expects the final grounded script "
            "with [SCENE ...] markers replacing every beat."
        )

    if count_scene_markers(script_text) == 0:
        raise ValueError(
            f"{script_path} contains no [SCENE ...] markers. Stage 3 expects the grounded Stage 2 output, "
            "not the writer draft or a prompt file."
        )

    longest_chunk = max(chunks, key=lambda chunk: len(chunk.text), default=None)
    if longest_chunk is not None and len(longest_chunk.text) > MAX_CHARS_PER_CHUNK:
        raise ValueError(
            f"{script_path} contains an oversized narration chunk ({len(longest_chunk.text)} chars in chunk "
            f"{longest_chunk.index}). This usually means prompt/reference text was pasted into the grounded "
            "script file instead of only final narration."
        )


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


def probe_audio_duration(audio_path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    text = result.stdout.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def resolve_voice_clone_mode(
    ref_audio: Path,
    requested_mode: str,
    max_icl_reference_seconds: float,
) -> str:
    if requested_mode != "auto":
        return requested_mode

    duration_s = probe_audio_duration(ref_audio)
    if duration_s is None:
        return "icl"
    if duration_s > max_icl_reference_seconds:
        print(
            f"[prompt] reference audio is {duration_s:.1f}s, which exceeds the ICL-safe threshold "
            f"of {max_icl_reference_seconds:.1f}s; switching to x-vector-only voice cloning"
        )
        return "x-vector"
    return "icl"


def prepare_reference_audio_for_prompt(
    ref_audio: Path,
    resolved_mode: str,
    max_xvector_reference_seconds: float,
    scratch_dir: Path,
) -> tuple[Path, float | None]:
    duration_s = probe_audio_duration(ref_audio)
    if (
        resolved_mode != "x-vector"
        or duration_s is None
        or max_xvector_reference_seconds <= 0
        or duration_s <= max_xvector_reference_seconds
    ):
        return ref_audio, duration_s

    scratch_dir.mkdir(parents=True, exist_ok=True)
    trimmed_ref_audio = scratch_dir / f"{ref_audio.stem}.xvector_{int(max_xvector_reference_seconds)}s.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(ref_audio),
            "-t",
            str(max_xvector_reference_seconds),
            "-ac",
            "1",
            "-ar",
            "24000",
            str(trimmed_ref_audio),
        ],
        check=True,
    )
    print(
        f"[prompt] x-vector mode still embeds the reference waveform; trimming {ref_audio.name} "
        f"from {duration_s:.1f}s to {max_xvector_reference_seconds:.1f}s before prompt creation"
    )
    return trimmed_ref_audio, duration_s


def build_voice_prompt(
    model,
    ref_audio: Path,
    ref_text_path: Path,
    scratch_dir: Path,
    voice_clone_mode: str = DEFAULT_VOICE_CLONE_MODE,
    max_icl_reference_seconds: float = DEFAULT_MAX_ICL_REFERENCE_SECONDS,
    max_xvector_reference_seconds: float = DEFAULT_MAX_XVECTOR_REFERENCE_SECONDS,
) -> object:
    resolved_mode = resolve_voice_clone_mode(ref_audio, voice_clone_mode, max_icl_reference_seconds)
    prepared_ref_audio, _duration_s = prepare_reference_audio_for_prompt(
        ref_audio,
        resolved_mode,
        max_xvector_reference_seconds,
        scratch_dir,
    )
    if resolved_mode == "x-vector":
        print(
            f"[prompt] ref audio {prepared_ref_audio.name}, transcript ignored, mode={resolved_mode}"
        )
        return model.create_voice_clone_prompt(
            ref_audio=str(prepared_ref_audio),
            ref_text=None,
            x_vector_only_mode=True,
        )
    ref_text = ref_text_path.read_text(encoding="utf-8").strip()
    print(
        f"[prompt] ref audio {prepared_ref_audio.name}, transcript {len(ref_text)} chars, mode={resolved_mode}"
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
                "scene_source": chunk.scene_source,
                "scene_confidence": chunk.scene_confidence,
                "scene_evidence": chunk.scene_evidence,
                "scene_characters": chunk.scene_characters,
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
    parser.add_argument(
        "--voice-clone-mode",
        choices=["auto", "icl", "x-vector"],
        default=DEFAULT_VOICE_CLONE_MODE,
        help="Voice-clone prompt mode. 'auto' switches long reference clips to x-vector-only mode.",
    )
    parser.add_argument(
        "--max-icl-reference-seconds",
        type=float,
        default=DEFAULT_MAX_ICL_REFERENCE_SECONDS,
        help="When --voice-clone-mode=auto, reference clips longer than this fall back to x-vector-only mode.",
    )
    parser.add_argument(
        "--max-xvector-reference-seconds",
        type=float,
        default=DEFAULT_MAX_XVECTOR_REFERENCE_SECONDS,
        help="When x-vector mode is used, cap the reference clip to this duration before speaker embedding.",
    )
    args = parser.parse_args(argv)

    script_text = args.script.read_text(encoding="utf-8")
    chunks = parse_script_chunks(script_text)

    try:
        validate_script_input(args.script, script_text, chunks)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

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
    voice_prompt = build_voice_prompt(
        model,
        args.ref_audio,
        args.ref_text,
        args.output_dir,
        voice_clone_mode=args.voice_clone_mode,
        max_icl_reference_seconds=args.max_icl_reference_seconds,
        max_xvector_reference_seconds=args.max_xvector_reference_seconds,
    )
    run_full_generation(model, chunks, voice_prompt, mp3_path, manifest_path)
    print(f"[done] wall time {(time.time() - total_t0) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())