from pathlib import Path

from scripts.parse_subtitles  import Subtitle, generate_ass_scripts, parse_ass, parse_timestamp, strip_tags 

def test_parse_timestamp():
    timestamp = "00:01:23.456"
    output = parse_timestamp(timestamp)
    assert output == 83.456

def test_strip_tags():
    text = "因为有些事情{\b1}不能{\b0}用法律解决"
    output = strip_tags(text)
    assert output == "因为有些事情不能用法律解决"


expected_sample_movie_ass_scripts = """你知道吗？这个世界上有一种人
他们天生就与众不同
我叫张伟，今年三十五岁
十年前我是一名警察
你为什么要离开警队？
因为有些事情不能用法律解决
三年后 — 上海
我从没想过会再见到她
张伟？是你吗？
李娜……你怎么会在这里
我现在在做一些危险的事情
Nobody leaves this organization alive.
你不用害怕，我会保护你
两个曾经相爱的人，再次被命运绑在了一起
就算拼上这条命我也要把你救出来"""

def test_parse_ass():
    sample_movie_path = Path.joinpath(Path(__file__).parent, "fixtures", "sample_movie.ass")
    subtitle_list = parse_ass(sample_movie_path)
    expected_subtitle_text_list = expected_sample_movie_ass_scripts.split("\n")
    assert len(subtitle_list) == len(expected_subtitle_text_list)
    subtitle_list = [subtitle.text for subtitle in subtitle_list]
    assert subtitle_list == expected_subtitle_text_list

def test_generate_ass_scripts():
    sample_movie_path = Path.joinpath(Path(__file__).parent, "fixtures", "sample_movie.ass")
    scripts_path = generate_ass_scripts(sample_movie_path)
    with open(scripts_path, "r", encoding="utf-8") as f:
        output = f.read()
    assert output == expected_sample_movie_ass_scripts