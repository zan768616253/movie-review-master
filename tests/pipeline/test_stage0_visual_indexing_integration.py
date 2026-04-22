import json
import os
import sys
import pytest
import requests
from pathlib import Path
from unittest.mock import patch

from app.pipeline.stage0_index_visuals import main

FIXTURE_VIDEO = Path(__file__).parent.parent / "fixtures" / "test_indexing_clip.mp4"


def _ollama_model_available() -> bool:
    """Check if Ollama is running and the required model is listed."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in resp.json().get("models", [])]
        return "qwen3-vl:4b" in models
    except Exception:
        return False


def _ollama_model_healthy() -> bool:
    """Preflight: actually send a tiny text-only request to verify the model runner is stable."""
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "qwen3-vl:4b",
                "messages": [{"role": "user", "content": "Reply with exactly: {\"ok\":true}"}],
                "stream": False,
                "format": "json",
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        json.loads(content)  # must be valid JSON
        return True
    except Exception:
        return False


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
        "--chunk-minutes", "1",
        "--strategy", "gemini",
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


# ---------------------------------------------------------------------------
# Ollama integration
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ollama_model_available(),
    reason="Ollama not running or Qwen3-VL model not installed",
)
def test_stage0_ollama_integration(tmp_path):
    """
    End-to-end test that calls the real local Ollama Qwen3-VL model on the fixture clip.
    """
    if not _ollama_model_healthy():
        pytest.skip(
            "Ollama model runner is unstable (segfault / OOM). "
            "Check `journalctl -u ollama` for details."
        )

    if not FIXTURE_VIDEO.exists():
        pytest.skip(f"Fixture video {FIXTURE_VIDEO} not found.")

    output_path = tmp_path / "ollama_segments.json"

    args = [
        "index-visuals",
        "--video", str(FIXTURE_VIDEO),
        "--output", str(output_path),
        "--chunk-minutes", "1",
        "--strategy", "ollama",
        "--tmp-dir", str(tmp_path / "tmp"),
    ]

    with patch.object(sys, "argv", args):
        exit_code = main()

    assert exit_code == 0
    assert output_path.exists()

    data = json.loads(output_path.read_text())
    assert isinstance(data, list)
    assert len(data) > 0, "Ollama should return at least one segment for a 10s clip"
    for seg in data:
        assert "start" in seg
        assert "end" in seg
        assert "summary" in seg
        assert isinstance(seg["summary"], str)
