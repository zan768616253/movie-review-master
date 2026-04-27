from pathlib import Path

from app.pipeline.common.json_io import dump_json
from app.pipeline.stage3_generate_audio import parse_script_chunks, write_manifest
from app.pipeline.stage5_render_video import (
    main,
    plan_primary_window,
    plan_scene_extension,
    select_semantic_broll_segments,
)


def test_plan_primary_window_uses_handles_before_leftover() -> None:
    clip_metadata = {
        "requested_duration_s": 3.0,
        "pre_handle_s": 1.5,
        "extracted_duration_s": 6.0,
    }

    start_offset, clip_duration, leftover = plan_primary_window(clip_metadata, 5.0) # type: ignore

    assert start_offset == 0.5
    assert clip_duration == 5.0
    assert leftover == 0.0


def test_plan_primary_window_leaves_leftover_after_handles_are_spent() -> None:
    clip_metadata = {
        "requested_duration_s": 3.0,
        "pre_handle_s": 1.5,
        "extracted_duration_s": 5.0,
    }

    start_offset, clip_duration, leftover = plan_primary_window(clip_metadata, 6.0) # type: ignore

    assert start_offset == 0.0
    assert clip_duration == 5.0
    assert leftover == 1.0


def test_plan_scene_extension_starts_after_consumed_post_handle() -> None:
    entry = {"scene_end": "00:00:10.000"}
    clip_metadata = {
        "requested_duration_s": 5.0,
        "pre_handle_s": 1.0,
        "extracted_duration_s": 8.0,
    }

    start_s, duration = plan_scene_extension(entry, clip_metadata, video_duration_s=600.0, remaining=4.0, budget=6.0) # type: ignore

    assert start_s == 12.0
    assert duration == 4.0


def test_plan_scene_extension_caps_by_budget_and_video_headroom() -> None:
    entry = {"scene_end": "00:00:55.000"}

    start_s, duration = plan_scene_extension(entry, clip_metadata=None, video_duration_s=58.0, remaining=10.0, budget=6.0) # type: ignore

    assert start_s == 55.0
    assert duration == 3.0


def test_plan_scene_extension_returns_zero_for_closing_chunk() -> None:
    start_s, duration = plan_scene_extension(
        {"scene_end": None}, clip_metadata=None, video_duration_s=600.0, remaining=4.0, budget=6.0,
    )

    assert duration == 0.0


def test_select_semantic_broll_segments_prefers_matching_characters_and_avoids_scene_overlap() -> None:
    entry = {
        "text": "主角开始追杀敌人",
        "scene_characters": ["Hero"],
        "scene_start": "00:00:05.000",
        "scene_end": "00:00:08.000",
    }
    visual_segments = [
        {
            "id": "visual:001",
            "start": "00:00:05.000",
            "end": "00:00:08.000",
            "summary": "hero attacks villain",
            "ocr_text": "",
            "characters": ["Hero"],
        },
        {
            "id": "visual:002",
            "start": "00:00:10.000",
            "end": "00:00:13.000",
            "summary": "hero chases villain down the street",
            "ocr_text": "",
            "characters": ["Hero"],
        },
        {
            "id": "visual:003",
            "start": "00:00:14.000",
            "end": "00:00:18.000",
            "summary": "quiet room with teacher",
            "ocr_text": "",
            "characters": ["Teacher"],
        },
    ]

    selected = select_semantic_broll_segments(entry, visual_segments, used_segment_ids=set())

    assert [segment["id"] for segment in selected] == ["visual:002"]


def test_main_rejects_invalid_manifest_json(tmp_path: Path, capsys) -> None:
    manifest_path = tmp_path / "voiceover.manifest.json"
    manifest_path.write_text("{not valid json", encoding="utf-8")
    voiceover_path = tmp_path / "voiceover.mp3"
    voiceover_path.write_bytes(b"audio")

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--voiceover",
            str(voiceover_path),
            "--clips-dir",
            str(tmp_path / "clips"),
            "--keyframes-dir",
            str(tmp_path / "keyframes"),
            "--output",
            str(tmp_path / "review.mp4"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "Invalid manifest JSON" in captured.err


def test_main_rejects_manifest_entries_missing_required_fields(tmp_path: Path, capsys) -> None:
    manifest_path = tmp_path / "voiceover.manifest.json"
    dump_json(manifest_path, [{"index": 1}])
    voiceover_path = tmp_path / "voiceover.mp3"
    voiceover_path.write_bytes(b"audio")

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--voiceover",
            str(voiceover_path),
            "--clips-dir",
            str(tmp_path / "clips"),
            "--keyframes-dir",
            str(tmp_path / "keyframes"),
            "--output",
            str(tmp_path / "review.mp4"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "missing required fields audio_start_s, audio_end_s" in captured.err


def test_main_renders_from_stage3_manifest_contract(tmp_path: Path, monkeypatch) -> None:
    script_text = """
[TITLE] Demo
[SCENE start=00:00:01.000 end=00:00:03.000 source=srt]
第一段旁白
[CLOSING]
结尾
""".strip()
    manifest_path = tmp_path / "voiceover.manifest.json"
    chunks = parse_script_chunks(script_text)
    write_manifest(chunks, [(0.0, 2.0), (2.0, 3.0)], manifest_path)

    voiceover_path = tmp_path / "voiceover.mp3"
    voiceover_path.write_bytes(b"audio")

    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "clip_001.mp4").write_bytes(b"clip")

    keyframes_dir = tmp_path / "keyframes"
    keyframes_dir.mkdir()
    (keyframes_dir / "keyframe_001.jpg").write_bytes(b"still")

    clip_manifest_path = tmp_path / "clip_manifest.json"
    dump_json(
        clip_manifest_path,
        [
            {
                "index": 1,
                "requested_duration_s": 2.0,
                "pre_handle_s": 0.5,
                "extracted_duration_s": 3.0,
            }
        ],
    )

    output_path = tmp_path / "stage5" / "review.mp4"
    calls: list[tuple[object, ...]] = []

    def fake_render_excerpt(source_path: Path, start_s: float, target_duration: float, out_path: Path, codec: str) -> None:
        out_path.write_bytes(b"excerpt")
        calls.append(("excerpt", source_path.name, round(start_s, 3), round(target_duration, 3), codec))

    def fake_render_stillframe_segment(image_path: Path, target_duration: float, out_path: Path, codec: str) -> None:
        out_path.write_bytes(b"still")
        calls.append(("still", image_path.name, round(target_duration, 3), codec))

    def fake_concat_segments(segment_paths: list[Path], out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"concat")
        calls.append(("concat", tuple(path.name for path in segment_paths), out_path.name))

    def fake_mux_audio(video_path: Path, audio_path: Path, out_path: Path) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"final")
        calls.append(("mux", video_path.name, audio_path.name, out_path.name))

    monkeypatch.setattr("app.pipeline.stage5_render_video.resolve_encoder", lambda: "fake-codec")
    monkeypatch.setattr("app.pipeline.stage5_render_video.render_excerpt", fake_render_excerpt)
    monkeypatch.setattr("app.pipeline.stage5_render_video.render_stillframe_segment", fake_render_stillframe_segment)
    monkeypatch.setattr("app.pipeline.stage5_render_video.concat_segments", fake_concat_segments)
    monkeypatch.setattr("app.pipeline.stage5_render_video.mux_audio", fake_mux_audio)
    monkeypatch.setattr(
        "app.pipeline.stage5_render_video.probe_duration",
        lambda path: 3.0 if path.name == "review.mp4" else 2.0,
    )

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--voiceover",
            str(voiceover_path),
            "--clips-dir",
            str(clips_dir),
            "--keyframes-dir",
            str(keyframes_dir),
            "--clip-manifest",
            str(clip_manifest_path),
            "--output",
            str(output_path),
        ]
    )

    assert result == 0
    assert output_path.exists()
    assert ("excerpt", "clip_001.mp4", 0.5, 2.0, "fake-codec") in calls
    assert ("still", "keyframe_001.jpg", 1.0, "fake-codec") in calls
    assert any(call[0] == "mux" for call in calls)