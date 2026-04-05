from pathlib import Path

from scripts.parse_subtitles  import Subtitle, parse_ass, parse_timestamp, strip_tags 

def test_parse_timestamp():
    timestamp = "00:01:23.456"
    output = parse_timestamp(timestamp)
    assert output == 83.456