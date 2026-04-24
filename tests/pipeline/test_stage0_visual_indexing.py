import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.pipeline.stage0_indexers.base import (
    seconds_to_timestamp,
    timestamp_to_seconds,
    merge_segments,
)
from app.pipeline.stage0_indexers.gemini import GeminiStrategy
from app.pipeline.stage0_indexers.ollama import OllamaStrategy


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
    @patch("app.pipeline.stage0_indexers.gemini.genai")
    @patch("app.pipeline.stage0_indexers.gemini.get_video_duration")
    @patch.object(GeminiStrategy, "_extract_chunk")
    def test_index_video_splits_and_merges(self, mock_extract, mock_duration, mock_genai, tmp_path):
        tmp_idx_dir = tmp_path / "tmp"
        tmp_idx_dir.mkdir()

        mock_duration.return_value = 900.0  # 15 mins -> 2 chunks

        response_text = json.dumps([{
            "start": "00:00:00.000", "end": "00:00:03.000", "summary": "test",
            "ocr_text": "", "is_action": True, "confidence": 0.9, "characters": []
        }])
        mock_genai.Client.return_value = _build_fake_gemini_client(response_text)

        strategy = GeminiStrategy(api_key="fake")
        results = strategy.index_video(tmp_path / "movie.mp4", [], 10, tmp_idx_dir)

        assert len(results) == 2
        assert mock_extract.call_count == 2
        assert results[0]["start"] == "00:00:00.000"
        assert results[1]["start"] == "00:10:00.000"

    @patch("app.pipeline.stage0_indexers.gemini.genai")
    @patch("app.pipeline.stage0_indexers.gemini.get_video_duration")
    @patch.object(GeminiStrategy, "_extract_chunk")
    def test_characters_passed_to_prompt(self, mock_extract, mock_duration, mock_genai, tmp_path):
        tmp_idx_dir = tmp_path / "tmp"
        tmp_idx_dir.mkdir()
        mock_duration.return_value = 60.0  # 1 min -> 1 chunk

        mock_client = _build_fake_gemini_client(json.dumps([]))
        mock_genai.Client.return_value = mock_client

        strategy = GeminiStrategy(api_key="fake")
        strategy.index_video(tmp_path / "m.mp4", ["Yuta", "Gojo"], 10, tmp_idx_dir)

        prompt_text = mock_client.models.generate_content.call_args.kwargs["contents"][1]
        assert "Yuta" in prompt_text
        assert "Gojo" in prompt_text


# ---------------------------------------------------------------------------
# Ollama strategy unit tests
# ---------------------------------------------------------------------------

class TestOllamaStrategy:
    @patch("app.pipeline.stage0_indexers.ollama.subprocess.run")
    @patch("app.pipeline.stage0_indexers.ollama.requests.post")
    def test_identical_frames_collapse(self, mock_post, mock_run, tmp_path):
        """Two frames with identical summary + characters must collapse into one segment."""
        strategy = OllamaStrategy()

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        for i in range(3):
            (frames_dir / f"frame_{i:05d}.jpg").write_bytes(b"img")

        class MockResponse:
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": json.dumps({
                "summary": "hero walks forward", "ocr_text": "",
                "is_action": True, "confidence": 0.9, "characters": ["Hero"]
            })}}

        mock_post.return_value = MockResponse()

        results = strategy.index_video(tmp_path / "m.mp4", ["Hero"], 10, tmp_path)

        assert len(results) == 1
        assert results[0]["start"] == "00:00:00.000"
        assert results[0]["end"] == "00:00:09.000"  # 3 frames * 3s

    @patch("app.pipeline.stage0_indexers.ollama.subprocess.run")
    @patch("app.pipeline.stage0_indexers.ollama.requests.post")
    def test_different_frames_no_collapse(self, mock_post, mock_run, tmp_path):
        """Frames with different summaries must stay separate."""
        strategy = OllamaStrategy()

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_00000.jpg").write_bytes(b"img1")
        (frames_dir / "frame_00001.jpg").write_bytes(b"img2")

        call_count = 0
        class MockResponse:
            def raise_for_status(self): pass
            def json(self_inner):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return {"message": {"content": json.dumps({
                        "summary": "hero walks forward", "ocr_text": "",
                        "is_action": True, "confidence": 0.9, "characters": ["Hero"]
                    })}}
                else:
                    return {"message": {"content": json.dumps({
                        "summary": "villain attacks from above", "ocr_text": "",
                        "is_action": True, "confidence": 0.95, "characters": ["Villain"]
                    })}}

        mock_post.return_value = MockResponse()

        results = strategy.index_video(tmp_path / "m.mp4", ["Hero", "Villain"], 10, tmp_path)

        assert len(results) == 2
        assert results[0]["end"] == "00:00:03.000"
        assert results[1]["start"] == "00:00:03.000"

    @patch("app.pipeline.stage0_indexers.ollama.subprocess.run")
    @patch("app.pipeline.stage0_indexers.ollama.requests.post")
    def test_json_fallback_on_bad_response(self, mock_post, mock_run, tmp_path):
        """When Ollama returns non-JSON, strategy should not crash."""
        strategy = OllamaStrategy()

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        (frames_dir / "frame_00000.jpg").write_bytes(b"img")

        class MockResponse:
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "this is not valid json at all"}}

        mock_post.return_value = MockResponse()

        results = strategy.index_video(tmp_path / "m.mp4", [], 10, tmp_path)

        assert len(results) == 1
        assert results[0]["confidence"] == 0.5  # fallback value

    @patch("app.pipeline.stage0_indexers.ollama.subprocess.run")
    def test_no_frames_returns_empty(self, mock_run, tmp_path):
        """When ffmpeg produces no frames, should return empty list."""
        strategy = OllamaStrategy()
        # frames dir exists but has no frame files
        (tmp_path / "frames").mkdir()

        results = strategy.index_video(tmp_path / "m.mp4", [], 10, tmp_path)
        assert results == []

    def test_compute_similarity_identical(self):
        strategy = OllamaStrategy()
        sim = strategy._compute_similarity("hero walks forward", "hero walks forward")
        assert sim == pytest.approx(1.0)

    def test_compute_similarity_different(self):
        strategy = OllamaStrategy()
        sim = strategy._compute_similarity("hero walks forward", "villain attacks from above")
        assert sim < 0.5

    def test_compute_similarity_empty(self):
        strategy = OllamaStrategy()
        assert strategy._compute_similarity("", "hello") == 0.0
        assert strategy._compute_similarity("hello", "") == 0.0
