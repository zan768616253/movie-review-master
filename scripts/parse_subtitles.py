import re
from dataclasses import dataclass

@dataclass
class Subtitle:
    start: float
    end: float
    text: str
    speaker: str | None = None
    style: str | None = None

def parse_timestamp(timestamp: str) -> float:
    """
    Convert a timestamp in the format 'H:MM:SS.cs' to seconds.
    Input example: 0:00:18.50
    """
    parts = timestamp.split(":")
    hour = parts[0]
    minute = parts[1]
    second = parts[2]
    output = int(hour) * 3600 + int(minute) * 60 + float(second)
    return output

def strip_tags(text: str) -> str:
    """
    Remove text styles from text.
    Input example: 因为有些事情{\b1}不能{\b0}用法律解决
    Output example: 因为有些事情不能用法律解决
    """
    output = re.sub(r"\{[^}]*\}", "", text)
    return output

def parse_ass(file_name: str) -> list[Subtitle]:
    """
    Parse an ASS subtitle file and return a list of Subtitle objects.
    """
    subtitles: list[Subtitle] = []
    event_start = False
    with open(file_name, "r", encoding="utf-8") as f:
       for line in f:
            if not event_start:
                if line.startswith("[Events]"):
                    event_start = True
                else:
                    continue
            
            if not line.startswith("Dialogue:"):
                continue

            line = line.strip()
            parts = line.split(",", 9)

            if len(parts) < 10:
                continue

            start_str = parts[1]
            start = parse_timestamp(start_str)

            end_str = parts[2]
            end = parse_timestamp(end_str)

            style = parts[3]
            speaker = parts[4]

            text = ",".join(parts[9:])

            subtitle = Subtitle(
                start=start, 
                end=end, 
                text=text, 
                speaker=speaker, 
                style=style
            )
            subtitles.append(subtitle)
            
    return subtitles

if __name__ == "__main__":
    pass