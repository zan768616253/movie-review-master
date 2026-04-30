"""Tests for the anchored-script contract introduced in the Stage 2 overhaul."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.common.script_contract import (
    MAX_ANCHOR_RANGE_DURATION_S,
    MAX_ANCHOR_TOTAL_DURATION_S,
    AnchorMarker,
    build_shot_boundary_set,
    build_timeline_intervals,
    parse_anchor_marker,
    parse_range_list,
    read_style_chars_per_second,
    validate_anchored_script,
)


def test_parse_range_list_handles_single_range() -> None:
    ranges = parse_range_list("00:01:00.000-00:01:05.000")
    assert ranges == [("00:01:00.000", "00:01:05.000")]


def test_parse_range_list_handles_multiple_comma_separated() -> None:
    ranges = parse_range_list("00:01:00-00:01:05, 00:02:00-00:02:10, 00:03:00-00:03:15")
    assert ranges == [
        ("00:01:00", "00:01:05"),
        ("00:02:00", "00:02:10"),
        ("00:03:00", "00:03:15"),
    ]


def test_parse_anchor_marker_single_range() -> None:
    marker = parse_anchor_marker(
        '[ANCHOR ranges="00:23:10.000-00:23:18.000" characters="Yuta|Rika"]'
    )
    assert marker is not None
    assert marker.ranges == [("00:23:10.000", "00:23:18.000")]
    assert marker.characters == ["Yuta", "Rika"]
    assert marker.total_seconds == pytest.approx(8.0)


def test_parse_anchor_marker_multi_range_chronological() -> None:
    marker = parse_anchor_marker(
        '[ANCHOR ranges="00:01:00-00:01:05, 00:02:00-00:02:10"]'
    )
    assert marker is not None
    assert marker.ranges == [("00:01:00", "00:01:05"), ("00:02:00", "00:02:10")]
    assert marker.characters == []
    assert marker.total_seconds == pytest.approx(15.0)


def test_parse_anchor_marker_returns_none_for_non_anchor_lines() -> None:
    assert parse_anchor_marker("[SCENE start=00:01:00 end=00:01:05]") is None
    assert parse_anchor_marker("plain narration text") is None
    assert parse_anchor_marker("[TITLE]") is None


def test_parse_anchor_marker_raises_when_ranges_missing() -> None:
    with pytest.raises(ValueError, match="missing required `ranges="):
        parse_anchor_marker('[ANCHOR characters="Yuta"]')


def test_parse_anchor_marker_raises_on_zero_duration_range() -> None:
    with pytest.raises(ValueError, match="non-positive duration"):
        parse_anchor_marker('[ANCHOR ranges="00:01:00-00:01:00"]')


def test_parse_anchor_marker_raises_on_inverted_range() -> None:
    with pytest.raises(ValueError, match="non-positive duration"):
        parse_anchor_marker('[ANCHOR ranges="00:01:10-00:01:05"]')


def test_parse_anchor_marker_auto_sorts_out_of_order_ranges() -> None:
    # The planner sometimes emits ranges in semantic order (e.g. "the
    # death shot, then the haunting shot") rather than source-time order.
    # The parser normalizes to source-time so playback is always forward.
    marker = parse_anchor_marker(
        '[ANCHOR ranges="00:02:00-00:02:10, 00:01:00-00:01:05"]'
    )
    assert marker is not None
    assert marker.ranges == [("00:01:00", "00:01:05"), ("00:02:00", "00:02:10")]


def test_parse_anchor_marker_raises_on_overlapping_ranges() -> None:
    with pytest.raises(ValueError, match="overlap"):
        parse_anchor_marker(
            '[ANCHOR ranges="00:01:00-00:01:10, 00:01:05-00:01:15"]'
        )


def test_parse_anchor_marker_detects_overlap_after_sorting() -> None:
    # Even when the overlapping pair is given out-of-order, the post-sort
    # overlap check still catches it.
    with pytest.raises(ValueError, match="overlap"):
        parse_anchor_marker(
            '[ANCHOR ranges="00:01:05-00:01:15, 00:01:00-00:01:10"]'
        )


def test_parse_anchor_marker_accepts_back_to_back_ranges() -> None:
    # end of range 1 == start of range 2 is allowed (no replay, just a join).
    marker = parse_anchor_marker(
        '[ANCHOR ranges="00:01:00-00:01:10, 00:01:10-00:01:20"]'
    )
    assert marker is not None
    assert marker.total_seconds == pytest.approx(20.0)


# --- read_style_chars_per_second ------------------------------------------


def test_read_style_chars_per_second_extracts_from_markdown(tmp_path: Path) -> None:
    style = tmp_path / "demo.md"
    style.write_text(
        "# Demo style\n"
        "**TTS Budget:** `chars_per_second = 5.5`. Notes follow.\n",
        encoding="utf-8",
    )
    assert read_style_chars_per_second(style) == 5.5


def test_read_style_chars_per_second_uses_default_when_missing(tmp_path: Path) -> None:
    style = tmp_path / "minimal.md"
    style.write_text("# No TTS line here", encoding="utf-8")
    assert read_style_chars_per_second(style, default=4.7) == 4.7


def test_read_style_chars_per_second_reads_real_niu_shu_file() -> None:
    # Smoke test against the actual project file — guards against edits
    # that would silently strip the planner-authority line.
    style = Path(__file__).resolve().parents[2] / "styles" / "niu-shu.md"
    cps = read_style_chars_per_second(style)
    assert 4.0 <= cps <= 8.0  # sanity range for a Chinese narration style


# --- validate_anchored_script ---------------------------------------------


def _build_script(*chunks: tuple[str, str]) -> str:
    """Helper: glue an anchored script from (anchor_line, narration) pairs.

    Adds the [TITLE]/[HOOK] preamble that the validator looks for to enter
    "in script" mode, mirroring the schema the planner-writer produces.
    """
    lines = ["[TITLE] Demo", "[HOOK]"]
    for anchor_line, narration in chunks:
        lines.append(anchor_line)
        lines.append(narration)
    return "\n".join(lines) + "\n"


def test_validate_anchored_script_marks_in_budget_chunk_ok() -> None:
    # 10s anchor × 5.0 cps = 50-char budget. 30 chars of narration → ratio 0.6 → ok.
    script = _build_script(
        ('[ANCHOR ranges="00:00:10-00:00:20"]', "三十个汉字组成的标准旁白这条线索是用来测试预算" + "x" * (30 - 23)),
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk.severity == "ok"
    assert chunk.budget_chars == 50
    assert chunk.overrun_ratio < 1.0


def test_validate_anchored_script_marks_small_overrun_warn() -> None:
    # 10s × 5.0 = 50-char budget. 54 chars → 1.08× → warn (≤10% slack).
    script = _build_script(
        ('[ANCHOR ranges="00:00:10-00:00:20"]', "x" * 54),
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert result.chunks[0].severity == "warn"
    assert result.has_warnings is True
    assert result.has_failures is False


def test_validate_anchored_script_marks_large_overrun_fail() -> None:
    # 10s × 5.0 = 50-char budget. 70 chars → 1.4× → fail (>10% over).
    script = _build_script(
        ('[ANCHOR ranges="00:00:10-00:00:20"]', "x" * 70),
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert result.chunks[0].severity == "fail"
    assert result.has_failures is True
    assert result.failures()[0].narration_chars == 70


def test_validate_anchored_script_handles_multi_range_anchor_budget() -> None:
    # 4s + 6s = 10s × 5.0 = 50-char budget.
    script = _build_script(
        ('[ANCHOR ranges="00:00:00-00:00:04, 00:00:10-00:00:16"]', "x" * 50),
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert result.chunks[0].budget_chars == 50
    assert result.chunks[0].severity == "ok"


def test_validate_anchored_script_skips_closing_chunk() -> None:
    script = (
        "[TITLE] Demo\n"
        "[HOOK]\n"
        '[ANCHOR ranges="00:00:00-00:00:10"]\n'
        + "x" * 40 + "\n"
        + "[CLOSING]\n"
        + "x" * 200 + "\n"  # closing narration — not budget-checked
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert len(result.chunks) == 1  # only the one anchor; closing skipped
    assert result.chunks[0].severity == "ok"
    assert not result.has_failures


# --- Structure checks (added in fix-up turn) ------------------------------


def test_validator_flags_missing_title() -> None:
    script = '[ANCHOR ranges="00:00:00-00:00:10"]\nfoo\n'
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert any(i.code == "no_title" for i in result.issues)
    assert result.has_failures


def test_validator_flags_no_anchors() -> None:
    script = "[TITLE] Demo\n[HOOK]\nplain narration with no anchor\n[CLOSING]\nbye\n"
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert any(i.code == "no_anchors" for i in result.issues)
    # The "plain narration" line is also flagged as orphan_narration.
    assert any(i.code == "orphan_narration" for i in result.issues)


def test_validator_flags_orphan_narration_between_act_and_anchor() -> None:
    script = (
        "[TITLE] Demo\n"
        "[HOOK]\n"
        '[ANCHOR ranges="00:00:00-00:00:10"]\n'
        + "x" * 40 + "\n"
        + "[ACT 1 - SETUP]\n"
        + "this orphan line is not under an anchor and Stage 3 would drop it\n"
        + '[ANCHOR ranges="00:00:20-00:00:30"]\n'
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    orphans = [i for i in result.issues if i.code == "orphan_narration"]
    assert len(orphans) == 1
    assert "this orphan line" in orphans[0].message


def test_validator_flags_non_monotonic_anchors() -> None:
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:30-00:00:40"]\n'
        + "x" * 40 + "\n"
        + '[ANCHOR ranges="00:00:10-00:00:20"]\n'  # earlier — out of order
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert any(i.code == "non_monotonic" for i in result.issues)
    assert result.has_failures


def test_validator_allows_hook_to_act_backward_jump() -> None:
    # The niu-shu hook pulls a climax shot up front, then ACT 1 starts
    # the chronological telling from early-movie. This is the format's
    # signature opening, not a planner mistake.
    script = (
        "[TITLE] Demo\n"
        "[HOOK]\n"
        '[ANCHOR ranges="01:26:30-01:26:40"]\n'  # climax shot
        + "x" * 40 + "\n"
        + "[ACT 1 - SETUP]\n"
        + '[ANCHOR ranges="00:09:50-00:10:00"]\n'  # early-movie, "earlier" than HOOK
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert not [i for i in result.issues if i.code == "non_monotonic"]


def test_validator_still_flags_scramble_within_one_act() -> None:
    # Per-section monotonic: jumps across sections are fine, but anchors
    # inside a single ACT must still march forward. Otherwise the audience
    # sees a confusing zigzag inside what should be linear storytelling.
    script = (
        "[TITLE] Demo\n"
        "[ACT 1 - SETUP]\n"
        '[ANCHOR ranges="00:09:00-00:09:10"]\n'
        + "x" * 40 + "\n"
        + '[ANCHOR ranges="00:15:00-00:15:10"]\n'
        + "x" * 40 + "\n"
        + '[ANCHOR ranges="00:11:00-00:11:10"]\n'  # backward inside ACT 1
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert any(i.code == "non_monotonic" for i in result.issues)
    assert result.has_failures


def test_validator_allows_cross_act_backward_jump() -> None:
    # ACT-to-ACT order is encoded by the structural markers themselves;
    # we do not enforce ACT 2's first anchor to be later than ACT 1's
    # last anchor. Rare in practice, but allowed.
    script = (
        "[TITLE] Demo\n"
        "[ACT 1 - SETUP]\n"
        '[ANCHOR ranges="00:30:00-00:30:10"]\n'
        + "x" * 40 + "\n"
        + "[ACT 2 - ESCALATION]\n"
        + '[ANCHOR ranges="00:20:00-00:20:10"]\n'  # earlier than ACT 1's start
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert not [i for i in result.issues if i.code == "non_monotonic"]


def test_validator_overrun_ratio_is_float_safe() -> None:
    # Construct a budget×ratio combination that produces a true 1.10 with
    # FP rounding noise; the grader must classify this as warn, not fail.
    # 11 chars / 10-char budget = 1.1000000000000001 in IEEE-754.
    script = "[TITLE] Demo\n" + '[ANCHOR ranges="00:00:00-00:00:02"]\n' + ("x" * 11) + "\n"
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert result.chunks[0].severity == "warn"


def test_validator_reports_bad_anchor_instead_of_raising() -> None:
    # A truly malformed anchor (overlapping ranges) used to crash the whole
    # validator. It should now surface as a structure issue and let the rest
    # of the script keep being checked.
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:30-00:00:40"]\n'
        + "x" * 40 + "\n"
        + '[ANCHOR ranges="00:01:00-00:01:10, 00:01:05-00:01:15"]\n'  # overlap
        + "narration that belongs to the bad anchor\n"
        + '[ANCHOR ranges="00:11:00-00:11:10"]\n'
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    bad = [i for i in result.issues if i.code == "bad_anchor"]
    assert len(bad) == 1
    assert "overlap" in bad[0].message
    # The good anchors before/after still produced budget chunks.
    assert len(result.chunks) == 2
    # And the narration under the bad anchor was NOT double-flagged as orphan.
    assert not [i for i in result.issues if i.code == "orphan_narration"]
    assert result.has_failures


# --- Range provenance check -----------------------------------------------


def test_validator_passes_when_anchor_overlaps_real_timeline() -> None:
    timeline = build_timeline_intervals(
        subtitle_intervals=[(10.0, 14.0), (20.0, 24.0)],
        visual_segments=None,
    )
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:11-00:00:13"]\n'  # inside SRT 10-14
        + "x" * 10 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0, timeline_intervals=timeline)
    assert not [i for i in result.issues if i.code == "range_provenance"]


def test_validator_warns_on_near_miss_anchor_range() -> None:
    timeline = [(10.0, 14.0)]
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:14.500-00:00:15.500"]\n'  # 0.5s gap from end
        + "x" * 5 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0, timeline_intervals=timeline)
    provenance = [i for i in result.issues if i.code == "range_provenance"]
    assert len(provenance) == 1
    assert provenance[0].severity == "warn"


def test_validator_fails_on_fabricated_anchor_range() -> None:
    timeline = [(10.0, 14.0)]
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:01:00-00:01:10"]\n'  # 46s away from any timeline entry
        + "x" * 50 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0, timeline_intervals=timeline)
    provenance = [i for i in result.issues if i.code == "range_provenance"]
    assert len(provenance) == 1
    assert provenance[0].severity == "fail"
    assert result.has_failures


def test_validator_skips_provenance_when_timeline_not_supplied() -> None:
    # Same fabricated range, but caller did not pass timeline_intervals →
    # we don't have ground truth, so we don't penalize.
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:01:00-00:01:10"]\n'
        + "x" * 50 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0, timeline_intervals=None)
    assert not [i for i in result.issues if i.code == "range_provenance"]


def test_validator_fails_on_single_anchor_range_that_is_too_long() -> None:
    # Reproduces the SPL II planner-typo bug: a range whose end timestamp
    # leaks into the next hour. Provenance can't catch this because the
    # oversized window still overlaps real timeline entries.
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:10:00-00:12:30"]\n'  # 150s — well over the 12s cap
        + "x" * 20 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    too_long = [i for i in result.issues if i.code == "range_too_long"]
    assert len(too_long) == 1
    assert result.has_failures


# --- Shot-aware contract: anchor total duration cap -----------------------


def test_validator_fails_on_anchor_total_duration_over_cap() -> None:
    # Three sub-12s ranges that sum to 18s — each individual range is
    # legal but the multi-range anchor as a whole exceeds the 12s cap.
    # Within-anchor drift would exceed ~3s; split into two anchors.
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:00-00:00:06, 00:00:10-00:00:16, 00:00:20-00:00:26"]\n'
        + "x" * 80 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    too_long = [i for i in result.issues if i.code == "anchor_too_long"]
    assert len(too_long) == 1
    assert "18.0s" in too_long[0].message
    assert result.has_failures


def test_validator_passes_anchor_total_exactly_at_cap() -> None:
    # 12s total is the cap, not over it.
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:00-00:00:06, 00:00:10-00:00:16"]\n'
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(script, chars_per_second=5.0)
    assert not [i for i in result.issues if i.code == "anchor_too_long"]


def test_validator_constants_match_each_other() -> None:
    # Both caps are tied to the same shot-aware design intent. They can
    # diverge in the future, but for now they should be equal so the
    # validator's individual-range and total-anchor checks describe the
    # same audience-comfort budget.
    assert MAX_ANCHOR_RANGE_DURATION_S == MAX_ANCHOR_TOTAL_DURATION_S


# --- Shot-aware contract: range-shot-crossing detection -------------------


def test_build_shot_boundary_set_collects_segment_edges_and_inner_cuts() -> None:
    segments = [
        {
            "start": "00:00:10.000",
            "end": "00:00:18.000",
            "shot_boundaries_s": [],
        },
        {
            "start": "00:00:18.000",  # also a shot cut (between segs)
            "end": "00:00:30.000",
            "shot_boundaries_s": [22.0, 25.5],
        },
    ]
    boundaries = build_shot_boundary_set(segments)
    # 10.0 (seg-A start, but it's the first one — let's see) + 18 + 22 + 25.5 + 30
    # build_shot_boundary_set excludes near-zero starts; 10s is far from 0 so kept.
    assert boundaries == [10.0, 18.0, 22.0, 25.5, 30.0]


def test_build_shot_boundary_set_skips_near_zero_movie_start() -> None:
    segments = [
        {"start": "00:00:00.000", "end": "00:00:08.000", "shot_boundaries_s": []},
    ]
    # The very first segment starts at t=0 (movie start). That's not a cut,
    # so it should not appear in the boundary set.
    assert build_shot_boundary_set(segments) == [8.0]


def test_validator_fails_when_range_crosses_shot_boundary() -> None:
    # Shot boundaries at 18.0 and 30.0. Range 10-25 contains 18.0 strictly
    # inside (10 + 0.3 < 18 < 25 - 0.3) → failed range_shot_crossing.
    boundaries = [10.0, 18.0, 30.0]
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:10-00:00:25"]\n'  # crosses 18s
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(
        script, chars_per_second=5.0, shot_boundaries=boundaries,
    )
    crossings = [i for i in result.issues if i.code == "range_shot_crossing"]
    assert len(crossings) == 1
    assert "00:00:18" in crossings[0].message
    assert result.has_failures


def test_validator_passes_range_inside_one_shot() -> None:
    # Range 10-17.5 sits inside the [10, 18] shot — no boundary inside it.
    boundaries = [10.0, 18.0, 30.0]
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:10-00:00:17.500"]\n'
        + "x" * 30 + "\n"
    )
    result = validate_anchored_script(
        script, chars_per_second=5.0, shot_boundaries=boundaries,
    )
    assert not [i for i in result.issues if i.code == "range_shot_crossing"]


def test_validator_tolerance_forgives_boundary_at_range_edge() -> None:
    # A boundary that lines up with the range's edge (within tolerance)
    # is "at the edge", not "strictly inside". Range 10.0-18.1 is treated
    # as ending at the 18.0 cut, not crossing into the next shot.
    boundaries = [10.0, 18.0, 30.0]
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:10-00:00:18.100"]\n'
        + "x" * 30 + "\n"
    )
    result = validate_anchored_script(
        script, chars_per_second=5.0, shot_boundaries=boundaries,
    )
    assert not [i for i in result.issues if i.code == "range_shot_crossing"]


def test_validator_skips_shot_check_when_boundaries_not_supplied() -> None:
    # Same range that would cross a shot if boundaries were known —
    # without boundaries we skip the check entirely (caller has no
    # ground truth).
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:10-00:00:25"]\n'
        + "x" * 40 + "\n"
    )
    result = validate_anchored_script(
        script, chars_per_second=5.0, shot_boundaries=None,
    )
    assert not [i for i in result.issues if i.code == "range_shot_crossing"]


def test_validator_flags_shot_crossing_per_offending_range() -> None:
    # A multi-range anchor where two ranges each cross a different cut.
    boundaries = [10.0, 18.0, 22.0, 30.0]
    script = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:10-00:00:20, 00:00:21-00:00:25"]\n'  # crosses 18 AND nothing
        + "x" * 30 + "\n"
    )
    # First range crosses 18; second range crosses 22.
    script_two = (
        "[TITLE] Demo\n"
        '[ANCHOR ranges="00:00:11-00:00:19, 00:00:21-00:00:25"]\n'
        + "x" * 30 + "\n"
    )
    result = validate_anchored_script(
        script_two, chars_per_second=5.0, shot_boundaries=boundaries,
    )
    crossings = [i for i in result.issues if i.code == "range_shot_crossing"]
    # Each offending range is reported once.
    assert len(crossings) == 2


def test_build_timeline_intervals_combines_srt_and_visuals() -> None:
    intervals = build_timeline_intervals(
        subtitle_intervals=[(10.0, 14.0)],
        visual_segments=[
            {"start": "00:00:20.000", "end": "00:00:24.000"},
            {"start": "00:00:30.000", "end": "00:00:30.000"},  # zero-duration → skipped
            {"start": "bad", "end": "data"},  # malformed → skipped
        ],
    )
    assert intervals == [(10.0, 14.0), (20.0, 24.0)]
