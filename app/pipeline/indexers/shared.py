from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

from app.pipeline.common.json_io import dump_json, load_json
from .base import (
    VisualIndexerStrategy,
    detect_shot_boundaries,
    get_video_duration,
    merge_segments,
    snap_to_shot_boundaries,
)

DEFAULT_SHOT_SNAP_TOLERANCE_S = 1.5
DEFAULT_SHOT_DETECT_THRESHOLD = 0.3
TIMESTAMP_FONT_PATH_ENV = "STAGE0_TIMESTAMP_FONT_PATH"


def _resolve_timestamp_font_path() -> Path:
    raw_font_path = os.getenv(TIMESTAMP_FONT_PATH_ENV)
    if not raw_font_path:
        raise RuntimeError(f"{TIMESTAMP_FONT_PATH_ENV} is not set in the environment")

    font_path = Path(raw_font_path).expanduser()
    if not font_path.exists():
        raise FileNotFoundError(f"Configured {TIMESTAMP_FONT_PATH_ENV} does not exist: {font_path}")
    if not font_path.is_file():
        raise FileNotFoundError(f"Configured {TIMESTAMP_FONT_PATH_ENV} is not a file: {font_path}")
    return font_path


def _escape_drawtext_fontfile_path(font_path: Path) -> str:
    return font_path.as_posix().replace(":", r"\\:")


def build_timestamp_drawtext_filter(font_path: Path | None = None) -> str:
    active_font_path = font_path if font_path is not None else _resolve_timestamp_font_path()
    if not active_font_path.exists():
        raise FileNotFoundError(f"Timestamp font file does not exist: {active_font_path}")
    if not active_font_path.is_file():
        raise FileNotFoundError(f"Timestamp font path is not a file: {active_font_path}")

    return (
        "drawtext="
        f"fontfile={_escape_drawtext_fontfile_path(active_font_path)}:"
        r"text='%{pts\:hms}':"
        "x=12:y=12:"
        "fontsize=28:fontcolor=white:"
        "box=1:boxcolor=black@0.7:boxborderw=6"
    )


_PROMPT_HEADER = """\
# Role
You are indexing a movie for VISUAL events only. Dialogue is indexed separately from SRT subtitles; do NOT duplicate dialogue coverage here.

# Timestamps (critical)
A chunk-local timestamp in HH:MM:SS.mmm is burned into the TOP-LEFT corner of every frame.
- Read it directly from the frame. Do NOT estimate or round timestamps from context.
- Every "start" and "end" you emit MUST match a timestamp visible in an actual frame.
- Timestamps are relative to this chunk (it always starts at 00:00:00.000), NOT the full movie.

# What to emit
Emit one segment per visually distinct event: a shot cut, a location change, a notable character action, or a significant on-screen text appearance.
- Typical segment length: 2-8 seconds. HARD MAXIMUM: 12 seconds.
- No forced minimum. A 1-second shot cut is a valid segment.
- Let the visible event define the duration. Do NOT invent transitions to fill time.

# What to SKIP (emit nothing for these)
- Pure shot-reverse-shot dialogue with no notable visual change (handled by SRT).
- Long static shots where nothing new is happening - wait for the next visible change.
- Any moment you cannot confidently describe. Omission is always better than a guess.

# Field rules
- summary: one short phrase describing the visible action. No dialogue paraphrasing.
- ocr_text: transcribe on-screen text clearly visible in-scene. Do NOT transcribe the burned-in timestamp in the top-left corner. Empty string if nothing.
"""

_CHARACTERS_RULE_NO_REFERENCE = """\
- characters: only include a character you can visually re-identify across MULTIPLE segments in THIS chunk. If unsure, leave empty. NEVER guess from general knowledge or franchise assumptions.
"""

_CHARACTERS_RULE_WITH_REFERENCE = """\
- characters: name a character ONLY if you can match them to an entry in the Cast Reference below. The reference is the authoritative cast list — do NOT introduce any character not on it. When the same on-screen person appears across multiple segments in this chunk, label them consistently using the reference name. When you genuinely cannot tell which referenced character is on screen, leave the array empty rather than guess.
"""

_PROMPT_FOOTER = """\

# Self-check before returning
- every start < end
- segments are in strictly ascending time order
- no segment longer than 12 seconds
- no start or end exceeds the chunk length
"""


def build_prompt(synopsis_text: str = "", has_face_gallery: bool = False) -> str:
    """Assemble the Stage 0 VLM prompt with an optional Cast Reference block and Face Gallery block.

    When ``synopsis_text`` is empty (no synopsis provided), the character
    rule is the conservative one: only label characters re-identified
    visually across this chunk; never guess from franchise knowledge.

    When ``synopsis_text`` is non-empty, the character rule flips: the
    VLM is allowed (and expected) to label characters using the cast
    list — but is forbidden from introducing characters NOT on the list.
    This is how we get consistent character names across chunks without
    risking franchise-knowledge over-attribution.
    """
    body = _PROMPT_HEADER
    synopsis_text = (synopsis_text or "").strip()
    if synopsis_text:
        body += (
            "\n# Cast Reference (use these names; do not invent others)\n"
            "<<<CAST_REFERENCE_START>>>\n"
            f"{synopsis_text}\n"
            "<<<CAST_REFERENCE_END>>>\n"
        )
        body += _CHARACTERS_RULE_WITH_REFERENCE
    else:
        body += _CHARACTERS_RULE_NO_REFERENCE
    if has_face_gallery:
        body += (
            "\n# Face Gallery (CRITICAL)\n"
            "You have been provided with reference images for the main cast (listed as 'Reference Image for <Name>'). "
            "You MUST use these exact faces and names to label the `characters` array. "
            "Do NOT invent variations of these names.\n"
        )
    body += _PROMPT_FOOTER
    return body


# Default prompt with no Cast Reference. Tests and callers that don't
# need synopsis enrichment can use this directly.
PROMPT = build_prompt()


class ChunkedVisualIndexerStrategy(VisualIndexerStrategy, ABC):
    def __init__(
        self,
        *,
        provider_label: str,
        model_name: str,
        max_workers: int,
        chunk_minutes: int,
        shot_snap_tolerance_s: float = DEFAULT_SHOT_SNAP_TOLERANCE_S,
        shot_detect_threshold: float = DEFAULT_SHOT_DETECT_THRESHOLD,
        synopsis_text: str = "",
        characters_dir: Path | None = None,
    ):
        self.provider_label = provider_label
        self.model_name = model_name
        self.max_workers = max(1, max_workers)
        self.chunk_minutes = chunk_minutes
        self.shot_snap_tolerance_s = shot_snap_tolerance_s
        self.shot_detect_threshold = shot_detect_threshold
        self.synopsis_text = synopsis_text or ""
        self.characters_dir = characters_dir

    @property
    def prompt(self) -> str:
        """The fully-assembled VLM prompt (includes Cast Reference and Face Gallery instructions if present)."""
        return build_prompt(self.synopsis_text, has_face_gallery=self.characters_dir is not None)

    def _get_video_duration(self, video_path: Path) -> float:
        return get_video_duration(video_path)

    def _detect_shot_boundaries(self, video_path: Path) -> List[float]:
        return detect_shot_boundaries(video_path, threshold=self.shot_detect_threshold)

    @abstractmethod
    def _extract_chunk(self, video_path: Path, start_s: float, duration_s: float, out_path: Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def _index_chunk(self, video_chunk_path: Path) -> List[Dict]:
        raise NotImplementedError

    def _chunk_paths(self, tmp_dir: Path, chunk_index: int) -> tuple[Path, Path]:
        chunk_path = tmp_dir / f"chunk_{chunk_index:03d}.mp4"
        segments_path = tmp_dir / "segments" / f"chunk_{chunk_index:03d}.json"
        return chunk_path, segments_path

    def _load_cached_chunk_segments(self, segments_path: Path) -> List[Dict] | None:
        if not segments_path.exists():
            return None

        try:
            cached_segments = load_json(segments_path)
        except Exception as exc:
            print(f"  {segments_path.stem}: cache read failed ({exc}); reprocessing")
            return None

        if not isinstance(cached_segments, list):
            print(f"  {segments_path.stem}: cache payload is not a list; reprocessing")
            return None

        print(f"  {segments_path.stem}: reusing cached segments from {segments_path}")
        return cached_segments

    def _persist_chunk_segments(self, segments_path: Path, chunk_segments: List[Dict]) -> None:
        temp_path = segments_path.with_suffix(".tmp")
        dump_json(temp_path, chunk_segments)
        temp_path.replace(segments_path)

    def _process_chunk(
        self,
        video_path: Path,
        tmp_dir: Path,
        chunk_index: int,
        start_s: float,
        duration_s: float,
    ) -> List[Dict]:
        chunk_path, segments_path = self._chunk_paths(tmp_dir, chunk_index)

        cached_segments = self._load_cached_chunk_segments(segments_path)
        if cached_segments is not None:
            return cached_segments

        if not chunk_path.exists():
            self._extract_chunk(video_path, start_s, duration_s, chunk_path)

        chunk_segments = self._index_chunk(chunk_path)

        boundaries = self._detect_shot_boundaries(chunk_path)
        print(
            f"  chunk_{chunk_index:03d}: {len(chunk_segments)} segments, "
            f"{len(boundaries)} shot cuts; snapping within {self.shot_snap_tolerance_s}s"
        )
        chunk_segments = snap_to_shot_boundaries(
            chunk_segments,
            boundaries,
            tolerance_s=self.shot_snap_tolerance_s,
        )
        self._persist_chunk_segments(segments_path, chunk_segments)
        print(f"  chunk_{chunk_index:03d}: cached segments -> {segments_path}")
        return chunk_segments

    def _process_chunk_job(
        self,
        video_path: Path,
        tmp_dir: Path,
        chunk_index: int,
        start_s: float,
        duration_s: float,
    ) -> tuple[int, List[Dict]]:
        return chunk_index, self._process_chunk(video_path, tmp_dir, chunk_index, start_s, duration_s)

    def index_video(self, video_path: Path, tmp_dir: Path) -> List[Dict]:
        duration = self._get_video_duration(video_path)
        chunk_size_s = self.chunk_minutes * 60
        num_chunks = int((duration + chunk_size_s - 1) // chunk_size_s)
        (tmp_dir / "segments").mkdir(parents=True, exist_ok=True)

        print(
            f"{self.provider_label} Stage 0 running. Video duration: {duration:.2f}s, "
            f"splitting into {num_chunks} chunks of {self.chunk_minutes} minutes."
        )
        if self.max_workers > 1:
            print(
                f"Stage 0 concurrency enabled with {self.max_workers} workers for missing chunk caches. "
                "Higher values can increase 503 risk."
            )

        chunk_specs = []
        for i in range(num_chunks):
            start_s = i * chunk_size_s
            current_chunk_duration = min(chunk_size_s, duration - start_s)
            chunk_specs.append((i, start_s, current_chunk_duration))

        if self.max_workers == 1:
            all_results = [
                self._process_chunk(video_path, tmp_dir, chunk_index, start_s, current_chunk_duration)
                for chunk_index, start_s, current_chunk_duration in chunk_specs
            ]
        else:
            chunk_results_by_index: dict[int, List[Dict]] = {}
            first_error: Exception | None = None
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(
                        self._process_chunk_job,
                        video_path,
                        tmp_dir,
                        chunk_index,
                        start_s,
                        current_chunk_duration,
                    ): chunk_index
                    for chunk_index, start_s, current_chunk_duration in chunk_specs
                }
                for future in as_completed(futures):
                    try:
                        chunk_index, chunk_segments = future.result()
                    except Exception as exc:
                        if first_error is None:
                            first_error = exc
                        continue
                    chunk_results_by_index[chunk_index] = chunk_segments

            if first_error is not None:
                raise first_error

            all_results = [chunk_results_by_index[i] for i in range(num_chunks)]

        return merge_segments(all_results, chunk_size_s)