import argparse
import re
import sys
import json

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from itertools import chain
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


class AssSubtitleParser(SubtitleParser):
    """Parse ASS subtitle files."""

    def parse(self, file_name: str | Path) -> list[Subtitle]:
        subtitles: list[Subtitle] = []
        event_start = False

        with Path(file_name).open("r", encoding="utf-8-sig") as file:
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
                        text=normalize_subtitle_text(parts[9]),
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

        # Many SRT files (especially from Windows tools) include a BOM
        with Path(file_name).open("r", encoding="utf-8-sig") as file:
            for raw_line in chain(file, [""]):
                line = raw_line.rstrip("\r\n")

                if line.strip():
                    block.append(line)
                    continue

                subtitle = self._parse_block(block)
                if subtitle is not None:
                    subtitles.append(subtitle)
                block.clear()

        return subtitles

    def _parse_block(self, block: list[str]) -> Subtitle | None:
        if not block:
            return None

        timing_index = 1 if block[0].strip().isdigit() else 0
        if timing_index >= len(block):
            return None

        timing_match = _SRT_TIMING_PATTERN.match(block[timing_index].strip())
        if timing_match is None:
            return None

        text = normalize_subtitle_text("\n".join(block[timing_index + 1 :]))

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


def normalize_subtitle_text(text: str) -> str:
    """
    Remove subtitle markup from text.
    Input example: 因为有些事情{\b1}不能{\b0}用法律解决
    Output example: 因为有些事情不能用法律解决
    """
    text = _SUBTITLE_BREAK_PATTERN.sub("\n", text)
    text = _SUBTITLE_TAG_PATTERN.sub("", text)
    return text.replace(r"\N", "\n").strip()


def get_subtitle_parser(file_name: str | Path) -> SubtitleParser:
    suffix = Path(file_name).suffix.lower()
    parser_class = SUBTITLE_PARSER_REGISTRY.get(suffix)

    if parser_class is None:
        raise ValueError(f"Unsupported subtitle format: {suffix or '<none>'}")

    return parser_class()


def parse_subtitles(file_name: str | Path) -> list[Subtitle]:
    """Parse subtitles for a supported file type using the parser registry."""
    return get_subtitle_parser(file_name).parse(file_name)


def main() -> int:
    arg_parser = argparse.ArgumentParser(
        prog="parse-subtitles",
        description="Parse .ass or .srt subtitles into a text file.",
    )

    arg_parser.add_argument("input", type=Path, help="Path to subtitle file (.ass or .srt)")
    arg_parser.add_argument(
        "-f", 
        "--format",
        choices=["txt", "json"],
        default="txt",
        help="Output format (default: txt)",
    )
    output_group = arg_parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path (default: <input>.txt next to input)",
    )
    output_group.add_argument(
        "--stdout",
        action="store_true",
        help="Print to stdout instead of writing a file",
    )
    args = arg_parser.parse_args()
    
    try:
        subtitles = parse_subtitles(args.input)

    except FileNotFoundError:
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.format == "txt":
        output_text = "\n".join(subtitle.text for subtitle in subtitles)
    else:
        output_text = json.dumps([asdict(subtitle) for subtitle in subtitles], ensure_ascii=False, indent=2)

    if args.stdout:
        print(output_text)
        return 0

    if args.output is not None:
        output_path = args.output
    else:
        output_path = args.input.with_suffix(".txt" if args.format == "txt" else ".json")

    try:
        output_path.write_text(output_text, encoding="utf-8")
    except OSError as e:
        print(f"Error: could not write to output path {output_path}: {e}", file=sys.stderr)
        return 1

    print(f"Generated subtitle script: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
