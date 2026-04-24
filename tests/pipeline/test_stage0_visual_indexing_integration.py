import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

from app.pipeline.stage0_index_visuals import main

FIXTURE_VIDEO = Path(__file__).parent.parent / "fixtures" / "test_indexing_clip.mp4"


# ---------------------------------------------------------------------------
# Gemini integration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not found in environment",
)
def test_stage0_gemini_integration(tmp_path):
    """
    End-to-end test that calls the real Gemini API on the fixture clip.
    """
    if not FIXTURE_VIDEO.exists():
        pytest.skip(f"Fixture video {FIXTURE_VIDEO} not found.")

    output_path = tmp_path / "gemini_segments.json"

    args = [
        "index-visuals",
        "--video", str(FIXTURE_VIDEO),
        "--output", str(output_path),
        "--tmp-dir", str(tmp_path / "tmp"),
    ]

    with patch.object(sys, "argv", args):
        exit_code = main()

    assert exit_code == 0
    assert output_path.exists()

    data = json.loads(output_path.read_text())
    assert isinstance(data, list)
    assert len(data) > 0, "Gemini should return at least one segment for a 10s clip"
    for seg in data:
        assert "start" in seg
        assert "end" in seg
        assert "summary" in seg
        assert isinstance(seg["summary"], str)
