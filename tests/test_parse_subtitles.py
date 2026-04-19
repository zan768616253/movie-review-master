import sys
from pathlib import Path
from shutil import copyfile

import pytest

from scripts.parse_subtitles import (
    main,
    parse_subtitles,
    parse_timestamp,
    strip_tags,
)


EXPECTED_SAMPLE_MOVIE_ASS_SCRIPTS = """你知道吗？这个世界上有一种人
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

EXPECTED_SAMPLE_MOVIE_SRT_SCRIPTS = """本字幕由豌豆&风之圣殿字幕组联合制作
仅供学习交流 禁止用于商业用途
好久不见了啊 乙骨
别过来
喂喂 别这么冷漠嘛
不可以
你知道我有多想揍你一顿吗"""

EXPECTED_SAMPLE_MOVIE_SRT_TEXTS = [
    "本字幕由豌豆&风之圣殿字幕组联合制作\n仅供学习交流 禁止用于商业用途",
    "好久不见了啊 乙骨",
    "别过来",
    "喂喂 别这么冷漠嘛",
    "不可以",
    "你知道我有多想揍你一顿吗",
]


def copy_fixture(tmp_path: Path, fixture_name: str) -> Path:
    source_path = Path(__file__).parent / "fixtures" / fixture_name
    destination_path = tmp_path / fixture_name
    copyfile(source_path, destination_path)
    return destination_path


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("00:01:23.456", 83.456),
        ("00:01:23,456", 83.456),
    ],
)
def test_parse_timestamp(timestamp: str, expected: float):
    output = parse_timestamp(timestamp)
    assert output == pytest.approx(expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (r"因为有些事情{\b1}不能{\b0}用法律解决", "因为有些事情不能用法律解决"),
        ("<i>别过来</i>", "别过来"),
        ("这<br/>里<br />有换行", "这\n里\n有换行"),
    ],
)
def test_strip_tags(text: str, expected: str):
    output = strip_tags(text)
    assert output == expected


@pytest.mark.parametrize(
    ("fixture_name", "expected_texts"),
    [
        ("sample_movie.ass", EXPECTED_SAMPLE_MOVIE_ASS_SCRIPTS.split("\n")),
        ("sample_movie.srt", EXPECTED_SAMPLE_MOVIE_SRT_TEXTS),
    ],
)
def test_parse_subtitles(tmp_path: Path, fixture_name: str, expected_texts: list[str]):
    sample_movie_path = copy_fixture(tmp_path, fixture_name)
    subtitle_list = parse_subtitles(sample_movie_path)

    assert len(subtitle_list) == len(expected_texts)
    assert [subtitle.text for subtitle in subtitle_list] == expected_texts


def test_main_writes_default_output(tmp_path: Path, monkeypatch, capsys):
    sample_movie_path = copy_fixture(tmp_path, "sample_movie.srt")
    expected_output_path = sample_movie_path.with_suffix(".txt")

    monkeypatch.setattr(sys, "argv", ["parse-subtitles", str(sample_movie_path)])

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert expected_output_path.read_text(encoding="utf-8") == EXPECTED_SAMPLE_MOVIE_SRT_SCRIPTS
    assert f"Generated subtitle script: {expected_output_path}" in captured.out


def test_main_prints_to_stdout(tmp_path: Path, monkeypatch, capsys):
    sample_movie_path = copy_fixture(tmp_path, "sample_movie.ass")

    monkeypatch.setattr(sys, "argv", ["parse-subtitles", str(sample_movie_path), "--stdout"])

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == EXPECTED_SAMPLE_MOVIE_ASS_SCRIPTS + "\n"
    assert captured.err == ""
    assert not sample_movie_path.with_suffix(".txt").exists()


def test_main_writes_custom_output_path(tmp_path: Path, monkeypatch):
    sample_movie_path = copy_fixture(tmp_path, "sample_movie.srt")
    output_path = tmp_path / "custom_output.txt"

    monkeypatch.setattr(
        sys,
        "argv",
        ["parse-subtitles", str(sample_movie_path), "-o", str(output_path)],
    )

    exit_code = main()

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8") == EXPECTED_SAMPLE_MOVIE_SRT_SCRIPTS


def test_main_reports_missing_input_file(tmp_path: Path, monkeypatch, capsys):
    missing_path = tmp_path / "missing.srt"

    monkeypatch.setattr(sys, "argv", ["parse-subtitles", str(missing_path)])

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Error: input file not found" in captured.err


def test_main_reports_unsupported_format(tmp_path: Path, monkeypatch, capsys):
    unsupported_path = tmp_path / "sample.txt"
    unsupported_path.write_text("not subtitles", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["parse-subtitles", str(unsupported_path)])

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Unsupported subtitle format" in captured.err