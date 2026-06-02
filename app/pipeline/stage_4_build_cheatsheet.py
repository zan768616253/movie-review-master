"""Stage 4: build the editor cheatsheet (thumbnails + HTML) for 剪映.

Consumes the Stage 3 manifest (sentence-level segments + visual_segment
refs + resolved source ranges) and Stage 1's visual_segments.json + the
source movie, then produces:

- ``thumbnails/visual_NNN.jpg`` — one mid-shot frame per visual segment
  (320px wide, reused across cheatsheet runs)
- ``editor_cheatsheet.html`` — single self-contained page the operator
  opens next to 剪映 to find the right footage for each narration sentence

No third-party deps: ffmpeg + stdlib only. Thumbnails are extracted in a
thread pool; existing files are skipped so re-runs are cheap.
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from app.pipeline.common.json_io import load_json
from app.pipeline.common.script_contract import (
    load_visual_segments,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.common.video_encoder import cuda_decode_available


THUMB_WIDTH = 320
DEFAULT_WORKERS = 8


@dataclass(frozen=True)
class ShotInfo:
    seg_id: str
    start_s: float
    end_s: float
    summary: str
    ocr_text: str
    characters: list[str]

    @property
    def mid_s(self) -> float:
        return (self.start_s + self.end_s) / 2.0


def build_shot_index(visual_segments: list[dict[str, Any]]) -> dict[str, ShotInfo]:
    """Index visual_segments by their normalized visual:NNN id."""
    index: dict[str, ShotInfo] = {}
    for segment in visual_segments:
        seg_id = str(segment.get("id") or "").strip()
        if not seg_id:
            continue
        try:
            start_s = timestamp_to_seconds(str(segment["start"]))
            end_s = timestamp_to_seconds(str(segment["end"]))
        except (KeyError, ValueError):
            continue
        if end_s <= start_s:
            continue
        characters = segment.get("characters") or []
        index[seg_id] = ShotInfo(
            seg_id=seg_id,
            start_s=start_s,
            end_s=end_s,
            summary=str(segment.get("summary") or "").strip(),
            ocr_text=str(segment.get("ocr_text") or "").strip(),
            characters=[str(c) for c in characters if str(c).strip()],
        )
    return index


def _extract_one_thumbnail(
    *,
    video: Path,
    out_path: Path,
    at_s: float,
    width: int,
    run_cmd=subprocess.run,
) -> Optional[str]:
    """Extract a single thumbnail. Returns an error string on failure, None on success."""
    if out_path.exists():
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    hwaccel_args = ["-hwaccel", "cuda"] if cuda_decode_available() else []
    base_args = [
        "-ss", f"{max(at_s, 0.0):.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-vf", f"scale={width}:-2",
        "-q:v", "5",
        "-y",
        str(out_path),
    ]
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        *hwaccel_args,
        *base_args,
    ]
    try:
        run_cmd(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return f"ffmpeg not on PATH: {exc}"
    except subprocess.CalledProcessError as exc:
        if hwaccel_args:
            fallback_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                *base_args,
            ]
            try:
                run_cmd(fallback_cmd, check=True, capture_output=True, text=True)
                return None
            except subprocess.CalledProcessError as fallback_exc:
                details = (fallback_exc.stderr or "").strip() or f"exit {fallback_exc.returncode}"
                return details
        details = (exc.stderr or "").strip() or f"exit {exc.returncode}"
        return details
    return None


def extract_missing_thumbnails(
    *,
    video: Path,
    shots: dict[str, ShotInfo],
    thumbnails_dir: Path,
    width: int = THUMB_WIDTH,
    workers: int = DEFAULT_WORKERS,
    run_cmd=subprocess.run,
) -> tuple[int, int, list[str]]:
    """Extract thumbnails for any shots that don't already have one on disk.

    Returns ``(extracted, skipped, errors)`` where ``errors`` is a list of
    short messages tagged with the seg_id.
    """
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    pending: list[tuple[str, Path, float]] = []
    skipped = 0
    for shot in shots.values():
        out_path = thumbnails_dir / f"{shot.seg_id.replace(':', '_')}.jpg"
        if out_path.exists():
            skipped += 1
            continue
        pending.append((shot.seg_id, out_path, shot.mid_s))

    extracted = 0
    errors: list[str] = []
    if not pending:
        return extracted, skipped, errors

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(
                _extract_one_thumbnail,
                video=video,
                out_path=out_path,
                at_s=mid_s,
                width=width,
                run_cmd=run_cmd,
            ): seg_id
            for seg_id, out_path, mid_s in pending
        }
        for future in as_completed(futures):
            seg_id = futures[future]
            err = future.result()
            if err is None:
                extracted += 1
            else:
                errors.append(f"{seg_id}: {err}")
    return extracted, skipped, errors


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


_CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; max-width: 1200px; margin: 0 auto; padding: 16px; background: #fafafa; color: #222; line-height: 1.5; }
  header { padding: 12px 0 16px; border-bottom: 1px solid #e0e0e0; margin-bottom: 16px; }
  header h1 { margin: 0 0 4px; font-size: 1.4em; }
  header .meta { color: #666; font-size: 0.9em; }
  .legend { font-size: 0.85em; color: #555; margin-top: 6px; }
  .chunk { background: #fff; border: 1px solid #e0e0e0; border-left: 4px solid #4a90e2; border-radius: 4px; padding: 12px 14px; margin-bottom: 16px; }
  .chunk-header { font-weight: 600; color: #1f3a68; font-size: 1.05em; }
  .chunk-audio { color: #888; font-size: 0.88em; margin-bottom: 8px; }
  .segment { padding: 10px 0; border-top: 1px dashed #eee; }
  .segment:first-of-type { border-top: none; padding-top: 4px; }
  .segment-text { font-size: 1.02em; color: #111; margin-bottom: 8px; }
  .segment-text.ungrounded { color: #a00; }
  .badge { display: inline-block; background: #fde7e7; color: #a00; padding: 1px 6px; border-radius: 3px; font-size: 0.8em; margin-left: 6px; vertical-align: middle; }
  .badge.warn { background: #fff7d6; color: #8a6d00; }
  .refs { display: flex; flex-wrap: wrap; gap: 10px; }
  .ref-card { width: 220px; border: 1px solid #ddd; border-radius: 4px; overflow: hidden; background: #fafafa; cursor: pointer; }
  .ref-card:hover { border-color: #4a90e2; }
  .ref-card img { width: 100%; display: block; background: #eee; aspect-ratio: 16 / 9; object-fit: cover; }
  .ref-card .meta { font-size: 0.85em; padding: 4px 6px 2px; color: #333; font-family: SFMono-Regular, Consolas, "Liberation Mono", monospace; }
  .ref-card .summary { font-size: 0.78em; padding: 0 6px 6px; color: #666; max-height: 3.4em; overflow: hidden; }
  .ref-card .summary .chars { color: #4a90e2; font-style: italic; }
  .ref-card .summary .ocr { color: #8a6d00; }
  .missing { width: 220px; height: 124px; border: 1px dashed #ccc; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #999; font-size: 0.85em; background: #f5f5f5; }
  #toast { position: fixed; bottom: 16px; right: 16px; background: #1f3a68; color: #fff; padding: 8px 12px; border-radius: 4px; font-size: 0.9em; opacity: 0; transition: opacity 0.2s ease; pointer-events: none; }
  #toast.show { opacity: 1; }
"""


_JS = """
function copyTimestamp(ts) {
  navigator.clipboard.writeText(ts).then(function () {
    var t = document.getElementById('toast');
    t.textContent = 'Copied ' + ts;
    t.classList.add('show');
    setTimeout(function () { t.classList.remove('show'); }, 1200);
  });
}
"""


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def _fmt_time(seconds: float) -> str:
    return seconds_to_timestamp(max(0.0, float(seconds)))


def _thumb_filename(seg_id: str) -> str:
    return f"{seg_id.replace(':', '_')}.jpg"


def _normalize_text_html(text: str) -> str:
    return _esc(text).replace("\n", "<br>")


def render_cheatsheet_html(
    *,
    title: str,
    manifest: list[dict[str, Any]],
    shots: dict[str, ShotInfo],
    thumbnails_dir_name: str = "thumbnails",
    thumbnails_present: Optional[set[str]] = None,
) -> str:
    """Render the editor cheatsheet as a single HTML string.

    ``thumbnails_present`` is the set of seg_ids whose JPG actually exists
    on disk; refs not in this set render as a placeholder card so the
    cheatsheet still reads cleanly when thumbnails are missing.
    """
    if thumbnails_present is None:
        thumbnails_present = set(shots.keys())

    total_chunks = len(manifest)
    total_segments = sum(len(chunk.get("segments", [])) for chunk in manifest)
    ungrounded_segments = sum(
        1
        for chunk in manifest
        for seg in chunk.get("segments", [])
        if not seg.get("refs")
    )
    total_audio_s = manifest[-1].get("audio_end_s", 0.0) if manifest else 0.0

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN"><head><meta charset="utf-8">')
    parts.append(f"<title>Editor Cheatsheet — {_esc(title)}</title>")
    parts.append(f"<style>{_CSS}</style>")
    parts.append("</head><body>")

    parts.append("<header>")
    parts.append(f"<h1>Editor Cheatsheet — {_esc(title)}</h1>")
    parts.append(
        f'<div class="meta">{total_chunks} chunks · {total_segments} sentences · '
        f"{_fmt_time(total_audio_s)} total narration</div>"
    )
    if ungrounded_segments:
        parts.append(
            f'<div class="legend">⚠ {ungrounded_segments} sentence(s) have no '
            f"&lt;refs&gt; — the LLM did not ground them. Treat as red flags.</div>"
        )
    parts.append(
        '<div class="legend">Click any thumbnail to copy its source timestamp '
        "to the clipboard.</div>"
    )
    parts.append("</header>")

    for chunk in manifest:
        section = _esc(str(chunk.get("section", "")))
        audio_start = float(chunk.get("audio_start_s", 0.0))
        audio_end = float(chunk.get("audio_end_s", 0.0))
        parts.append('<div class="chunk">')
        parts.append(f'<div class="chunk-header">{section}</div>')
        parts.append(
            f'<div class="chunk-audio">narration {_fmt_time(audio_start)} '
            f"→ {_fmt_time(audio_end)} ({audio_end - audio_start:.1f}s)</div>"
        )

        for seg in chunk.get("segments", []):
            text = str(seg.get("text", "")).strip()
            refs = list(seg.get("refs") or [])
            unknown_refs = list(seg.get("unknown_refs") or [])
            is_ungrounded = not refs

            seg_class = "segment-text ungrounded" if is_ungrounded else "segment-text"
            parts.append('<div class="segment">')
            badge = ' <span class="badge">no footage hint</span>' if is_ungrounded else ""
            if unknown_refs:
                badge += (
                    f' <span class="badge warn">{len(unknown_refs)} unknown ref(s): '
                    f'{_esc(", ".join(unknown_refs[:3]))}</span>'
                )
            parts.append(
                f'<div class="{seg_class}">"{_normalize_text_html(text)}"{badge}</div>'
            )

            if refs:
                parts.append('<div class="refs">')
                for ref in refs:
                    shot = shots.get(ref)
                    has_thumb = ref in thumbnails_present
                    ts = _fmt_time(shot.start_s) if shot else ""
                    if shot is None:
                        parts.append(
                            f'<div class="missing">missing: {_esc(ref)}</div>'
                        )
                        continue
                    onclick = f"copyTimestamp('{_esc(ts)}')"
                    summary_html = _esc(shot.summary) if shot.summary else ""
                    ocr_html = (
                        f' <span class="ocr">📝 {_esc(shot.ocr_text)}</span>'
                        if shot.ocr_text
                        else ""
                    )
                    chars_html = (
                        f' <span class="chars">[{_esc(", ".join(shot.characters))}]</span>'
                        if shot.characters
                        else ""
                    )
                    img_or_placeholder = (
                        f'<img src="{thumbnails_dir_name}/{_thumb_filename(ref)}" '
                        f'alt="{_esc(ref)}" loading="lazy">'
                        if has_thumb
                        else '<div class="missing">no thumbnail</div>'
                    )
                    parts.append(
                        f'<div class="ref-card" onclick="{onclick}" title="Click to copy {_esc(ts)}">'
                        f"{img_or_placeholder}"
                        f'<div class="meta">{_esc(ref)} · {_fmt_time(shot.start_s)}'
                        f"–{_fmt_time(shot.end_s)}</div>"
                        f'<div class="summary">{summary_html}{ocr_html}{chars_html}</div>'
                        f"</div>"
                    )
                parts.append("</div>")
            parts.append("</div>")
        parts.append("</div>")

    parts.append('<div id="toast"></div>')
    parts.append(f"<script>{_JS}</script>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"Manifest is not a JSON array: {path}")
    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-cheatsheet",
        description="Stage 4: build the 剪映 editor cheatsheet (thumbnails + HTML).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Stage 3 voiceover_<style>.manifest.json with segments + refs.")
    parser.add_argument("--visual-segments", type=Path, required=True,
                        help="Stage 1 visual_segments.json (provides shot summaries + timestamps).")
    parser.add_argument("--video", type=Path, required=True,
                        help="Source movie path used to extract thumbnails.")
    parser.add_argument("--thumbnails-dir", type=Path, required=True,
                        help="Directory where per-shot thumbnails live (created if absent).")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output HTML cheatsheet path.")
    parser.add_argument("--title", default="",
                        help="Movie title shown in the cheatsheet header.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="Concurrent ffmpeg workers for thumbnail extraction.")
    parser.add_argument("--skip-thumbnails", action="store_true",
                        help="Skip thumbnail extraction (HTML still renders, missing thumbs show placeholders).")
    return parser


_REF_PATTERN = re.compile(r"^visual:\d+$")


def _collect_referenced_seg_ids(manifest: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for chunk in manifest:
        for seg in chunk.get("segments", []):
            for ref in seg.get("refs") or []:
                ref_str = str(ref)
                if _REF_PATTERN.match(ref_str):
                    ids.add(ref_str)
    return ids


def main(
    argv: Sequence[str] | None = None,
    *,
    run_cmd=subprocess.run,
) -> int:
    args = build_parser().parse_args(argv)
    manifest_path = args.manifest.expanduser().resolve()
    visual_segments_path = args.visual_segments.expanduser().resolve()
    video_path = args.video.expanduser().resolve()
    thumbnails_dir = args.thumbnails_dir.expanduser().resolve()
    out_path = args.out.expanduser().resolve()

    try:
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")
        if not visual_segments_path.exists():
            raise FileNotFoundError(f"Visual segments not found: {visual_segments_path}")
        if not args.skip_thumbnails and not video_path.exists():
            raise FileNotFoundError(f"Source video not found: {video_path}")

        manifest = load_manifest(manifest_path)
        visual_segments = load_visual_segments(visual_segments_path)
        shots = build_shot_index(visual_segments)
        referenced = _collect_referenced_seg_ids(manifest)
        referenced_shots = {seg_id: shots[seg_id] for seg_id in referenced if seg_id in shots}

        print(f"[cheatsheet] manifest chunks: {len(manifest)}")
        print(f"[cheatsheet] visual_segments: {len(visual_segments)} loaded")
        print(
            f"[cheatsheet] refs in manifest: {len(referenced)} unique "
            f"({len(referenced_shots)} resolved, {len(referenced) - len(referenced_shots)} unknown)"
        )

        thumbnails_present: set[str] = set()
        if not args.skip_thumbnails:
            decode_mode = "CUDA decode with CPU fallback" if cuda_decode_available() else "CPU"
            print(f"[cheatsheet] thumbnail decode: {decode_mode}")
            extracted, skipped, errors = extract_missing_thumbnails(
                video=video_path,
                shots=referenced_shots,
                thumbnails_dir=thumbnails_dir,
                workers=args.workers,
                run_cmd=run_cmd,
            )
            print(
                f"[cheatsheet] thumbnails: {extracted} extracted, {skipped} cached"
            )
            if errors:
                preview = "; ".join(errors[:3])
                more = f" (+{len(errors) - 3} more)" if len(errors) > 3 else ""
                print(
                    f"[cheatsheet] WARNING: {len(errors)} thumbnail(s) failed — {preview}{more}",
                    file=sys.stderr,
                )

        for seg_id in referenced_shots:
            if (thumbnails_dir / _thumb_filename(seg_id)).exists():
                thumbnails_present.add(seg_id)

        try:
            rel_thumbs = thumbnails_dir.relative_to(out_path.parent).as_posix()
        except ValueError:
            rel_thumbs = thumbnails_dir.as_posix()

        html_text = render_cheatsheet_html(
            title=args.title or video_path.stem,
            manifest=manifest,
            shots=shots,
            thumbnails_dir_name=rel_thumbs,
            thumbnails_present=thumbnails_present,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html_text, encoding="utf-8")
        print(f"[cheatsheet] wrote {out_path}")
        return 0
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
