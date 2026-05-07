import re
from dataclasses import dataclass

from app.pipeline.common.script_contract import seconds_to_timestamp

_PUNCTUATION_SPLIT_RE = re.compile(r"(?<=[。！？!?；;：:，,、])")

@dataclass(frozen=True)
class TimedChunk:
    index: int
    text: str
    start_s: float
    end_s: float

@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_s: float
    end_s: float
    text: str

def normalize_text_for_match(text: str) -> str:
    return "".join(text.split())

def spoken_char_count(text: str) -> int:
    return max(len(normalize_text_for_match(text)), 1)

def join_fragments(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if (
        left[-1].isascii()
        and left[-1].isalnum()
        and right[0].isascii()
        and right[0].isalnum()
    ):
        return f"{left} {right}"
    return left + right

def split_long_fragment(fragment: str, max_chars_per_cue: int) -> list[str]:
    if spoken_char_count(fragment) <= max_chars_per_cue:
        return [fragment]

    if " " in fragment:
        words = [word for word in fragment.split(" ")]
        words = [w for w in words if w]
        pieces: list[str] = []
        buffer = ""
        for word in words:
            candidate = join_fragments(buffer, word)
            if buffer and spoken_char_count(candidate) > max_chars_per_cue:
                pieces.append(buffer)
                buffer = word
            else:
                buffer = candidate
        if buffer:
            pieces.append(buffer)
        return pieces

    pieces = [
        fragment[i : i + max_chars_per_cue]
        for i in range(0, len(fragment), max_chars_per_cue)
    ]
    if len(pieces) >= 2 and len(pieces[-1]) == 1 and re.fullmatch(r"[。！？!?；;：:，,、…]", pieces[-1]):
        pieces[-2] += pieces[-1]
        pieces.pop()
    return pieces

def split_text_into_cues(text: str, max_chars_per_cue: int) -> list[str]:
    if max_chars_per_cue <= 0:
        raise ValueError("--max-chars-per-cue must be greater than 0")

    fragments: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for fragment in _PUNCTUATION_SPLIT_RE.split(line):
            clean_fragment = fragment.strip()
            if not clean_fragment:
                continue
            fragments.extend(split_long_fragment(clean_fragment, max_chars_per_cue))

    if not fragments:
        return []

    cues: list[str] = []
    buffer = ""
    for fragment in fragments:
        candidate = join_fragments(buffer, fragment)
        if buffer and spoken_char_count(candidate) > max_chars_per_cue:
            cues.append(buffer)
            buffer = fragment
        else:
            buffer = candidate
    if buffer:
        cues.append(buffer)
    return cues

def build_subtitle_cues(
    timed_chunks: list[TimedChunk],
    *,
    max_chars_per_cue: int,
) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    cue_index = 1

    for chunk in timed_chunks:
        text_parts = split_text_into_cues(chunk.text, max_chars_per_cue)
        if not text_parts:
            continue

        total_weight = sum(spoken_char_count(part) for part in text_parts)
        duration_s = chunk.end_s - chunk.start_s
        cursor = chunk.start_s
        consumed_weight = 0

        for part_index, part in enumerate(text_parts, start=1):
            consumed_weight += spoken_char_count(part)
            if part_index == len(text_parts):
                end_s = chunk.end_s
            else:
                end_s = chunk.start_s + duration_s * (consumed_weight / total_weight)
            if end_s <= cursor:
                end_s = cursor + 0.001

            cues.append(
                SubtitleCue(
                    index=cue_index,
                    start_s=cursor,
                    end_s=end_s,
                    text=part,
                )
            )
            cue_index += 1
            cursor = end_s

    return cues

def format_srt_timestamp(seconds: float) -> str:
    return seconds_to_timestamp(seconds).replace(".", ",")

def render_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for cue in cues:
        blocks.append(
            "\n".join(
                [
                    str(cue.index),
                    f"{format_srt_timestamp(cue.start_s)} --> {format_srt_timestamp(cue.end_s)}",
                    cue.text,
                ]
            )
        )
    return "\n\n".join(blocks).rstrip() + "\n"

def render_vtt(cues: list[SubtitleCue]) -> str:
    blocks = ["WEBVTT"]
    for cue in cues:
        blocks.append(
            "\n".join(
                [
                    f"{seconds_to_timestamp(cue.start_s)} --> {seconds_to_timestamp(cue.end_s)}",
                    cue.text,
                ]
            )
        )
    return "\n\n".join(blocks).rstrip() + "\n"
