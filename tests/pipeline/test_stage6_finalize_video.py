import json
from pathlib import Path

from app.pipeline.stage6_finalize_video import build_ffmpeg_command, main


def test_build_ffmpeg_command_maps_stage5_video_and_stage3_audio() -> None:
    command = build_ffmpeg_command(
        Path("/tmp/stage5/review.mp4"),
        Path("/tmp/stage3/voiceover.mp3"),
        Path("/tmp/stage6/final_video.mp4"),
    )

    assert command == [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        "/tmp/stage5/review.mp4",
        "-i",
        "/tmp/stage3/voiceover.mp3",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        "/tmp/stage6/final_video.mp4",
    ]


def test_main_rejects_missing_review_video(tmp_path: Path, capsys) -> None:
    voiceover = tmp_path / "voiceover.mp3"
    voiceover.write_bytes(b"audio")

    result = main([
        "--review-video",
        str(tmp_path / "missing-review.mp4"),
        "--voiceover",
        str(voiceover),
        "--output",
        str(tmp_path / "stage6" / "final_video.mp4"),
    ])

    captured = capsys.readouterr()
    assert result == 1
    assert "Review video not found:" in captured.err


def test_main_muxes_upload_video_and_writes_delivery_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    review_video = tmp_path / "stage5" / "review.mp4"
    review_video.parent.mkdir(parents=True, exist_ok=True)
    review_video.write_bytes(b"video")
    voiceover = tmp_path / "stage3" / "voiceover.mp3"
    voiceover.parent.mkdir(parents=True, exist_ok=True)
    voiceover.write_bytes(b"audio")
    output_path = tmp_path / "stage6" / "final_video.mp4"

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool) -> None:
        assert check is True
        calls.append(cmd)
        output_path.write_bytes(b"final")

    monkeypatch.setattr("app.pipeline.stage6_finalize_video.subprocess.run", fake_run)

    result = main([
        "--review-video",
        str(review_video),
        "--voiceover",
        str(voiceover),
        "--output",
        str(output_path),
    ])

    assert result == 0
    assert output_path.exists()
    assert calls == [[
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(review_video.resolve()),
        "-i",
        str(voiceover.resolve()),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path.resolve()),
    ]]

    manifest_path = output_path.parent / "delivery_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload == {
        "stage": 6,
        "video_source": str(review_video.resolve()),
        "audio_source": str(voiceover.resolve()),
        "output": str(output_path.resolve()),
        "video_codec": "copy",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "movflags": "+faststart",
    }