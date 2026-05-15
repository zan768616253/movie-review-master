"""Shared timeline helpers used by every Stage 2 pass."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.common.script_contract import (
    seconds_to_timestamp,
    timestamp_to_seconds,
)


@dataclass(frozen=True)
class TimelineEntry:
    kind: str
    start_s: float
    end_s: float
    body: str
    priority: int
    sequence: int

    def render(self) -> str:
        start = seconds_to_timestamp(self.start_s)
        end = seconds_to_timestamp(self.end_s)
        return f"[{self.kind} {start} -> {end}] {self.body}"


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*\n", re.DOTALL)
_SUBTITLE_TXT_PATTERN = re.compile(
    r"^\[(?P<start>\d{2}:\d{2}:\d{2}\.\d+) -> (?P<end>\d{2}:\d{2}:\d{2}\.\d+)\]\s*(?P<body>.*)$"
)


def normalize_inline_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    return " / ".join(part.strip() for part in text.split("\n") if part.strip())


def read_text_strict(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Text file is empty: {path}")
    return text


def parse_style_frontmatter(style_text: str) -> tuple[dict[str, object], str]:
    """Extract simple key-value frontmatter from a style markdown file."""
    m = _FRONTMATTER_RE.match(style_text)
    if not m:
        return {}, style_text
    meta: dict[str, object] = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        for convert in (int, float):
            try:
                val = convert(val)  # type: ignore[assignment]
                break
            except (ValueError, TypeError):
                continue
        meta[key] = val
    return meta, style_text[m.end():]


def load_subtitles(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    subtitles: list[dict[str, object]] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = _SUBTITLE_TXT_PATTERN.match(line)
        if not match:
            raise ValueError(f"Invalid subtitle line format: {line}")
        subtitles.append({
            "start": match.group("start"),
            "end": match.group("end"),
            "text": match.group("body"),
        })
    return subtitles


def build_timeline_entries(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []

    for index, segment in enumerate(visual_segments):
        try:
            start = str(segment["start"])
            end = str(segment["end"])
        except KeyError as exc:
            raise ValueError(f"Visual segment #{index + 1} is missing {exc.args[0]!r}") from exc

        start_s = timestamp_to_seconds(start)
        end_s = timestamp_to_seconds(end)
        if end_s <= start_s:
            raise ValueError(f"Visual segment #{index + 1} has end <= start")

        segment_id = str(segment.get("id") or f"visual:{index + 1:03d}")
        summary = normalize_inline_text(segment.get("summary")) or "(no visual summary)"
        parts = [f"{segment_id} | {summary}"]

        characters = segment.get("characters")
        if isinstance(characters, list):
            character_names = [normalize_inline_text(item) for item in characters if normalize_inline_text(item)]
            if character_names:
                parts.append(f"characters: {', '.join(character_names)}")

        ocr_text = normalize_inline_text(segment.get("ocr_text"))
        if ocr_text:
            parts.append(f"on-screen text: {ocr_text}")

        entries.append(TimelineEntry(
            kind="VISUAL",
            start_s=start_s,
            end_s=end_s,
            body=" | ".join(parts),
            priority=0,
            sequence=index,
        ))

    for index, subtitle in enumerate(subtitles):
        try:
            start_s = timestamp_to_seconds(str(subtitle["start"]))
            end_s = timestamp_to_seconds(str(subtitle["end"]))
        except KeyError as exc:
            raise ValueError(f"Subtitle #{index + 1} is missing {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Subtitle #{index + 1} has invalid timing values") from exc

        if end_s <= start_s:
            raise ValueError(f"Subtitle #{index + 1} has end <= start")

        text = normalize_inline_text(subtitle.get("text"))
        if not text:
            continue

        speaker = normalize_inline_text(subtitle.get("speaker"))
        body = f"{speaker}: {text}" if speaker else text

        entries.append(TimelineEntry(
            kind="SUBTITLE",
            start_s=start_s,
            end_s=end_s,
            body=body,
            priority=1,
            sequence=index,
        ))

    return sorted(entries, key=lambda item: (item.start_s, item.priority, item.end_s, item.sequence))


def render_timeline(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> str:
    return "\n".join(entry.render() for entry in build_timeline_entries(visual_segments, subtitles))
