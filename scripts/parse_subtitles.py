import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


_SUBTITLE_BREAK_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SUBTITLE_TAG_PATTERN = re.compile(r"\{[^}]*\}|<[^>]+>", re.IGNORECASE)
_SRT_TIMING_PATTERN = re.compile(
    r"^(?P<start>\d+:\d{2}:\d{2}[,.]\d+)\s*-->\s*(?P<end>\d+:\d{2}:\d{2}[,.]\d+)(?:\s+.*)?$"
)


@dataclass
class Subtitle:
    start: float
    end: float
    text: str
    speaker: str | None = None
    style: str | None = None


class SubtitleParser(ABC):
    """Base class for subtitle parsers."""

    @abstractmethod
    def parse(self, file_name: str | Path) -> list[Subtitle]:
        """Parse subtitle content into Subtitle objects."""

    def generate_scripts(self, file_name: str | Path) -> Path:
        """Generate a text file from parsed subtitles and return its path."""
        subtitles = self.parse(file_name)
        scripts_path = Path(file_name).with_suffix(".txt")
        lines: list[str] = []
        for subtitle in subtitles:
            text = subtitle.text.replace("\\N", "\n").strip()
            lines.append(text)

        scripts_path.write_text("\n".join(lines), encoding="utf-8")
        return scripts_path


class AssSubtitleParser(SubtitleParser):
    """Parse ASS subtitle files."""

    def parse(self, file_name: str | Path) -> list[Subtitle]:
        subtitles: list[Subtitle] = []
        event_start = False

        with Path(file_name).open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if not event_start:
                    if line == "[Events]":
                        event_start = True
                    continue

                if not line.startswith("Dialogue:"):
                    continue

                parts = line.split(",", 9)
                if len(parts) < 10:
                    continue

                subtitles.append(
                    Subtitle(
                        start=parse_timestamp(parts[1]),
                        end=parse_timestamp(parts[2]),
                        text=strip_tags(parts[9]),
                        speaker=parts[4],
                        style=parts[3],
                    )
                )

        return subtitles


class SrtSubtitleParser(SubtitleParser):
    """Parse SRT subtitle files."""

    def parse(self, file_name: str | Path) -> list[Subtitle]:
        subtitles: list[Subtitle] = []
        block: list[str] = []

        with Path(file_name).open("r", encoding="utf-8-sig") as file:
            for raw_line in file:
                line = raw_line.rstrip("\r\n")

                if line.strip():
                    block.append(line)
                    continue

                subtitle = self._parse_block(block)
                if subtitle is not None:
                    subtitles.append(subtitle)
                block = []

        subtitle = self._parse_block(block)
        if subtitle is not None:
            subtitles.append(subtitle)

        return subtitles

    def _parse_block(self, block: list[str]) -> Subtitle | None:
        if not block:
            return None

        lines = [line.strip("\ufeff") for line in block]
        line_index = 0

        if lines[0].strip().isdigit():
            line_index = 1

        if line_index >= len(lines):
            return None

        timing_match = _SRT_TIMING_PATTERN.match(lines[line_index].strip())
        if timing_match is None:
            return None

        text = strip_tags("\n".join(lines[line_index + 1 :]))

        return Subtitle(
            start=parse_timestamp(timing_match.group("start")),
            end=parse_timestamp(timing_match.group("end")),
            text=text,
        )


SUBTITLE_PARSER_REGISTRY: dict[str, type[SubtitleParser]] = {
    ".ass": AssSubtitleParser,
    ".srt": SrtSubtitleParser,
}


def parse_timestamp(timestamp: str) -> float:
    """
    Convert a timestamp in the format 'H:MM:SS.cs' or 'H:MM:SS,ms' to seconds.
    Input example: 0:00:18.50
    """
    normalized_timestamp = timestamp.strip().replace(",", ".")
    hour, minute, second = normalized_timestamp.split(":")
    return int(hour) * 3600 + int(minute) * 60 + float(second)


def strip_tags(text: str) -> str:
    """
    Remove subtitle markup from text.
    Input example: 因为有些事情{\b1}不能{\b0}用法律解决
    Output example: 因为有些事情不能用法律解决
    """
    text = _SUBTITLE_BREAK_PATTERN.sub("\n", text)
    return _SUBTITLE_TAG_PATTERN.sub("", text)


def get_subtitle_parser(file_name: str | Path) -> SubtitleParser:
    suffix = Path(file_name).suffix.lower()
    parser_class = SUBTITLE_PARSER_REGISTRY.get(suffix)

    if parser_class is None:
        raise ValueError(f"Unsupported subtitle format: {suffix or '<none>'}")

    return parser_class()


def parse_subtitles(file_name: str | Path) -> list[Subtitle]:
    """Parse subtitles for a supported file type using the parser registry."""
    return get_subtitle_parser(file_name).parse(file_name)


def generate_subtitle_scripts(file_name: str | Path) -> Path:
    """Generate a text script file for any supported subtitle type."""
    return get_subtitle_parser(file_name).generate_scripts(file_name)


def parse_ass(file_name: str | Path) -> list[Subtitle]:
    """Parse an ASS subtitle file and return a list of Subtitle objects."""
    return AssSubtitleParser().parse(file_name)


def generate_ass_scripts(file_name: str | Path) -> Path:
    """Generate a text file from an ASS subtitle file and return its path."""
    return AssSubtitleParser().generate_scripts(file_name)


def parse_srt(file_name: str | Path) -> list[Subtitle]:
    """Parse an SRT subtitle file and return a list of Subtitle objects."""
    return SrtSubtitleParser().parse(file_name)


def generate_srt_scripts(file_name: str | Path) -> Path:
    """Generate a text file from an SRT subtitle file and return its path."""
    return SrtSubtitleParser().generate_scripts(file_name)