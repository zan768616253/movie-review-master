from pathlib import Path

from app.pipeline.stage4_align_subtitles import (
    align_chunk_subtitles,
    build_speech_segments,
    choose_natural_windows,
    detect_silence_intervals,
    main,
    split_subtitle_text,
)
from app.pipeline.common.json_io import dump_json, load_json


def test_split_subtitle_text_prefers_punctuation_breaks() -> None:
    cues = split_subtitle_text(
        "注意看，眼前这个弱不禁风的男人叫小帅，他刚刚把自己的灵魂和身体，全部献祭给了怪兽。",
        max_chars=16,
    )
    assert cues == [
        "注意看，",
        "眼前这个弱不禁风的男人叫小帅，",
        "他刚刚把自己的灵魂和身体，",
        "全部献祭给了怪兽。",
    ]


def test_build_speech_segments_subtracts_chunk_local_silence() -> None:
    segments = build_speech_segments(
        chunk_start_s=10.0,
        chunk_end_s=16.0,
        silence_intervals=[(11.5, 12.0), (13.2, 13.8), (20.0, 21.0)],
    )
    assert segments == [(10.0, 11.5), (12.0, 13.2), (13.8, 16.0)]


def test_choose_natural_windows_uses_longest_pause_boundaries() -> None:
    windows = choose_natural_windows(
        [(0.0, 1.0), (1.4, 2.0), (3.0, 4.0), (4.2, 5.0)],
        desired_count=2,
    )
    assert windows == [(0.0, 2.0), (3.0, 5.0)]


def test_align_chunk_subtitles_uses_pause_windows_when_available() -> None:
    cues = align_chunk_subtitles(
        chunk_index=3,
        text="第一句。第二句。第三句。",
        chunk_start_s=0.0,
        chunk_end_s=6.0,
        silence_intervals=[(1.5, 1.9), (3.8, 4.4)],
        max_chars=8,
    )
    assert cues == [
        {"chunk_index": 3, "text": "第一句。", "start_s": 0.0, "end_s": 1.5},
        {"chunk_index": 3, "text": "第二句。", "start_s": 1.9, "end_s": 3.8},
        {"chunk_index": 3, "text": "第三句。", "start_s": 4.4, "end_s": 6.0},
    ]


def test_detect_silence_intervals_parses_ffmpeg_output(tmp_path: Path, monkeypatch) -> None:
    class FakeProc:
        stderr = (
            "[silencedetect @ 0x1] silence_start:1.25\n"
            "[silencedetect @ 0x1] silence_end:1.75 | silence_duration:0.50\n"
            "[silencedetect @ 0x1] silence_start:4.0\n"
            "[silencedetect @ 0x1] silence_end:4.4 | silence_duration:0.40\n"
        )

    monkeypatch.setattr(
        "app.pipeline.stage4_align_subtitles.subprocess.run",
        lambda *args, **kwargs: FakeProc(),
    )

    assert detect_silence_intervals(tmp_path / "voiceover.mp3") == [(1.25, 1.75), (4.0, 4.4)]


def test_main_writes_subtitle_manifest(tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "voiceover.manifest.json"
    voiceover_path = tmp_path / "voiceover.mp3"
    output_path = tmp_path / "subtitle_manifest.json"
    voiceover_path.write_bytes(b"audio")
    dump_json(
        manifest_path,
        [
            {
                "index": 1,
                "text": "第一句。第二句。",
                "audio_start_s": 0.0,
                "audio_end_s": 4.0,
            }
        ],
    )

    monkeypatch.setattr(
        "app.pipeline.stage4_align_subtitles.detect_silence_intervals",
        lambda path: [(1.8, 2.2)],
    )

    result = main([
        "--manifest", str(manifest_path),
        "--voiceover", str(voiceover_path),
        "--output", str(output_path),
    ])

    assert result == 0
    assert load_json(output_path) == [
        {
            "index": 1,
            "chunk_index": 1,
            "text": "第一句。",
            "start_s": 0.0,
            "end_s": 1.8,
        },
        {
            "index": 2,
            "chunk_index": 1,
            "text": "第二句。",
            "start_s": 2.2,
            "end_s": 4.0,
        },
    ]
