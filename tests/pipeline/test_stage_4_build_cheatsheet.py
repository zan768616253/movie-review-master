from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.pipeline.stage_4_build_cheatsheet import (
    ShotInfo,
    _collect_referenced_seg_ids,
    _thumb_filename,
    build_shot_index,
    extract_missing_thumbnails,
    main,
    render_cheatsheet_html,
)


def _sample_manifest() -> list[dict[str, Any]]:
    return [
        {
            "index": 1,
            "section": "HOOK",
            "audio_start_s": 0.0,
            "audio_end_s": 12.3,
            "text": "看完这部片，我整整两天睡不着。\n那场雪山追逐，比我看过的所有动作戏都狠。",
            "segments": [
                {
                    "text": "看完这部片，我整整两天睡不着。",
                    "refs": ["visual:001"],
                    "ranges_s": [[5.0, 9.5]],
                },
                {
                    "text": "那场雪山追逐，比我看过的所有动作戏都狠。",
                    "refs": ["visual:002", "visual:003"],
                    "ranges_s": [[60.0, 64.0], [70.0, 75.0]],
                    "unknown_refs": ["visual:999"],
                },
            ],
        },
        {
            "index": 2,
            "section": "ACT 1 - SETUP",
            "audio_start_s": 12.3,
            "audio_end_s": 25.0,
            "text": "故事开场，老猜每天送女儿去溜冰场学习。",
            "segments": [
                {
                    "text": "故事开场，老猜每天送女儿去溜冰场学习。",
                    "refs": [],
                },
            ],
        },
    ]


def _sample_visual_segments() -> list[dict[str, Any]]:
    return [
        {
            "id": "visual:001",
            "start": "00:00:05.000",
            "end": "00:00:09.500",
            "summary": "老猜抱着女儿走进溜冰场",
            "ocr_text": "",
            "characters": ["老猜", "莎"],
        },
        {
            "id": "visual:002",
            "start": "00:01:00.000",
            "end": "00:01:04.000",
            "summary": "雪山追逐 — 男主开车<撞过路障>",
            "ocr_text": "STOP",
            "characters": ["老猜"],
        },
        {
            "id": "visual:003",
            "start": "00:01:10.000",
            "end": "00:01:15.000",
            "summary": "追逐继续",
            "ocr_text": "",
            "characters": [],
        },
    ]


def test_build_shot_index_uses_normalized_ids_and_timestamps() -> None:
    shots = build_shot_index(_sample_visual_segments())
    assert set(shots) == {"visual:001", "visual:002", "visual:003"}
    one = shots["visual:001"]
    assert (one.start_s, one.end_s) == (5.0, 9.5)
    assert abs(one.mid_s - 7.25) < 1e-6
    assert one.characters == ["老猜", "莎"]


def test_collect_referenced_seg_ids_returns_unique_normalized() -> None:
    manifest = _sample_manifest()
    ids = _collect_referenced_seg_ids(manifest)
    assert ids == {"visual:001", "visual:002", "visual:003"}


def test_render_cheatsheet_html_includes_text_refs_and_warnings() -> None:
    manifest = _sample_manifest()
    shots = build_shot_index(_sample_visual_segments())

    rendered = render_cheatsheet_html(
        title="测试影片",
        manifest=manifest,
        shots=shots,
        thumbnails_dir_name="thumbnails",
        thumbnails_present={"visual:001", "visual:002"},
    )

    assert "Editor Cheatsheet — 测试影片" in rendered
    assert "看完这部片，我整整两天睡不着。" in rendered
    assert "故事开场，老猜每天送女儿去溜冰场学习。" in rendered

    # grounded segments link to their cached thumbnails
    assert 'src="thumbnails/visual_001.jpg"' in rendered
    assert 'src="thumbnails/visual_002.jpg"' in rendered
    # ref with no thumbnail on disk shows a placeholder, not a broken img
    assert 'src="thumbnails/visual_003.jpg"' not in rendered
    assert "no thumbnail" in rendered

    # ungrounded segment flagged
    assert "no footage hint" in rendered
    assert "ungrounded" in rendered

    # unknown_refs surfaced as a warn badge
    assert "unknown ref" in rendered
    assert "visual:999" in rendered

    # shot metadata renders with HTML-escaped content (the test summary has < / >)
    assert "&lt;撞过路障&gt;" in rendered
    assert "STOP" in rendered

    # clipboard hook present for click-to-copy timestamps
    assert "copyTimestamp(" in rendered


def test_render_cheatsheet_html_handles_empty_manifest() -> None:
    rendered = render_cheatsheet_html(
        title="empty",
        manifest=[],
        shots={},
        thumbnails_present=set(),
    )
    assert "Editor Cheatsheet — empty" in rendered
    assert "0 chunks · 0 sentences" in rendered


def test_extract_missing_thumbnails_skips_existing_and_invokes_ffmpeg(tmp_path: Path) -> None:
    thumbnails_dir = tmp_path / "thumbs"
    thumbnails_dir.mkdir()
    # one thumbnail pre-existing — should be skipped
    (thumbnails_dir / _thumb_filename("visual:001")).write_bytes(b"\xff\xd8\xff")

    shots = {
        "visual:001": ShotInfo(
            seg_id="visual:001", start_s=0.0, end_s=2.0, summary="", ocr_text="", characters=[],
        ),
        "visual:002": ShotInfo(
            seg_id="visual:002", start_s=10.0, end_s=14.0, summary="", ocr_text="", characters=[],
        ),
    }

    calls: list[list[str]] = []

    def fake_run(cmd, *, check=True, capture_output=True, text=True):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        # Simulate ffmpeg writing the output file
        out_path = Path(cmd[cmd.index("-y") + 1])
        out_path.write_bytes(b"\xff\xd8\xff")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    extracted, skipped, errors = extract_missing_thumbnails(
        video=tmp_path / "video.mkv",
        shots=shots,
        thumbnails_dir=thumbnails_dir,
        workers=1,
        run_cmd=fake_run,
    )
    assert extracted == 1
    assert skipped == 1
    assert errors == []
    assert (thumbnails_dir / _thumb_filename("visual:002")).exists()
    # Only visual:002 should have triggered ffmpeg
    assert len(calls) == 1
    assert "-ss" in calls[0]
    # Mid-shot of (10.0, 14.0) is 12.0
    assert "12.000" in calls[0]


def test_extract_missing_thumbnails_requests_cuda_decode_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    thumbnails_dir = tmp_path / "thumbs"
    shots = {
        "visual:001": ShotInfo(
            seg_id="visual:001", start_s=10.0, end_s=14.0, summary="", ocr_text="", characters=[],
        ),
    }
    calls: list[list[str]] = []

    monkeypatch.setattr("app.pipeline.stage_4_build_cheatsheet.cuda_decode_available", lambda: True)

    def fake_run(cmd, *, check=True, capture_output=True, text=True):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        Path(cmd[-1]).write_bytes(b"\xff\xd8\xff")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    extracted, skipped, errors = extract_missing_thumbnails(
        video=tmp_path / "video.mkv",
        shots=shots,
        thumbnails_dir=thumbnails_dir,
        workers=1,
        run_cmd=fake_run,
    )

    assert extracted == 1
    assert skipped == 0
    assert errors == []
    assert calls == [[
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-hwaccel", "cuda",
        "-ss", "12.000",
        "-i", str(tmp_path / "video.mkv"),
        "-frames:v", "1",
        "-vf", "scale=320:-2",
        "-q:v", "5",
        "-y",
        str(thumbnails_dir / "visual_001.jpg"),
    ]]


def test_extract_missing_thumbnails_falls_back_to_cpu_when_cuda_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    thumbnails_dir = tmp_path / "thumbs"
    shots = {
        "visual:001": ShotInfo(
            seg_id="visual:001", start_s=10.0, end_s=14.0, summary="", ocr_text="", characters=[],
        ),
    }
    calls: list[list[str]] = []

    monkeypatch.setattr("app.pipeline.stage_4_build_cheatsheet.cuda_decode_available", lambda: True)

    def fake_run(cmd, *, check=True, capture_output=True, text=True):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        if "-hwaccel" in cmd:
            raise subprocess.CalledProcessError(1, cmd, stderr="CUDA decode failed")
        Path(cmd[-1]).write_bytes(b"\xff\xd8\xff")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    extracted, skipped, errors = extract_missing_thumbnails(
        video=tmp_path / "video.mkv",
        shots=shots,
        thumbnails_dir=thumbnails_dir,
        workers=1,
        run_cmd=fake_run,
    )

    assert extracted == 1
    assert skipped == 0
    assert errors == []
    assert len(calls) == 2
    assert "-hwaccel" in calls[0]
    assert "-hwaccel" not in calls[1]


def test_main_skips_thumbnails_when_flag_set(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_sample_manifest()), encoding="utf-8")
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(
        json.dumps(_sample_visual_segments(), ensure_ascii=False), encoding="utf-8"
    )
    video_path = tmp_path / "video.mkv"  # doesn't need to exist with --skip-thumbnails
    out_path = tmp_path / "out" / "cheatsheet.html"
    thumbnails_dir = tmp_path / "out" / "thumbs"

    rc = main(
        [
            "--manifest", str(manifest_path),
            "--visual-segments", str(visual_segments_path),
            "--video", str(video_path),
            "--thumbnails-dir", str(thumbnails_dir),
            "--out", str(out_path),
            "--title", "测试影片",
            "--skip-thumbnails",
        ],
        run_cmd=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("ffmpeg should not be called")),
    )
    assert rc == 0
    rendered = out_path.read_text(encoding="utf-8")
    assert "测试影片" in rendered
    # All thumbnails missing -> all show "no thumbnail" placeholder
    assert "no thumbnail" in rendered
