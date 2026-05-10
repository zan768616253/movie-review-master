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
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

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
STYLE_VOICE_CONFIG_FILENAME = "voice_clone.toml"

VOICE_CONFIG_KEYS: tuple[str, ...] = (
    "temperature",
    "top_p",
    "top_k",
    "repetition_penalty",
    "max_chars_per_request",
    "max_new_tokens",
)

DEFAULT_MAX_CHARS_PER_REQUEST = 120
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.8
DEFAULT_TOP_K = 40
DEFAULT_REPETITION_PENALTY = 1.1
DEFAULT_MAX_NEW_TOKENS = 1024

STRUCTURAL_MARKER_RE = re.compile(r"^\[(?P<label>TITLE|HOOK|CLOSING|ACT[^\]]*)\]$")
ANCHOR_LINE_RE = re.compile(r"^\[ANCHOR\s+(?P<body>.*)\]$")
ANCHOR_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；])")


@dataclass
class Chunk:
    """One narration chunk from the script."""

    index: int
    section: str
    text: str
    ranges: list[tuple[str, str]] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)


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


def resolve_style_voice_config_path(style_path: Path) -> Path:
    return style_path.parent / "voice-assets" / style_path.stem / STYLE_VOICE_CONFIG_FILENAME


def load_style_voice_config(style_path: Path) -> dict[str, Any]:
    """Load per-style TTS sampling overrides from styles/voice-assets/<style>/voice_clone.toml.

    Returns an empty dict if the file is absent. Unknown keys are ignored so the
    file format stays forward-compatible.
    """
    config_path = resolve_style_voice_config_path(style_path)
    if not config_path.exists():
        return {}
    with config_path.open("rb") as f:
        loaded = tomllib.load(f)
    return {key: loaded[key] for key in VOICE_CONFIG_KEYS if key in loaded}


def resolve_voice_setting(
    cli_value: Any,
    style_value: Any,
    default_value: Any,
) -> Any:
    """Pick the highest-priority value: CLI > style config > hardcoded default."""
    if cli_value is not None:
        return cli_value
    if style_value is not None:
        return style_value
    return default_value


def resolve_output_tag(style_path: Path, explicit_tag: Optional[str]) -> str:
    if explicit_tag:
        return explicit_tag
    return style_path.stem


def parse_structural_marker(line: str) -> Optional[str]:
    match = STRUCTURAL_MARKER_RE.match(line)
    if match is None:
        return None
    return match.group("label").strip()


def parse_anchor_line(body: str) -> tuple[list[tuple[str, str]], list[str]]:
    attrs = dict(ANCHOR_ATTR_RE.findall(body))
    ranges: list[tuple[str, str]] = []
    raw_ranges = attrs.get("ranges", "").strip()
    if raw_ranges:
        for piece in raw_ranges.split(","):
            piece = piece.strip()
            if not piece:
                continue
            start, _, end = piece.partition("-")
            if end:
                ranges.append((start.strip(), end.strip()))
    raw_characters = attrs.get("characters", "").strip()
    characters = (
        [c.strip() for c in raw_characters.split(",") if c.strip()]
        if raw_characters
        else []
    )
    return ranges, characters


def parse_script_chunks(script_text: str) -> list[Chunk]:
    """Split a script into spoken chunks.

    Each structural block after `[HOOK]` becomes one chunk. `[ANCHOR ...]`
    lines attach range / character metadata to the surrounding section
    without contributing to the spoken text.
    """
    lines = [raw.strip() for raw in script_text.splitlines()]

    chunks: list[Chunk] = []
    current_section: Optional[str] = None
    pending_lines: list[str] = []
    pending_ranges: list[tuple[str, str]] = []
    pending_characters: list[str] = []
    in_script = False

    def flush() -> None:
        nonlocal pending_lines, pending_ranges, pending_characters
        if pending_lines:
            chunks.append(
                Chunk(
                    index=len(chunks) + 1,
                    section=current_section or "SCRIPT",
                    text="\n".join(pending_lines),
                    ranges=pending_ranges,
                    characters=pending_characters,
                )
            )
        pending_lines = []
        pending_ranges = []
        pending_characters = []

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

        anchor_match = ANCHOR_LINE_RE.match(line)
        if anchor_match is not None:
            anchor_ranges, anchor_characters = parse_anchor_line(anchor_match.group("body"))
            pending_ranges.extend(anchor_ranges)
            if anchor_characters:
                pending_characters = anchor_characters
            continue

        pending_lines.append(line)

    flush()
    return chunks


def _force_split_oversize(unit: str, max_chars: int) -> list[str]:
    """Best-effort split for a single sentence that exceeds max_chars.

    Tries the Chinese comma first, then falls back to a hard char-count slice.
    """
    if len(unit) <= max_chars:
        return [unit]
    parts = [p.strip() for p in unit.split("，") if p.strip()]
    if len(parts) > 1:
        out: list[str] = []
        current = ""
        for part in parts:
            piece = part if part.endswith("，") else part + "，"
            candidate = piece if not current else current + piece
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    out.append(current.rstrip("，"))
                if len(piece) <= max_chars:
                    current = piece
                else:
                    out.extend(
                        piece[i : i + max_chars] for i in range(0, len(piece), max_chars)
                    )
                    current = ""
        if current:
            out.append(current.rstrip("，"))
        return out
    return [unit[i : i + max_chars] for i in range(0, len(unit), max_chars)]


def split_text_for_tts(text: str, max_chars_per_request: int) -> list[str]:
    """Split narration text into TTS requests of at most `max_chars_per_request` chars.

    Splits on Chinese sentence punctuation and newlines so each request ends on a
    natural boundary, then greedily packs sentences (joined by newlines) up to the
    cap. Sentences that exceed the cap on their own are sub-split on commas and,
    as a last resort, by character count.
    """
    if max_chars_per_request <= 0:
        raise ValueError("max_chars_per_request must be positive")

    units: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for piece in SENTENCE_SPLIT_RE.split(paragraph):
            piece = piece.strip()
            if piece:
                units.append(piece)

    requests: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        if len(current) + 1 + len(unit) <= max_chars_per_request:
            current = current + "\n" + unit
        else:
            requests.append(current)
            current = unit
    if current:
        requests.append(current)

    final: list[str] = []
    for request in requests:
        if len(request) <= max_chars_per_request:
            final.append(request)
        else:
            final.extend(_force_split_oversize(request, max_chars_per_request))
    return final


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
    *,
    max_chars_per_request: int = DEFAULT_MAX_CHARS_PER_REQUEST,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    top_k: int = DEFAULT_TOP_K,
    repetition_penalty: float = DEFAULT_REPETITION_PENALTY,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
) -> tuple[list[np.ndarray], int]:
    """Generate one wav per chunk, sub-chunking each into TTS-sized pieces.

    Each chunk is split via `split_text_for_tts` and synthesised piece-by-piece,
    then concatenated so manifest/SRT timing stays per-section. If the model
    truncates at `max_new_tokens` (cap-hit heuristic), char and token limits are
    halved and the remaining pieces are re-split before retrying.
    """
    try:
        import torch  # type: ignore

        cuda_available = torch.cuda.is_available()
    except Exception:
        torch = None  # type: ignore
        cuda_available = False

    wavs: list[np.ndarray] = []
    sample_rate: Optional[int] = None
    total = len(chunks)

    for chunk in chunks:
        char_limit = max_chars_per_request
        token_limit = max_new_tokens
        pending = split_text_for_tts(chunk.text, char_limit)
        chunk_wavs: list[np.ndarray] = []
        i = 0
        piece_seq = 0
        retries = 0
        max_retries = 4

        while i < len(pending):
            piece = pending[i]
            piece_seq += 1
            t0 = time.time()
            out_wavs, out_sr = model.generate_voice_clone(
                text=piece,
                voice_clone_prompt=voice_prompt,
                language="chinese",
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
                max_new_tokens=token_limit,
            )
            if not out_wavs:
                raise RuntimeError(f"TTS returned no audio for chunk {chunk.index}")

            wav = np.asarray(out_wavs[0], dtype=np.float32)
            sample_rate = out_sr

            if len(wav) == token_limit and retries < max_retries:
                retries += 1
                new_char_limit = max(char_limit // 2, 20)
                new_token_limit = max(token_limit // 2, 256)
                if new_char_limit == char_limit and new_token_limit == token_limit:
                    chunk_wavs.append(wav)
                    i += 1
                    continue
                remaining = "\n".join(pending[i:])
                pending = pending[:i] + split_text_for_tts(remaining, new_char_limit)
                print(
                    f"[gen  {chunk.index:>3}/{total} piece {piece_seq:>2}] "
                    f"{chunk.section:>16} cap hit "
                    f"({len(piece)}ch, max_new_tokens={token_limit}) -> "
                    f"halving to {new_char_limit}ch / {new_token_limit} tokens"
                )
                char_limit = new_char_limit
                token_limit = new_token_limit
                continue

            chunk_wavs.append(wav)
            audio_s = len(wav) / out_sr
            print(
                f"[gen  {chunk.index:>3}/{total} piece {piece_seq:>2}/{len(pending)}] "
                f"{chunk.section:>16} "
                f"{len(piece):>3}ch "
                f"-> {audio_s:5.1f}s audio in {time.time() - t0:5.1f}s"
            )
            i += 1

            if cuda_available and torch is not None:
                torch.cuda.empty_cache()

        if not chunk_wavs:
            raise RuntimeError(f"No audio produced for chunk {chunk.index}")
        wavs.append(np.concatenate(chunk_wavs))

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
            "ranges": [list(r) for r in chunk.ranges],
            "characters": list(chunk.characters),
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
    max_chars_per_request: int = DEFAULT_MAX_CHARS_PER_REQUEST,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    top_k: int = DEFAULT_TOP_K,
    repetition_penalty: float = DEFAULT_REPETITION_PENALTY,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    run_cmd=subprocess.run,
) -> None:
    wavs, sample_rate = generate_chunks(
        model,
        chunks,
        voice_prompt,
        max_chars_per_request=max_chars_per_request,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
        max_new_tokens=max_new_tokens,
    )
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
    parser.add_argument(
        "--max-chars-per-request",
        type=int,
        default=None,
        help=(
            "Max characters per TTS request. Long sections are split on Chinese sentence punctuation. "
            f"Falls back to the style's voice_clone.toml, then {DEFAULT_MAX_CHARS_PER_REQUEST}."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help=(
            "Sampling temperature. Lower = sharper distribution, less drift toward laugh/breath tokens. "
            f"Falls back to the style's voice_clone.toml, then {DEFAULT_TEMPERATURE}."
        ),
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=None,
        help=(
            "Nucleus sampling threshold. Lower truncates the codec-vocab tail (where laughs/sighs live). "
            f"Falls back to the style's voice_clone.toml, then {DEFAULT_TOP_P}."
        ),
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help=(
            "Hard cap on candidate tokens per sampling step. "
            f"Falls back to the style's voice_clone.toml, then {DEFAULT_TOP_K}."
        ),
    )
    parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=None,
        help=(
            "Penalty applied to recently sampled tokens to avoid getting stuck on non-speech loops. "
            f"Falls back to the style's voice_clone.toml, then {DEFAULT_REPETITION_PENALTY}."
        ),
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=None,
        help=(
            "Hard cap on codec frames per request. Cap-hit triggers a halve-and-retry. "
            f"Falls back to the style's voice_clone.toml, then {DEFAULT_MAX_NEW_TOKENS}."
        ),
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
        style_voice = load_style_voice_config(style_path)
        if style_voice:
            print(f"[voice-config] {resolve_style_voice_config_path(style_path)}")
            for key in VOICE_CONFIG_KEYS:
                if key in style_voice:
                    print(f"  {key} = {style_voice[key]}")
        else:
            print(
                f"[voice-config] no voice_clone.toml at "
                f"{resolve_style_voice_config_path(style_path)} — using built-in defaults"
            )

        resolved = {
            key: resolve_voice_setting(getattr(args, key), style_voice.get(key), default)
            for key, default in (
                ("max_chars_per_request", DEFAULT_MAX_CHARS_PER_REQUEST),
                ("temperature", DEFAULT_TEMPERATURE),
                ("top_p", DEFAULT_TOP_P),
                ("top_k", DEFAULT_TOP_K),
                ("repetition_penalty", DEFAULT_REPETITION_PENALTY),
                ("max_new_tokens", DEFAULT_MAX_NEW_TOKENS),
            )
        }

        run_full_generation(
            model,
            chunks,
            voice_prompt,
            mp3_path,
            manifest_path,
            subtitle_path,
            max_chars_per_request=resolved["max_chars_per_request"],
            temperature=resolved["temperature"],
            top_p=resolved["top_p"],
            top_k=resolved["top_k"],
            repetition_penalty=resolved["repetition_penalty"],
            max_new_tokens=resolved["max_new_tokens"],
            run_cmd=run_cmd,
        )
        print(f"[done] wall time {(time.time() - total_t0) / 60:.1f} min")
        return 0
    except (FileNotFoundError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())