import json
import pytest
from unittest.mock import MagicMock, patch

from app.pipeline.stage0_indexers.base import (
    seconds_to_timestamp,
    snap_to_shot_boundaries,
    timestamp_to_seconds,
    merge_segments,
)
from app.pipeline.stage0_indexers.gemini import GeminiStrategy
from app.pipeline.stage0_indexers.gemini import build_timestamp_drawtext_filter


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

    def test_empty_boundaries_is_noop(self):
        segments = [{"start": "00:00:02.000", "end": "00:00:07.000", "summary": "x"}]
        assert snap_to_shot_boundaries(segments, [], tolerance_s=1.5) == segments

    def test_keeps_originals_when_snap_would_invert_segment(self):
        # Both start and end would snap to 5.0, which would zero-length the
        # segment; the helper must keep the originals in that case.
        segments = [{"start": "00:00:05.200", "end": "00:00:05.600", "summary": "x"}]
        snapped = snap_to_shot_boundaries(segments, [5.0], tolerance_s=1.5)
        assert snapped[0]["start"] == "00:00:05.200"
        assert snapped[0]["end"] == "00:00:05.600"


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
    @patch("app.pipeline.stage0_indexers.gemini.detect_shot_boundaries", return_value=[])
    @patch("app.pipeline.stage0_indexers.gemini.genai")
    @patch("app.pipeline.stage0_indexers.gemini.get_video_duration")
    @patch.object(GeminiStrategy, "_extract_chunk")
    def test_index_video_splits_and_merges(
        self, mock_extract, mock_duration, mock_genai, mock_boundaries, tmp_path,
    ):
        tmp_idx_dir = tmp_path / "tmp"
        tmp_idx_dir.mkdir()

        mock_duration.return_value = 600.0  # 10 mins -> 2 chunks of 5 minutes

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
        assert results[1]["start"] == "00:05:00.000"

    @patch("app.pipeline.stage0_indexers.gemini.detect_shot_boundaries", return_value=[])
    @patch("app.pipeline.stage0_indexers.gemini.genai")
    @patch("app.pipeline.stage0_indexers.gemini.get_video_duration")
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


def test_build_timestamp_drawtext_filter_omits_fontfile_when_default_font_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.pipeline.stage0_indexers.gemini.DEFAULT_TIMESTAMP_FONT_PATH",
        tmp_path / "missing-font.ttf",
    )

    drawtext_filter = build_timestamp_drawtext_filter()

    assert "fontfile=" not in drawtext_filter
    assert drawtext_filter.startswith("drawtext=text=")


@patch("app.pipeline.stage0_indexers.gemini.genai")
def test_index_chunk_deletes_uploaded_file_when_json_parse_fails(mock_genai, tmp_path):
    mock_client = _build_fake_gemini_client("not valid json")
    mock_genai.Client.return_value = mock_client

    strategy = GeminiStrategy(api_key="fake")

    with pytest.raises(json.JSONDecodeError):
        strategy._index_chunk(tmp_path / "chunk.mp4")

    mock_client.files.delete.assert_called_once()
