from pathlib import Path

from app.pipeline.common.json_io import dump_json
from app.pipeline.stage3_generate_audio import parse_script_chunks, write_manifest
from app.pipeline.stage5_render_video import (
    clamp_extension_against_black,
    collect_shot_boundaries_for_range,
    detect_black_intervals,
    main,
    plan_smart_trim,
    subtract_black_from_range,
    write_subtitle_script,
)


# --- plan_smart_trim ------------------------------------------------------


def test_plan_smart_trim_returns_exact_when_total_matches_audio() -> None:
    ranges = [(10.0, 20.0)]  # 10s of video
    kept, kind = plan_smart_trim(ranges, [[]], audio_duration_s=10.0)
    assert kept == ranges
    assert kind == "exact"


def test_plan_smart_trim_returns_extension_needed_when_video_too_short() -> None:
    ranges = [(10.0, 18.0)]  # 8s of video
    kept, kind = plan_smart_trim(ranges, [[]], audio_duration_s=12.0)
    assert kept == ranges  # unchanged; caller extends from post-handle or freezes tail
    assert kind == "extension-needed"


def test_plan_smart_trim_snaps_to_shot_boundary_within_grace() -> None:
    # 14s of video, 11s of audio → excess 3s.
    # Inner shot boundaries at 14.0, 17.0 (last range 10.0–24.0).
    # new_end = 24 - 3 = 21 → only candidate ≤ 21+grace is 17 → shot-aligned.
    ranges = [(10.0, 24.0)]
    shots = [[14.0, 17.0]]
    kept, kind = plan_smart_trim(ranges, shots, audio_duration_s=11.0)
    assert kept == [(10.0, 17.0)]
    assert kind == "shot-aligned-tail"


def test_plan_smart_trim_picks_latest_shot_boundary_to_preserve_payoff() -> None:
    # Last range 10–24s (14s); audio 6s → need new_end = 16 (exact target).
    # Boundaries at 12, 13, 16 are all candidates ≤ 16+grace; we want the
    # LATEST one (16) so we keep the most footage including the payoff.
    ranges = [(10.0, 24.0)]
    shots = [[12.0, 13.0, 16.0]]
    kept, kind = plan_smart_trim(ranges, shots, audio_duration_s=6.0)
    assert kept == [(10.0, 16.0)]
    assert kind == "shot-aligned-tail"


def test_plan_smart_trim_falls_back_to_mid_shot_when_no_boundary_fits() -> None:
    # 14s of video, 11s of audio → new_end target = 21. The only boundary
    # is at 10.5 (immediately after last_start). With audio_duration=11
    # and grace=0.55, candidates are { b : 10.0 < b ≤ 21.55 } = {10.5}.
    # That qualifies — but we want to test the "no-fit" branch, so place
    # the boundary AFTER new_end + grace.
    ranges = [(10.0, 24.0)]
    shots = [[23.0]]  # boundary at 23 > 21.55 → does not fit
    kept, kind = plan_smart_trim(ranges, shots, audio_duration_s=11.0)
    assert kept == [(10.0, 21.0)]  # mid-shot tail cut at exact target
    assert kind == "mid-shot-tail"


def test_plan_smart_trim_spreads_excess_across_multiple_ranges() -> None:
    # Two ranges: [10–14] (4s) and [20–22] (2s); audio 4s; excess 2s.
    # The planner picked these two ranges to anchor distinct beats — the
    # narration tells viewers about both. So we trim each range
    # proportionally rather than dropping the second one entirely. Each
    # range loses excess × (range_budget / total_budget).
    ranges = [(10.0, 14.0), (20.0, 22.0)]
    shots = [[], []]
    kept, kind = plan_smart_trim(ranges, shots, audio_duration_s=4.0)
    assert kept[0] == (10.0, 14.0 - 2.0 * (2.5 / 3.0))
    assert kept[1] == (20.0, 22.0 - 2.0 * (0.5 / 3.0))
    # Both ranges still represented.
    assert len(kept) == 2
    assert kind == "mid-shot-spread"


def test_plan_smart_trim_snaps_each_range_to_its_own_shot_boundary() -> None:
    # Two ranges; both have shot boundaries available within their cut
    # windows. The proportional cut snaps each range independently.
    ranges = [(10.0, 20.0), (30.0, 40.0)]  # 10s + 10s = 20s
    # Shot boundaries inside each range. Audio = 16s → excess = 4s,
    # 2s should come from each range. Cut in r0: target end = 18.0
    # (boundary at 17 is the latest ≤ 18.8 → snap there). r1: target
    # end = 38.0 (boundary at 38 fits, snap there).
    shots = [[15.0, 17.0], [35.0, 38.0]]
    kept, kind = plan_smart_trim(ranges, shots, audio_duration_s=16.0)
    assert kept == [(10.0, 17.0), (30.0, 38.0)]
    assert kind == "shot-aligned-spread"


def test_plan_smart_trim_drops_last_range_only_when_spread_cannot_absorb() -> None:
    # Three short ranges: [10–12] [20–22] [30–32], total 6s, audio 1s.
    # Excess = 5s. Per-range budget = 0.5s × 3 = 1.5s, far less than 5s.
    # Spread is impossible; fall back to dropping the last range and
    # recursing. After dropping one, total=4s, still > audio + budget;
    # drop another. After two drops, total=2s, budget=0.5s, still > 1s
    # → drops to single range, then single-range path trims to 1s.
    ranges = [(10.0, 12.0), (20.0, 22.0), (30.0, 32.0)]
    shots = [[], [], []]
    kept, kind = plan_smart_trim(ranges, shots, audio_duration_s=1.0)
    assert kept == [(10.0, 11.0)]
    assert kind == "mid-shot-tail"


# --- detect_black_intervals -----------------------------------------------


def test_detect_black_intervals_parses_ffmpeg_blackdetect_output(
    tmp_path: Path, monkeypatch
) -> None:
    fake_stderr = (
        "ffmpeg version ... blah\n"
        "[blackdetect @ 0x1234] black_start:5.0 black_end:11.0 black_duration:6.0\n"
        "[blackdetect @ 0x1234] black_start:25.5 black_end:27.0 black_duration:1.5\n"
        "frame=  100 fps=30\n"
    )

    class FakeProc:
        stderr = fake_stderr

    def fake_run(cmd, capture_output, text):
        # Sanity: must invoke the blackdetect filter.
        assert "-vf" in cmd
        vf_idx = cmd.index("-vf")
        assert "blackdetect=" in cmd[vf_idx + 1]
        return FakeProc()

    monkeypatch.setattr(
        "app.pipeline.stage5_render_video.subprocess.run", fake_run
    )

    intervals = detect_black_intervals(tmp_path / "fake.mp4")
    assert intervals == [(5.0, 11.0), (25.5, 27.0)]


def test_detect_black_intervals_returns_empty_when_no_match(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeProc:
        stderr = "ffmpeg version 5.0\nframe= 100\n"

    monkeypatch.setattr(
        "app.pipeline.stage5_render_video.subprocess.run",
        lambda *a, **kw: FakeProc(),
    )

    assert detect_black_intervals(tmp_path / "fake.mp4") == []


# --- subtract_black_from_range --------------------------------------------


def test_subtract_black_from_range_passes_through_when_no_black() -> None:
    assert subtract_black_from_range(10.0, 20.0, 8.0, []) == [(10.0, 20.0)]


def test_subtract_black_from_range_splits_around_mid_range_black() -> None:
    # Range 10-20s in absolute; clip extracted starting at 8.0s; black at
    # clip-relative 4-12 → absolute 12-20. The range covers 10-20, so
    # black overlap is 12-20. After clip: [10-12] (2s, kept).
    out = subtract_black_from_range(
        range_start_abs=10.0,
        range_end_abs=20.0,
        extracted_start_abs=8.0,
        clip_blacks_rel=[(4.0, 12.0)],
    )
    assert out == [(10.0, 12.0)]


def test_subtract_black_from_range_keeps_two_sub_ranges_when_black_in_middle() -> None:
    # Mirror the chunk-26 case: range straddles a fade-to-black baked
    # into the source. We want to keep both real-footage halves.
    out = subtract_black_from_range(
        range_start_abs=100.0,
        range_end_abs=120.0,
        extracted_start_abs=98.0,
        clip_blacks_rel=[(8.0, 14.0)],  # absolute 106-112
    )
    assert out == [(100.0, 106.0), (112.0, 120.0)]


def test_subtract_black_from_range_drops_short_fragments() -> None:
    # Range 10-13.4 with black at 11.0-12.0 → fragments [10-11] (1.0s)
    # and [12-13.4] (1.4s); both below the 1.5s default min_keep, so
    # nothing survives. Caller should drop the range entirely.
    out = subtract_black_from_range(
        range_start_abs=10.0,
        range_end_abs=13.4,
        extracted_start_abs=10.0,
        clip_blacks_rel=[(1.0, 2.0)],
    )
    assert out == []


# --- clamp_extension_against_black ----------------------------------------


def test_clamp_extension_against_black_no_change_when_no_black() -> None:
    assert clamp_extension_against_black(
        range_end_abs=100.0,
        extended_end_abs=103.0,
        extracted_start_abs=98.0,
        clip_blacks_rel=[],
    ) == 103.0


def test_clamp_extension_stops_at_first_black_in_post_handle() -> None:
    # Mirror chunk-22 case: requested range ends at 100; extension wants
    # to push to 103 to fill audio shortfall; but the source has black
    # starting at clip-relative 4.0 (absolute 102.0). Clamp to 102.
    clamped = clamp_extension_against_black(
        range_end_abs=100.0,
        extended_end_abs=103.0,
        extracted_start_abs=98.0,
        clip_blacks_rel=[(4.0, 6.5)],  # absolute 102-104.5
    )
    assert clamped == 102.0


def test_clamp_extension_ignores_black_outside_extension_window() -> None:
    # Black is before the requested range; extension is clean.
    clamped = clamp_extension_against_black(
        range_end_abs=100.0,
        extended_end_abs=103.0,
        extracted_start_abs=95.0,
        clip_blacks_rel=[(0.0, 2.0)],  # absolute 95-97, well before range_end
    )
    assert clamped == 103.0


# --- collect_shot_boundaries_for_range ------------------------------------


def test_collect_shot_boundaries_unions_overlapping_segments() -> None:
    visual_segments = [
        {
            "start": "00:00:08.000", "end": "00:00:16.000",
            "shot_boundaries_s": [12.0],
        },
        {
            "start": "00:00:14.000", "end": "00:00:22.000",
            "shot_boundaries_s": [14.0, 18.0, 22.0],
        },
        {
            # Outside the requested range — should be ignored.
            "start": "00:01:00.000", "end": "00:01:10.000",
            "shot_boundaries_s": [65.0],
        },
    ]
    boundaries = collect_shot_boundaries_for_range(10.0, 20.0, visual_segments)
    # Strictly inside (10, 20) → 12.0, 14.0, 18.0; 22 and 65 are outside.
    assert boundaries == [12.0, 14.0, 18.0]


def test_write_subtitle_script_creates_styled_bottom_center_dialogue(tmp_path: Path) -> None:
    subtitle_path = tmp_path / "review_subtitles.ass"

    wrote_file = write_subtitle_script([
        {
            "index": 1,
            "text": "First line\nSecond line",
            "audio_start_s": 0.0,
            "audio_end_s": 2.34,
        },
        {
            "index": 2,
            "text": "   ",
            "audio_start_s": 2.34,
            "audio_end_s": 3.0,
        },
    ], subtitle_path)

    assert wrote_file is True
    payload = subtitle_path.read_text(encoding="utf-8")
    assert "Style: ReviewCaption" in payload
    assert ",2,140,140,64,1" in payload
    assert "Dialogue: 0,0:00:00.00,0:00:02.34,ReviewCaption,,0,0,0,,First line Second line" in payload


# --- main: end-to-end with new manifest schemas ---------------------------


def _build_minimal_anchored_run(tmp_path: Path) -> dict[str, Path]:
    """Set up a tmp directory with all files an end-to-end main() needs."""
    script_text = (
        "[TITLE] Demo\n"
        "[HOOK]\n"
        '[ANCHOR ranges="00:00:01.000-00:00:03.000" characters="Hero"]\n'
        "narration A\n"
        "[CLOSING]\n"
        "closing line\n"
    )
    manifest_path = tmp_path / "voiceover.manifest.json"
    chunks = parse_script_chunks(script_text)
    write_manifest(chunks, [(0.0, 2.0), (2.0, 3.0)], manifest_path)

    voiceover_path = tmp_path / "voiceover.mp3"
    voiceover_path.write_bytes(b"audio")

    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "clip_001_a.mp4").write_bytes(b"clip")

    keyframes_dir = tmp_path / "keyframes"
    keyframes_dir.mkdir()
    (keyframes_dir / "keyframe_001.jpg").write_bytes(b"still")

    clip_manifest_path = tmp_path / "clip_manifest.json"
    dump_json(clip_manifest_path, [
        {
            "index": 1,
            "characters": ["Hero"],
            "keyframe_path": "keyframe_001.jpg",
            "ranges": [
                {
                    "clip_path": "clip_001_a.mp4",
                    "range_start": "00:00:01.000",
                    "range_end": "00:00:03.000",
                    "extracted_start": "00:00:00.000",
                    "extracted_end": "00:00:05.000",
                    "requested_duration_s": 2.0,
                    "extracted_duration_s": 5.0,
                    "pre_handle_s": 1.0,
                    "post_handle_s": 2.0,
                },
            ],
        },
    ])

    return {
        "manifest": manifest_path,
        "voiceover": voiceover_path,
        "clips_dir": clips_dir,
        "keyframes_dir": keyframes_dir,
        "clip_manifest": clip_manifest_path,
    }


def test_main_rejects_invalid_manifest_json(tmp_path: Path, capsys) -> None:
    manifest_path = tmp_path / "voiceover.manifest.json"
    manifest_path.write_text("{not valid json", encoding="utf-8")
    voiceover_path = tmp_path / "voiceover.mp3"
    voiceover_path.write_bytes(b"audio")

    result = main([
        "--manifest", str(manifest_path),
        "--voiceover", str(voiceover_path),
        "--clips-dir", str(tmp_path / "clips"),
        "--keyframes-dir", str(tmp_path / "keyframes"),
        "--output", str(tmp_path / "review.mp4"),
    ])
    captured = capsys.readouterr()
    assert result == 1
    assert "Invalid manifest JSON" in captured.err


def test_main_rejects_manifest_entries_missing_required_fields(tmp_path: Path, capsys) -> None:
    manifest_path = tmp_path / "voiceover.manifest.json"
    dump_json(manifest_path, [{"index": 1}])
    voiceover_path = tmp_path / "voiceover.mp3"
    voiceover_path.write_bytes(b"audio")

    result = main([
        "--manifest", str(manifest_path),
        "--voiceover", str(voiceover_path),
        "--clips-dir", str(tmp_path / "clips"),
        "--keyframes-dir", str(tmp_path / "keyframes"),
        "--output", str(tmp_path / "review.mp4"),
    ])
    captured = capsys.readouterr()
    assert result == 1
    assert "missing required fields audio_start_s, audio_end_s" in captured.err


def test_main_renders_anchored_chunk_and_closing_keyframe(tmp_path: Path, monkeypatch) -> None:
    files = _build_minimal_anchored_run(tmp_path)
    output_path = tmp_path / "stage5" / "review.mp4"
    calls: list[tuple[object, ...]] = []

    def fake_render_excerpt(source_path, start_s, target_duration, out_path, codec):
        out_path.write_bytes(b"excerpt")
        calls.append(("excerpt", source_path.name, round(start_s, 3), round(target_duration, 3)))

    def fake_render_stillframe_segment(image_path, target_duration, out_path, codec):
        out_path.write_bytes(b"still")
        calls.append(("still", image_path.name, round(target_duration, 3)))

    def fake_concat_segments(segment_paths, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"concat")
        calls.append(("concat", tuple(p.name for p in segment_paths), out_path.name))

    def fake_split_voiceover_to_segment(voiceover_path, audio_start_s, audio_end_s, out_path):
        out_path.write_bytes(b"chunk-mp3")
        calls.append(("split", voiceover_path.name, round(audio_end_s - audio_start_s, 3)))

    def fake_mux_audio(video_path, audio_path, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"final")
        calls.append(("mux", video_path.name, audio_path.name, out_path.name))

    def fake_write_subtitle_script(manifest, out_path):
        out_path.write_text("ass", encoding="utf-8")
        calls.append(("subtitle-script", len(manifest), out_path.name))
        return True

    def fake_burn_subtitles(video_path, subtitle_path, out_path, codec):
        out_path.write_bytes(b"subtitled")
        calls.append(("burn", video_path.name, subtitle_path.name, out_path.name, codec))

    monkeypatch.setattr("app.pipeline.stage5_render_video.resolve_encoder", lambda: "fake-codec")
    monkeypatch.setattr("app.pipeline.stage5_render_video.render_excerpt", fake_render_excerpt)
    monkeypatch.setattr("app.pipeline.stage5_render_video.render_stillframe_segment", fake_render_stillframe_segment)
    monkeypatch.setattr("app.pipeline.stage5_render_video.concat_segments", fake_concat_segments)
    monkeypatch.setattr("app.pipeline.stage5_render_video.split_voiceover_to_segment", fake_split_voiceover_to_segment)
    monkeypatch.setattr("app.pipeline.stage5_render_video.write_subtitle_script", fake_write_subtitle_script)
    monkeypatch.setattr("app.pipeline.stage5_render_video.burn_subtitles", fake_burn_subtitles)
    monkeypatch.setattr("app.pipeline.stage5_render_video.mux_audio", fake_mux_audio)
    monkeypatch.setattr(
        "app.pipeline.stage5_render_video.detect_black_intervals",
        lambda *a, **kw: [],
    )

    result = main([
        "--manifest", str(files["manifest"]),
        "--voiceover", str(files["voiceover"]),
        "--clips-dir", str(files["clips_dir"]),
        "--keyframes-dir", str(files["keyframes_dir"]),
        "--clip-manifest", str(files["clip_manifest"]),
        "--output", str(output_path),
    ])

    assert result == 0
    assert output_path.exists()

    # The anchored chunk's hero clip is rendered from clip_001_a.mp4 with
    # offset = pre_handle = 1.0s, target = audio_duration = 2.0s.
    assert ("excerpt", "clip_001_a.mp4", 1.0, 2.0) in calls

    # The closing chunk falls through to a still over the keyframe.
    assert ("still", "keyframe_001.jpg", 1.0) in calls

    # Both chunks get a per-chunk MP3 split for the editor handoff.
    split_calls = [c for c in calls if c[0] == "split"]
    assert len(split_calls) == 2

    # Final mux happens once.
    assert ("subtitle-script", 2, "review_subtitles.ass") in calls
    assert ("burn", "review.silent.mp4", "review_subtitles.ass", "review.subtitled.mp4", "fake-codec") in calls
    assert ("mux", "review.subtitled.mp4", "voiceover.mp3", "review.mp4") in calls

    # Edit manifest is written.
    edit_manifest_path = output_path.parent / "edit_manifest.json"
    assert edit_manifest_path.exists()
    import json
    payload = json.loads(edit_manifest_path.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert payload[0]["index"] == 1
    assert payload[0]["segment_video"] == "segment_001.mp4"
    assert payload[0]["segment_audio"] == "segment_001.mp3"


def test_main_extends_anchor_chunk_from_post_handle_when_audio_runs_long(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manifest_path = tmp_path / "voiceover.manifest.json"
    dump_json(manifest_path, [
        {
            "index": 1,
            "ranges": [["00:00:01.000", "00:00:03.000"]],
            "characters": ["Hero"],
            "text": "narration A",
            "audio_start_s": 0.0,
            "audio_end_s": 4.0,
        },
    ])

    voiceover_path = tmp_path / "voiceover.mp3"
    voiceover_path.write_bytes(b"audio")

    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "clip_001_a.mp4").write_bytes(b"clip")

    keyframes_dir = tmp_path / "keyframes"
    keyframes_dir.mkdir()
    (keyframes_dir / "keyframe_001.jpg").write_bytes(b"still")

    clip_manifest_path = tmp_path / "clip_manifest.json"
    dump_json(clip_manifest_path, [
        {
            "index": 1,
            "characters": ["Hero"],
            "keyframe_path": "keyframe_001.jpg",
            "ranges": [
                {
                    "clip_path": "clip_001_a.mp4",
                    "range_start": "00:00:01.000",
                    "range_end": "00:00:03.000",
                    "extracted_start": "00:00:00.000",
                    "extracted_end": "00:00:05.000",
                    "requested_duration_s": 2.0,
                    "extracted_duration_s": 5.0,
                    "pre_handle_s": 1.0,
                    "post_handle_s": 2.0,
                },
            ],
        },
    ])

    output_path = tmp_path / "stage5" / "review.mp4"
    calls: list[tuple[object, ...]] = []

    def fake_render_excerpt(source_path, start_s, target_duration, out_path, codec):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"excerpt")
        calls.append(("excerpt", source_path.name, round(start_s, 3), round(target_duration, 3)))

    def fake_render_stillframe_segment(image_path, target_duration, out_path, codec):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"still")
        calls.append(("still", image_path.name, round(target_duration, 3), out_path.name))

    def fake_concat_segments(segment_paths, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"concat")
        calls.append(("concat", tuple(p.name for p in segment_paths), out_path.name))

    def fake_split_voiceover_to_segment(voiceover_path, audio_start_s, audio_end_s, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"chunk-mp3")

    def fake_mux_audio(video_path, audio_path, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"final")

    def fake_write_subtitle_script(manifest, out_path):
        out_path.write_text("ass", encoding="utf-8")
        return True

    def fake_burn_subtitles(video_path, subtitle_path, out_path, codec):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"subtitled")

    monkeypatch.setattr("app.pipeline.stage5_render_video.resolve_encoder", lambda: "fake-codec")
    monkeypatch.setattr("app.pipeline.stage5_render_video.render_excerpt", fake_render_excerpt)
    monkeypatch.setattr("app.pipeline.stage5_render_video.render_stillframe_segment", fake_render_stillframe_segment)
    monkeypatch.setattr("app.pipeline.stage5_render_video.concat_segments", fake_concat_segments)
    monkeypatch.setattr("app.pipeline.stage5_render_video.split_voiceover_to_segment", fake_split_voiceover_to_segment)
    monkeypatch.setattr("app.pipeline.stage5_render_video.write_subtitle_script", fake_write_subtitle_script)
    monkeypatch.setattr("app.pipeline.stage5_render_video.burn_subtitles", fake_burn_subtitles)
    monkeypatch.setattr("app.pipeline.stage5_render_video.mux_audio", fake_mux_audio)
    monkeypatch.setattr(
        "app.pipeline.stage5_render_video.detect_black_intervals",
        lambda *a, **kw: [],
    )

    result = main([
        "--manifest", str(manifest_path),
        "--voiceover", str(voiceover_path),
        "--clips-dir", str(clips_dir),
        "--keyframes-dir", str(keyframes_dir),
        "--clip-manifest", str(clip_manifest_path),
        "--output", str(output_path),
    ])

    assert result == 0
    assert ("excerpt", "clip_001_a.mp4", 1.0, 4.0) in calls
    assert not [c for c in calls if c[0] == "still" and c[2] == 4.0]
