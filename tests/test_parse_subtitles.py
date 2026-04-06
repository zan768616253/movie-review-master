from pathlib import Path

from scripts.parse_subtitles  import Subtitle, parse_ass, parse_timestamp, strip_tags 

def test_parse_timestamp():
    timestamp = "00:01:23.456"
    output = parse_timestamp(timestamp)
    assert output == 83.456

def test_strip_tags():
    text = "因为有些事情{\b1}不能{\b0}用法律解决"
    output = strip_tags(text)
    assert output == "因为有些事情不能用法律解决"