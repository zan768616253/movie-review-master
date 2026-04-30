import json
from pathlib import Path

from app.pipeline.common.script_contract import AnchorMarker
from app.pipeline.stage5_video_processor import (
    PRE_HANDLE_SECONDS,
    POST_HANDLE_SECONDS,
    _suffix_for,
    plan_anchor_clips,
    write_clip_manifest,
)


def test_suffix_for_lowercase_letters() -> None:
    assert _suffix_for(0) == "a"
    assert _suffix_for(1) == "b"
    assert _suffix_for(25) == "z"
    # 26+ ranges in one anchor would be absurd, but support it cleanly.
    assert _suffix_for(26) == "aa"


def test_plan_anchor_clips_single_range_uses_asymmetric_handles() -> None:
    anchor = AnchorMarker(
        ranges=[("00:00:10.000", "00:00:18.000")],
        characters=["Yuta"],
    )

    plan = plan_anchor_clips(index=7, anchor=anchor, video_duration_s=600.0)

    assert plan.index == 7
    assert plan.characters == ["Yuta"]
    assert len(plan.range_plans) == 1
    rp = plan.range_plans[0]
    assert rp.suffix == "a"
    assert rp.clip_path == "clip_007_a.mp4"
    assert rp.range_start == "00:00:10.000"
    assert rp.range_end == "00:00:18.000"
    # Asymmetric: pre=2s, post=4s.
    assert rp.pre_handle_s == PRE_HANDLE_SECONDS
    assert rp.post_handle_s == POST_HANDLE_SECONDS
    assert rp.extracted_start == "00:00:08.000"  # 10 - 2 = 8
    assert rp.extracted_end == "00:00:22.000"    # 18 + 4 = 22
    assert rp.requested_duration_s == 8.0
    assert rp.extracted_duration_s == 14.0       # 22 - 8


def test_plan_anchor_clips_multi_range_produces_lettered_clip_files() -> None:
    anchor = AnchorMarker(
        ranges=[
            ("00:01:00.000", "00:01:05.000"),
            ("00:02:00.000", "00:02:10.000"),
            ("00:03:00.000", "00:03:15.000"),
        ],
        characters=[],
    )

    plan = plan_anchor_clips(index=12, anchor=anchor, video_duration_s=600.0)

    assert [rp.clip_path for rp in plan.range_plans] == [
        "clip_012_a.mp4",
        "clip_012_b.mp4",
        "clip_012_c.mp4",
    ]
    # Each range gets its own handles independently.
    assert plan.range_plans[1].extracted_start == "00:01:58.000"  # 120 - 2
    assert plan.range_plans[1].extracted_end == "00:02:14.000"    # 130 + 4


def test_plan_anchor_clips_clamps_handles_to_video_bounds() -> None:
    # Range right at the start of the movie — pre-handle would go negative.
    anchor = AnchorMarker(
        ranges=[("00:00:01.000", "00:00:05.000")],
        characters=[],
    )

    plan = plan_anchor_clips(index=1, anchor=anchor, video_duration_s=600.0)

    rp = plan.range_plans[0]
    assert rp.extracted_start == "00:00:00.000"  # clamped to 0
    assert rp.pre_handle_s == 1.0  # 1 - 0 (only 1s of pre-handle available)


def test_plan_anchor_clips_clamps_handles_to_video_eof() -> None:
    # Range near the end of the movie — post-handle would exceed EOF.
    anchor = AnchorMarker(
        ranges=[("00:09:55.000", "00:09:58.000")],
        characters=[],
    )

    plan = plan_anchor_clips(index=1, anchor=anchor, video_duration_s=600.0)  # 10 min

    rp = plan.range_plans[0]
    assert rp.extracted_end == "00:10:00.000"  # clamped to 600
    assert rp.post_handle_s == 2.0  # 600 - 598 (only 2s of post-handle available)


def test_plan_anchor_clips_keyframe_one_second_into_first_range() -> None:
    anchor = AnchorMarker(
        ranges=[("00:00:10.000", "00:00:18.000")],
        characters=[],
    )

    plan = plan_anchor_clips(index=3, anchor=anchor, video_duration_s=600.0)

    # First range start = 10s, mid = 14s, min(1, 8/2)=1 → keyframe at 11s
    assert plan.keyframe_time == "00:00:11.000"
    assert plan.keyframe_path == "keyframe_003.jpg"


def test_write_clip_manifest_emits_nested_ranges_per_anchor(tmp_path: Path) -> None:
    anchor = AnchorMarker(
        ranges=[("00:00:10.000", "00:00:14.000"), ("00:00:20.000", "00:00:24.000")],
        characters=["Hero"],
    )
    plan = plan_anchor_clips(index=1, anchor=anchor, video_duration_s=600.0)

    out_path = write_clip_manifest(tmp_path, [plan])

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload) == 1
    entry = payload[0]
    assert entry["index"] == 1
    assert entry["characters"] == ["Hero"]
    assert entry["keyframe_path"] == "keyframe_001.jpg"
    assert len(entry["ranges"]) == 2
    first = entry["ranges"][0]
    assert first["clip_path"] == "clip_001_a.mp4"
    assert first["range_start"] == "00:00:10.000"
    assert first["pre_handle_s"] == PRE_HANDLE_SECONDS
    assert first["post_handle_s"] == POST_HANDLE_SECONDS
