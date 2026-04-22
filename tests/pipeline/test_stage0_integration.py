import os
import pytest
from pathlib import Path
from app.pipeline.stage0_index_visuals import main

@pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not found in environment"
)
def test_stage0_integration_small_clip(tmp_path):
    """
    Integration test that actually calls the Gemini API.
    Uses a small compressed fixture video to keep it fast and portable.
    """
    fixture_video = Path(__file__).parent.parent / "fixtures" / "test_indexing_clip.mp4"
    if not fixture_video.exists():
        pytest.skip(f"Fixture video {fixture_video} not found.")
        
    output_path = tmp_path / "integration_segments.json"
    
    import sys
    from unittest.mock import patch
    
    # Run the indexer on the small fixture
    args = [
        "index-visuals",
        "--video", str(fixture_video),
        "--output", str(output_path),
        "--chunk-minutes", "1",
        "--tmp-dir", str(tmp_path / "tmp")
    ]
    
    with patch.object(sys, 'argv', args):
        exit_code = main()
            
    assert exit_code == 0
    assert output_path.exists()
    
    # Basic validation of the result
    import json
    data = json.loads(output_path.read_text())
    assert isinstance(data, list)
    if len(data) > 0:
        assert "start" in data[0]
        assert "summary" in data[0]
