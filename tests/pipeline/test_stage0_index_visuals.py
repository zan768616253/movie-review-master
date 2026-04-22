import json
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.pipeline.stage0_index_visuals import (
    seconds_to_timestamp,
    timestamp_to_seconds,
    merge_segments,
    main
)

def test_seconds_to_timestamp():
    assert seconds_to_timestamp(0) == "00:00:00.000"
    assert seconds_to_timestamp(3661.123) == "01:01:01.123"

def test_timestamp_to_seconds():
    assert timestamp_to_seconds("00:00:00.000") == 0.0
    assert timestamp_to_seconds("01:01:01.123") == pytest.approx(3661.123)
    assert timestamp_to_seconds("01:01") == 61.0

def test_merge_segments():
    chunk_1 = [
        {"start": "00:00:00.000", "end": "00:00:05.000", "summary": "s1"}
    ]
    chunk_2 = [
        {"start": "00:00:01.000", "end": "00:00:04.000", "summary": "s2"}
    ]
    # 10 minute chunks = 600s
    merged = merge_segments([chunk_1, chunk_2], 600.0)
    
    assert len(merged) == 2
    assert merged[0]["start"] == "00:00:00.000"
    assert merged[1]["start"] == "00:10:01.000"

@patch("app.pipeline.stage0_index_visuals.get_video_duration")
@patch("app.pipeline.stage0_index_visuals.extract_chunk")
@patch("app.pipeline.stage0_index_visuals.GeminiVisualIndexer")
def test_main_flow(mock_indexer_cls, mock_extract, mock_duration, tmp_path, monkeypatch):
    video_path = tmp_path / "movie.mp4"
    video_path.write_text("fake video")
    
    # 15 minutes video = 2 chunks (10 min each)
    mock_duration.return_value = 900.0 
    
    mock_indexer = MagicMock()
    mock_indexer.index_chunk.return_value = [{"start": "0:00:00", "end": "0:00:05", "summary": "test", "ocr_text": "", "is_action": True, "confidence": 0.9, "characters": []}]
    mock_indexer_cls.return_value = mock_indexer
    
    monkeypatch.setenv("GOOGLE_API_KEY", "fake_key")
    
    args = ["index-visuals", "--video", str(video_path), "--tmp-dir", str(tmp_path / "tmp")]
    monkeypatch.setattr(sys, "argv", args)
    
    exit_code = main()
    
    assert exit_code == 0
    assert mock_extract.call_count == 2
    assert mock_indexer.index_chunk.call_count == 2
    
    output_path = video_path.parent / "visual_segments.json"
    assert output_path.exists()
    
    data = json.loads(output_path.read_text())
    assert len(data) == 2
    assert data[1]["start"] == "00:10:00.000"
