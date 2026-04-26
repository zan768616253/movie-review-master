from pytest import MonkeyPatch

from app.pipeline.common.video_encoder import resolve_encoder


def test_resolve_encoder_requires_nvenc(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("app.pipeline.common.video_encoder.nvenc_available", lambda: False)
    monkeypatch.setattr("app.pipeline.common.video_encoder.cuda_decode_available", lambda: True)

    try:
        resolve_encoder()
    except RuntimeError as exc:
        assert "h264_nvenc" in str(exc)
    else:
        raise AssertionError("resolve_encoder() should fail when NVENC is unavailable")


def test_resolve_encoder_requires_cuda_decode(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("app.pipeline.common.video_encoder.nvenc_available", lambda: True)
    monkeypatch.setattr("app.pipeline.common.video_encoder.cuda_decode_available", lambda: False)

    try:
        resolve_encoder()
    except RuntimeError as exc:
        assert "CUDA" in str(exc)
    else:
        raise AssertionError("resolve_encoder() should fail when CUDA decode is unavailable")


def test_resolve_encoder_returns_nvenc_when_gpu_pipeline_is_available(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("app.pipeline.common.video_encoder.nvenc_available", lambda: True)
    monkeypatch.setattr("app.pipeline.common.video_encoder.cuda_decode_available", lambda: True)

    assert resolve_encoder() == "h264_nvenc"