from app.pipeline.stage5_render_video import plan_primary_window, select_semantic_broll_segments


def test_plan_primary_window_uses_handles_before_leftover() -> None:
    clip_metadata = {
        "requested_duration_s": 3.0,
        "pre_handle_s": 1.5,
        "extracted_duration_s": 6.0,
    }

    start_offset, clip_duration, leftover = plan_primary_window(clip_metadata, 5.0)

    assert start_offset == 0.5
    assert clip_duration == 5.0
    assert leftover == 0.0


def test_plan_primary_window_leaves_leftover_after_handles_are_spent() -> None:
    clip_metadata = {
        "requested_duration_s": 3.0,
        "pre_handle_s": 1.5,
        "extracted_duration_s": 5.0,
    }

    start_offset, clip_duration, leftover = plan_primary_window(clip_metadata, 6.0)

    assert start_offset == 0.0
    assert clip_duration == 5.0
    assert leftover == 1.0


def test_select_semantic_broll_segments_prefers_matching_characters_and_avoids_scene_overlap() -> None:
    entry = {
        "text": "主角开始追杀敌人",
        "scene_characters": ["Hero"],
        "scene_evidence": "visual:001",
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