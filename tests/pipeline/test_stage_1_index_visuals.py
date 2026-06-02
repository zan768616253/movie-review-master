import os
import json
import subprocess
import time
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.stage_1_index_visuals import build_parser
from app.pipeline.stage_1.base import (
    detect_shot_boundaries,
    seconds_to_timestamp,
    snap_to_shot_boundaries,
    timestamp_to_seconds,
    merge_segments,
)
from app.pipeline.common.script_contract import validate_visual_segments
from app.pipeline.stage_1.shared import build_prompt
from app.pipeline.stage_1.gemini import GeminiStrategy


# ---------------------------------------------------------------------------
# Base utility tests
# ---------------------------------------------------------------------------

class TestTimestampConversion:
    def test_zero(self):
        assert seconds_to_timestamp(0) == "00:00:00.000"

    def test_large_value(self):
        assert seconds_to_timestamp(3661.123) == "01:01:01.123"

    def test_sub_second(self):
        assert seconds_to_timestamp(0.5) == "00:00:00.500"

    def test_roundtrip(self):
        for secs in [0, 1.5, 61, 3661.123, 7200]:
            assert timestamp_to_seconds(seconds_to_timestamp(secs)) == pytest.approx(secs)

    def test_timestamp_hms(self):
        assert timestamp_to_seconds("00:00:00.000") == 0.0
        assert timestamp_to_seconds("01:01:01.123") == pytest.approx(3661.123)

    def test_timestamp_ms(self):
        assert timestamp_to_seconds("01:01") == 61.0

    def test_timestamp_bare_number(self):
        assert timestamp_to_seconds("42.5") == 42.5


class TestMergeSegments:
    def test_two_chunks(self):
        chunk_1 = [{"start": "00:00:00.000", "end": "00:00:05.000", "summary": "s1"}]
        chunk_2 = [{"start": "00:00:01.000", "end": "00:00:04.000", "summary": "s2"}]
        merged = merge_segments([chunk_1, chunk_2], 600.0)

        assert len(merged) == 2
        assert merged[0]["start"] == "00:00:00.000"
        assert merged[1]["start"] == "00:10:01.000"

    def test_empty_chunks(self):
        merged = merge_segments([], 600.0)
        assert merged == []

    def test_single_chunk(self):
        chunk = [{"start": "00:00:02.000", "end": "00:00:05.000", "summary": "only"}]
        merged = merge_segments([chunk], 600.0)
        assert len(merged) == 1
        assert merged[0]["start"] == "00:00:02.000"

    def test_preserves_extra_fields(self):
        chunk = [{"start": "00:00:00.000", "end": "00:00:03.000", "extra": "kept"}]
        merged = merge_segments([chunk], 600.0)
        assert merged[0]["extra"] == "kept"

    def test_shifts_inner_shot_boundaries_to_absolute_time(self):
        # Regression: ``snap_to_shot_boundaries`` populates ``shot_boundaries_s``
        # with chunk-local seconds. Pre-2026-04-30 ``merge_segments`` shifted
        # ``start``/``end`` but not the inner-cut list, so 96% of inner cuts
        # ended up pointing one chunk earlier than their parent segment.
        chunk_0 = [{
            "start": "00:00:30.000", "end": "00:00:42.000", "summary": "s0",
            "shot_boundaries_s": [33.0, 38.0],
        }]
        chunk_1 = [{
            "start": "00:00:30.000", "end": "00:00:42.000", "summary": "s1",
            "shot_boundaries_s": [33.0, 38.0],  # chunk-local seconds (same numbers!)
        }]
        merged = merge_segments([chunk_0, chunk_1], 300.0)
        # Chunk 0 (offset 0): boundaries unchanged.
        assert merged[0]["shot_boundaries_s"] == [33.0, 38.0]
        # Chunk 1 (offset 300): boundaries shifted into absolute time and
        # now fall STRICTLY INSIDE the segment's absolute window.
        seg1 = merged[1]
        assert seg1["start"] == "00:05:30.000"
        assert seg1["end"] == "00:05:42.000"
        assert seg1["shot_boundaries_s"] == [333.0, 338.0]

    def test_handles_empty_inner_boundaries(self):
        chunk = [{
            "start": "00:00:00.000", "end": "00:00:05.000", "summary": "s",
            "shot_boundaries_s": [],
        }]
        merged = merge_segments([chunk, chunk], 300.0)
        assert merged[0]["shot_boundaries_s"] == []
        assert merged[1]["shot_boundaries_s"] == []

    def test_drops_unparseable_inner_boundary_entries(self):
        # snap_to_shot_boundaries should never emit non-numeric entries, but
        # an external migration / hand-edit might. The shifter must skip them
        # rather than crash the whole pipeline.
        chunk = [{
            "start": "00:00:00.000", "end": "00:00:10.000", "summary": "s",
            "shot_boundaries_s": [3.0, "bad", None, 7.0],
        }]
        merged = merge_segments([chunk], 300.0)  # offset 0 for chunk 0
        assert merged[0]["shot_boundaries_s"] == [3.0, 7.0]

    def test_repairs_range_packed_start_timestamp_before_merging(self):
        chunk = [{
            "start": "00:00:01.000 - 00:00:04.000",
            "end": "00:00:04.000",
            "summary": "range packed",
        }]

        merged = merge_segments([chunk], 300.0)

        assert merged == [{
            "start": "00:00:01.000",
            "end": "00:00:04.000",
            "summary": "range packed",
        }]


class TestValidateVisualSegments:
    def test_repairs_range_packed_end_timestamp_before_validation(self):
        segments = [{
            "start": "00:00:10.000",
            "end": "00:00:10.000 - 00:00:14.500",
            "summary": "range packed",
        }]

        validated, diagnostics = validate_visual_segments(segments, video_duration_s=100.0)

        assert diagnostics.kept == 1
        assert validated == [{
            "start": "00:00:10.000",
            "end": "00:00:14.500",
            "summary": "range packed",
        }]


class TestSnapToShotBoundaries:
    def test_snaps_start_and_end_within_tolerance(self):
        segments = [{"start": "00:00:04.800", "end": "00:00:09.300", "summary": "x"}]
        snapped = snap_to_shot_boundaries(segments, [5.0, 9.0], tolerance_s=0.5)
        assert snapped[0]["start"] == "00:00:05.000"
        assert snapped[0]["end"] == "00:00:09.000"

    def test_leaves_timestamps_alone_when_no_boundary_is_within_tolerance(self):
        segments = [{"start": "00:00:02.000", "end": "00:00:07.000", "summary": "x"}]
        snapped = snap_to_shot_boundaries(segments, [5.0], tolerance_s=0.5)
        assert snapped[0]["start"] == "00:00:02.000"
        assert snapped[0]["end"] == "00:00:07.000"

    def test_empty_boundaries_annotates_with_empty_shot_list(self):
        segments = [{"start": "00:00:02.000", "end": "00:00:07.000", "summary": "x"}]
        snapped = snap_to_shot_boundaries(segments, [], tolerance_s=1.5)
        assert snapped[0]["start"] == "00:00:02.000"
        assert snapped[0]["end"] == "00:00:07.000"
        assert snapped[0]["shot_boundaries_s"] == []

    def test_keeps_originals_when_snap_would_invert_segment(self):
        # Both start and end would snap to 5.0, which would zero-length the
        # segment; the helper must keep the originals in that case.
        segments = [{"start": "00:00:05.200", "end": "00:00:05.600", "summary": "x"}]
        snapped = snap_to_shot_boundaries(segments, [5.0], tolerance_s=1.5)
        assert snapped[0]["start"] == "00:00:05.200"
        assert snapped[0]["end"] == "00:00:05.600"

    def test_emits_inner_shot_boundaries_for_smart_trim(self):
        # 10s segment with two cuts inside it (at +4s and +7s relative to start).
        segments = [{"start": "00:00:10.000", "end": "00:00:20.000", "summary": "x"}]
        boundaries = [10.0, 14.0, 17.0, 20.0]
        snapped = snap_to_shot_boundaries(segments, boundaries, tolerance_s=0.5)
        # Outer boundaries (10.0, 20.0) coincide with start/end; only the
        # two inner cuts (14.0 and 17.0) should land in shot_boundaries_s.
        assert snapped[0]["shot_boundaries_s"] == [14.0, 17.0]


class TestDetectShotBoundaries:
    @patch("app.pipeline.stage_1.base.subprocess.run")
    def test_uses_utf8_decoding_for_ffmpeg_output(self, mock_run, tmp_path):
        mock_run.return_value = SimpleNamespace(
            stderr="frame=1 pts_time:1.25\nframe=2 pts_time:2.5\n"
        )

        cuts = detect_shot_boundaries(tmp_path / "movie.mp4")

        assert cuts == [1.25, 2.5]
        assert mock_run.call_args.kwargs["encoding"] == "utf-8"
        assert mock_run.call_args.kwargs["errors"] == "replace"

    @patch("app.pipeline.stage_1.base.subprocess.run")
    def test_missing_stderr_returns_no_cuts_instead_of_crashing(self, mock_run, tmp_path):
        mock_run.return_value = SimpleNamespace(stderr=None)

        assert detect_shot_boundaries(tmp_path / "movie.mp4") == []


# ---------------------------------------------------------------------------
# Gemini strategy unit tests
# ---------------------------------------------------------------------------

def _build_fake_gemini_client(response_text: str) -> MagicMock:
    """Wire up a MagicMock that looks like a google.genai Client for our usage."""
    mock_client = MagicMock()

    mock_file = MagicMock()
    mock_file.state.name = "ACTIVE"
    mock_client.files.upload.return_value = mock_file
    mock_client.files.get.return_value = mock_file

    mock_response = MagicMock()
    mock_response.text = response_text
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


class TestGeminiStrategy:
    @patch("app.pipeline.stage_1.gemini.detect_shot_boundaries", return_value=[])
    @patch("app.pipeline.stage_1.gemini.genai")
    @patch("app.pipeline.stage_1.gemini.get_video_duration")
    @patch.object(GeminiStrategy, "_extract_chunk")
    def test_index_video_splits_and_merges(
        self, mock_extract, mock_duration, mock_genai, mock_boundaries, tmp_path,
    ):
        tmp_idx_dir = tmp_path / "tmp"
        tmp_idx_dir.mkdir()

        mock_duration.return_value = 600.0  # 10 mins -> 2 chunks with a 7-minute default

        response_text = json.dumps([{
            "start": "00:00:00.000", "end": "00:00:03.000", "summary": "test",
            "ocr_text": "", "characters": []
        }])
        mock_genai.Client.return_value = _build_fake_gemini_client(response_text)

        strategy = GeminiStrategy(api_key="fake")
        results = strategy.index_video(tmp_path / "movie.mp4", tmp_idx_dir)

        assert len(results) == 2
        assert mock_extract.call_count == 2
        assert results[0]["start"] == "00:00:00.000"
        assert results[1]["start"] == "00:07:00.000"

    @patch("app.pipeline.stage_1.gemini.detect_shot_boundaries", return_value=[])
    @patch("app.pipeline.stage_1.gemini.genai")
    @patch("app.pipeline.stage_1.gemini.get_video_duration")
    @patch.object(GeminiStrategy, "_extract_chunk")
    def test_prompt_contract_covers_timestamps_characters_and_dialogue_skip(
        self, mock_extract, mock_duration, mock_genai, mock_boundaries, tmp_path,
    ):
        tmp_idx_dir = tmp_path / "tmp"
        tmp_idx_dir.mkdir()
        mock_duration.return_value = 60.0  # 1 min -> 1 chunk

        mock_client = _build_fake_gemini_client(json.dumps([]))
        mock_genai.Client.return_value = mock_client

        strategy = GeminiStrategy(api_key="fake")
        strategy.index_video(tmp_path / "m.mp4", tmp_idx_dir)

        prompt_text = mock_client.models.generate_content.call_args.kwargs["contents"][1]
        # Timestamps: model is told to read burned-in values, not estimate.
        assert "burned into the TOP-LEFT corner" in prompt_text
        assert "Do NOT estimate or round timestamps" in prompt_text
        # Dialogue skip keeps Stage 0 focused on visual-only events.
        assert "shot-reverse-shot dialogue" in prompt_text
        # Characters: no guessing without visual re-identification.
        assert "visually re-identify" in prompt_text
        assert "NEVER guess" in prompt_text

    @patch("app.pipeline.stage_1.gemini.detect_shot_boundaries", return_value=[])
    @patch("app.pipeline.stage_1.gemini.genai")
    @patch("app.pipeline.stage_1.gemini.get_video_duration")
    @patch.object(GeminiStrategy, "_extract_chunk")
    def test_index_video_persists_and_reuses_chunk_segments(
        self, mock_extract, mock_duration, mock_genai, mock_boundaries, tmp_path,
    ):
        tmp_idx_dir = tmp_path / "tmp"
        tmp_idx_dir.mkdir()

        mock_duration.return_value = 600.0
        response_text = json.dumps([{
            "start": "00:00:00.000", "end": "00:00:03.000", "summary": "test",
            "ocr_text": "", "characters": []
        }])
        mock_genai.Client.return_value = _build_fake_gemini_client(response_text)

        strategy = GeminiStrategy(api_key="fake")
        first_results = strategy.index_video(tmp_path / "movie.mp4", tmp_idx_dir)

        cache_dir = tmp_idx_dir / "segments"
        chunk_001_cache = cache_dir / "chunk_001.json"
        assert (cache_dir / "chunk_000.json").exists()
        assert chunk_001_cache.exists()
        assert json.loads(chunk_001_cache.read_text())[0]["start"] == "00:00:00.000"
        assert first_results[1]["start"] == "00:07:00.000"

        with patch.object(strategy, "_extract_chunk", side_effect=AssertionError("should not extract")), \
             patch.object(strategy, "_index_chunk", side_effect=AssertionError("should not reindex")), \
             patch("app.pipeline.stage_1.gemini.detect_shot_boundaries", side_effect=AssertionError("should not detect")):
            second_results = strategy.index_video(tmp_path / "movie.mp4", tmp_idx_dir)

        assert second_results == first_results

    @patch("app.pipeline.stage_1.gemini.get_video_duration", return_value=600.0)
    def test_index_video_parallel_preserves_chunk_order(self, mock_duration, tmp_path):
        tmp_idx_dir = tmp_path / "tmp"
        tmp_idx_dir.mkdir()
        strategy = GeminiStrategy(api_key="fake", max_workers=2)

        def fake_process(video_path, tmp_dir, chunk_index, start_s, duration_s):
            if chunk_index == 0:
                time.sleep(0.05)
            return [{
                "start": "00:00:00.000",
                "end": "00:00:03.000",
                "summary": f"chunk-{chunk_index}",
                "ocr_text": "",
                "characters": [],
            }]

        with patch.object(strategy, "_process_chunk", side_effect=fake_process):
            results = strategy.index_video(tmp_path / "movie.mp4", tmp_idx_dir)

        assert [segment["summary"] for segment in results] == ["chunk-0", "chunk-1"]
        assert results[1]["start"] == "00:07:00.000"

    @patch("app.pipeline.stage_1.gemini.hwaccel_decode_args", return_value=["-hwaccel", "cuda"])
    @patch("app.pipeline.stage_1.gemini.nvenc_available", return_value=True)
    @patch("app.pipeline.stage_1.gemini.subprocess.run")
    def test_extract_chunk_falls_back_to_cpu_when_cuda_decode_fails(
        self,
        mock_run,
        mock_nvenc,
        mock_hwaccel,
        tmp_path,
    ):
        strategy = GeminiStrategy(api_key="fake")

        def fake_run(cmd, **kwargs):
            if "-hwaccel" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr="CUDA decode failed")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        mock_run.side_effect = fake_run

        with patch(
            "app.pipeline.stage_1.gemini.build_timestamp_drawtext_filter",
            return_value="drawtext=mock",
        ):
            strategy._extract_chunk(
                tmp_path / "movie.mp4",
                start_s=10.0,
                duration_s=20.0,
                out_path=tmp_path / "chunk.mp4",
            )

        assert mock_run.call_count == 2

        first_call = mock_run.call_args_list[0]
        second_call = mock_run.call_args_list[1]
        second_cmd = second_call.args[0]
        assert first_call.args[0][:5] == ["ffmpeg", "-y", "-loglevel", "error", "-hwaccel"]
        assert "-hwaccel" not in second_cmd
        vf_index = second_cmd.index("-vf")
        assert second_cmd[vf_index:vf_index + 8] == [
            "-vf", "drawtext=mock",
            "-c:v", "h264_nvenc", "-preset", "p1", "-pix_fmt", "yuv420p",
        ]
        assert second_cmd[-1] == str(tmp_path / "chunk.mp4")
        assert first_call.kwargs["encoding"] == "utf-8"
        assert first_call.kwargs["errors"] == "replace"


def test_stage0_parser_requires_synopsis_and_characters_dir():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--video", "movie.mp4"])


def test_stage0_parser_accepts_required_synopsis_and_characters_dir(tmp_path):
    synopsis = tmp_path / "synopsis.md"
    synopsis.write_text("Yuta: protagonist", encoding="utf-8")

    characters_dir = tmp_path / "characters"
    characters_dir.mkdir()
    (characters_dir / "Kit.jpg").write_bytes(b"fake-image")

    args = build_parser().parse_args([
        "--video",
        "movie.mp4",
        "--synopsis",
        str(synopsis),
        "--characters-dir",
        str(characters_dir),
    ])
    assert args.synopsis == synopsis
    assert args.characters_dir == characters_dir


def test_stage0_parser_rejects_empty_characters_dir(tmp_path):
    synopsis = tmp_path / "synopsis.md"
    synopsis.write_text("Yuta: protagonist", encoding="utf-8")

    empty_characters_dir = tmp_path / "characters"
    empty_characters_dir.mkdir()

    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "--video",
            "movie.mp4",
            "--synopsis",
            str(synopsis),
            "--characters-dir",
            str(empty_characters_dir),
        ])


def test_stage0_timestamp_font_path_from_env_exists():
    font_path = Path(os.environ["STAGE0_TIMESTAMP_FONT_PATH"])

    assert font_path.exists()
    assert font_path.is_file()


# ---------------------------------------------------------------------------
# build_prompt — synopsis-aware Cast Reference branch
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_no_synopsis_uses_conservative_character_rule(self):
        prompt = build_prompt()
        assert "Cast Reference" not in prompt
        # Original conservative rule: visual re-id only, no franchise guessing.
        assert "visually re-identify" in prompt
        assert "NEVER guess from general knowledge" in prompt

    def test_empty_synopsis_treated_as_no_synopsis(self):
        # Whitespace-only synopsis input is the no-reference case.
        assert build_prompt("   \n  ") == build_prompt("")

    def test_synopsis_inlines_cast_reference_block(self):
        synopsis = "## Main Characters\n- Yuta: protagonist\n- Rika: cursed spirit"
        prompt = build_prompt(synopsis)
        assert "<<<CAST_REFERENCE_START>>>" in prompt
        assert "Yuta: protagonist" in prompt
        assert "<<<CAST_REFERENCE_END>>>" in prompt

    def test_synopsis_swaps_in_reference_grounded_character_rule(self):
        synopsis = "Yuta: protagonist"
        prompt = build_prompt(synopsis)
        # Reference-grounded rule: VLM may name characters from the cast
        # but must not introduce ones outside it.
        assert "match them to an entry in the Cast Reference below" in prompt
        assert "do NOT introduce any character not on it" in prompt
        # The conservative no-synopsis rule must be GONE — otherwise the VLM
        # gets contradictory instructions.
        assert "NEVER guess from general knowledge" not in prompt

    def test_has_face_gallery_includes_face_gallery_instructions(self):
        prompt = build_prompt(has_face_gallery=True)
        assert "# Face Gallery (CRITICAL)" in prompt
        assert "Reference Image for <Name>" in prompt
        assert "Do NOT invent variations" in prompt


def test_gemini_strategy_uses_synopsis_and_face_gallery_when_provided(tmp_path):
    strategy = GeminiStrategy(api_key="fake", synopsis_text="Yuta: protagonist", characters_dir=tmp_path)
    assert "Cast Reference" in strategy.prompt
    assert "Yuta: protagonist" in strategy.prompt
    assert "# Face Gallery" in strategy.prompt


def test_strategy_without_synopsis_keeps_conservative_rule():
    strategy = GeminiStrategy(api_key="fake")
    assert "Cast Reference" not in strategy.prompt
    assert "NEVER guess from general knowledge" in strategy.prompt


@patch("app.pipeline.stage_1.gemini.genai")
def test_index_chunk_deletes_uploaded_file_when_json_parse_fails(mock_genai, tmp_path):
    mock_client = _build_fake_gemini_client("not valid json")
    mock_genai.Client.return_value = mock_client

    strategy = GeminiStrategy(api_key="fake")

    with pytest.raises(json.JSONDecodeError):
        strategy._index_chunk(tmp_path / "chunk.mp4")

    mock_client.files.delete.assert_called_once()


@patch("app.pipeline.stage_1.gemini.genai")
def test_index_chunk_uploads_face_gallery_and_cleans_up_all_files(mock_genai, tmp_path):
    mock_client = _build_fake_gemini_client(json.dumps([]))
    mock_genai.Client.return_value = mock_client

    chars_dir = tmp_path / "characters"
    chars_dir.mkdir()
    (chars_dir / "Kit.jpg").touch()
    (chars_dir / "Chatchai.png").touch()

    strategy = GeminiStrategy(api_key="fake", characters_dir=chars_dir)
    strategy._index_chunk(tmp_path / "chunk.mp4")

    # Uploads: Kit.jpg, Chatchai.png, chunk.mp4
    assert mock_client.files.upload.call_count == 3
    # Contents length: Kit (2) + Chatchai (2) + video (1) + prompt (1) = 6
    contents = mock_client.models.generate_content.call_args.kwargs["contents"]
    assert len(contents) == 6
    assert "Reference Image for Chatchai:" in contents[0]
    assert "Reference Image for Kit:" in contents[2]

    # Deletions: all 3 files
    assert mock_client.files.delete.call_count == 3
