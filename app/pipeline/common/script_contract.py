from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from app.pipeline.common.json_io import load_json


# Anchor schema:
# `[ANCHOR ranges="HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS" characters="A|B"]`
# Ranges are chronological and non-overlapping; the planner-writer
# guarantees narration fits inside the total range duration. See
# docs/OVERHAUL_PLAN.md §4 for the full data contract.

# Time-range and structural-marker regexes used by the parser below.
RANGE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)\s*-\s*(\d{2}:\d{2}:\d{2}(?:[.,]\d{1,3})?)"
)
STRUCTURAL_MARKER_RE = re.compile(r"^\s*\[(TITLE|HOOK|ACT\s*\d+[^\]]*|CLOSING)\]")


def normalize_timestamp(ts: str | None) -> str | None:
    if ts is None:
        return None
    return ts.replace(",", ".")


def timestamp_to_seconds(ts: str) -> float:
    normalized_ts = normalize_timestamp(ts)
    if normalized_ts is None:
        raise ValueError("Timestamp cannot be None")
    parts = normalized_ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(normalized_ts)


def seconds_to_timestamp(seconds: float) -> str:
    safe_seconds = max(0.0, seconds)
    hours = int(safe_seconds // 3600)
    minutes = int((safe_seconds % 3600) // 60)
    secs = safe_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def split_packed_list(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return []
    return [item.strip() for item in raw.split("|") if item.strip()]


# --- New anchor marker (Stage 2 overhaul) ---------------------------------

@dataclass
class AnchorMarker:
    """One `[ANCHOR ...]` block from the planner-writer output.

    Example line:
        [ANCHOR ranges="00:23:10.000-00:23:18.000, 00:24:02.000-00:24:09.000" characters="Yuta|Rika"]

    Parsed into:
        AnchorMarker(
            ranges=[("00:23:10.000", "00:23:18.000"),
                    ("00:24:02.000", "00:24:09.000")],
            characters=["Yuta", "Rika"],
        )
    """

    ranges: list[tuple[str, str]]
    characters: list[str] = field(default_factory=list)
    raw: str | None = None

    @property
    def total_seconds(self) -> float:
        return sum(
            timestamp_to_seconds(end) - timestamp_to_seconds(start)
            for start, end in self.ranges
        )


def parse_range_list(text: str) -> list[tuple[str, str]]:
    """Parse the `ranges="..."` attribute payload.

    Accepts comma- or whitespace-separated pairs of `HH:MM:SS[.mmm]-HH:MM:SS[.mmm]`.
    Example: `"00:01:00-00:01:05, 00:02:00-00:02:10"` →
    `[("00:01:00", "00:01:05"), ("00:02:00", "00:02:10")]`.
    """
    ranges: list[tuple[str, str]] = []
    for match in RANGE_RE.finditer(text):
        start = normalize_timestamp(match.group(1))
        end = normalize_timestamp(match.group(2))
        if start is not None and end is not None:
            ranges.append((start, end))
    return ranges


def parse_anchor_marker(line: str) -> AnchorMarker | None:
    """Parse a single `[ANCHOR ...]` line.

    Returns None when `line` is not an anchor marker. Raises ValueError when
    `line` *looks* like an anchor but is structurally invalid (missing
    `ranges`, empty range list, non-chronological, overlapping, or any range
    with end <= start). This way callers can `continue` on None and fail
    loudly on malformed input.
    """
    stripped = line.strip()
    if not stripped.startswith("[ANCHOR ") or not stripped.endswith("]"):
        return None

    inner = stripped[len("[ANCHOR ") : -1].strip()
    if not inner:
        raise ValueError(f"Empty anchor marker: {stripped!r}")

    attributes: dict[str, str] = {}
    for token in shlex.split(inner):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        attributes[key.strip().lower()] = value.strip()

    ranges_attr = attributes.get("ranges")
    if not ranges_attr:
        raise ValueError(f"Anchor marker missing required `ranges=`: {stripped!r}")

    ranges = parse_range_list(ranges_attr)
    if not ranges:
        raise ValueError(f"Anchor marker `ranges=` parsed to zero ranges: {stripped!r}")

    # First reject any range with non-positive duration — that's a typo, not
    # an ordering question.
    for start_ts, end_ts in ranges:
        if timestamp_to_seconds(end_ts) <= timestamp_to_seconds(start_ts):
            raise ValueError(
                f"Anchor range has non-positive duration ({start_ts} → {end_ts}): {stripped!r}"
            )

    # Within one anchor, ranges play back-to-back as a single beat, so the
    # audience sees forward-time playback regardless of how the planner
    # ordered them. Sort by start time so semantically-ordered planner output
    # ("death-shot, then haunting-shot") is normalized to source-time
    # playback. Overlap is still a real bug (replayed footage) and is rejected
    # after sorting.
    ranges.sort(key=lambda r: timestamp_to_seconds(r[0]))
    prev_end_s: float | None = None
    for start_ts, end_ts in ranges:
        start_s = timestamp_to_seconds(start_ts)
        end_s = timestamp_to_seconds(end_ts)
        if prev_end_s is not None and start_s < prev_end_s:
            raise ValueError(
                f"Anchor ranges overlap near {start_ts}: {stripped!r}"
            )
        prev_end_s = end_s

    return AnchorMarker(
        ranges=ranges,
        characters=split_packed_list(attributes.get("characters")),
        raw=stripped,
    )


# --- Style file reader ----------------------------------------------------

CHARS_PER_SECOND_RE = re.compile(r"chars_per_second\s*=\s*([\d.]+)")


def read_style_chars_per_second(style_path: Path, default: float = 5.0) -> float:
    """Read the planner CPS budget from a style markdown file.

    Looks for a `chars_per_second = N.N` token anywhere in the file (e.g.
    on the `**TTS Budget (planner authority):**` line in `niu-shu.md`).
    Returns `default` when the style file lacks that line, so callers can
    still operate on a generic budget.

    Example:
        >>> read_style_chars_per_second(Path("styles/niu-shu.md"))
        5.0
    """
    text = style_path.read_text(encoding="utf-8")
    match = CHARS_PER_SECOND_RE.search(text)
    if match:
        return float(match.group(1))
    return default


# --- Anchored-script validator (Phase 2 of the overhaul) ------------------

# An anchor's narration is allowed to overrun its computed character budget
# by up to this fraction without rejection. The 10% slack covers TTS speed
# variance; Stage 5 absorbs the resulting audio overrun via post-handle
# extension and, only if needed, a final still fill.
NARRATION_WARN_OVERRUN = 0.10
# Float-safety epsilon for boundary comparisons (e.g. ratio = 1.10 should
# round to "warn" not "fail" even when arithmetic produces 1.10000000001).
RATIO_EPSILON = 1e-9
# Range-provenance tolerances. An anchor range must overlap a real timeline
# entry (SRT line or visual segment) within these tolerances; otherwise we
# flag it (warn for near-miss, fail for fabricated).
RANGE_PROVENANCE_WARN_S = 1.0
RANGE_PROVENANCE_FAIL_S = 5.0


@dataclass
class AnchorValidation:
    """Per-anchor budget check result.

    `severity` is one of: ``"ok"`` (narration fits the budget),
    ``"warn"`` (over by ≤10%, Stage 5 can absorb it visually), or
    ``"fail"`` (over by >10%, requires manual rewrite — narration is
    sacred, the pipeline never trims it automatically).
    """

    index: int
    anchor: AnchorMarker
    narration_chars: int
    budget_chars: int
    overrun_ratio: float
    severity: str


@dataclass
class StructureIssue:
    """A script-level problem that isn't tied to a single anchor's budget."""

    severity: str  # "warn" or "fail"
    code: str
    message: str


@dataclass
class ScriptValidation:
    """Aggregate result of validating a full anchored script.

    Reports per-anchor budget issues (`chunks`) AND script-level
    structural problems (`issues`) like missing TITLE, zero anchors,
    orphan narration, anchor non-monotonicity, or range provenance.
    """

    chunks: list[AnchorValidation]
    issues: list[StructureIssue] = field(default_factory=list)

    @property
    def has_failures(self) -> bool:
        return any(c.severity == "fail" for c in self.chunks) or any(
            i.severity == "fail" for i in self.issues
        )

    @property
    def has_warnings(self) -> bool:
        return any(c.severity == "warn" for c in self.chunks) or any(
            i.severity == "warn" for i in self.issues
        )

    def failures(self) -> list[AnchorValidation]:
        return [c for c in self.chunks if c.severity == "fail"]

    def fail_issues(self) -> list[StructureIssue]:
        return [i for i in self.issues if i.severity == "fail"]


def _grade_overrun(ratio: float) -> str:
    """Classify a narration overrun ratio with float-safe boundaries.

    Example: ratio = 1.10000000001 (a true 1.10 corrupted by FP rounding)
    grades as ``"warn"``, not ``"fail"``.
    """
    if ratio <= 1.0 + RATIO_EPSILON:
        return "ok"
    if ratio <= 1.0 + NARRATION_WARN_OVERRUN + RATIO_EPSILON:
        return "warn"
    return "fail"


def _check_range_provenance(
    anchor: AnchorMarker,
    timeline_intervals: list[tuple[float, float]] | None,
) -> StructureIssue | None:
    """Verify each anchor range overlaps a real SRT/visual timeline entry.

    Returns the strictest issue found across the anchor's ranges, or None
    when timeline data was not supplied (caller chose to skip provenance).

    Tolerance: a range is "ok" if it overlaps any timeline interval, "warn"
    if its midpoint is within 1s of an interval edge but doesn't overlap,
    "fail" otherwise — within 5s a near-miss, beyond 5s likely fabricated.
    """
    if timeline_intervals is None:
        return None

    worst: StructureIssue | None = None
    for start_ts, end_ts in anchor.ranges:
        start_s = timestamp_to_seconds(start_ts)
        end_s = timestamp_to_seconds(end_ts)
        # Closest distance from the range to any timeline interval, where
        # 0 means overlap. We measure the gap as max(0, span_a_start - span_b_end).
        best_gap = float("inf")
        for ts_start, ts_end in timeline_intervals:
            if start_s <= ts_end and ts_start <= end_s:
                best_gap = 0.0
                break
            gap = max(start_s - ts_end, ts_start - end_s)
            best_gap = min(best_gap, gap)

        if best_gap == 0.0:
            continue
        if best_gap <= RANGE_PROVENANCE_WARN_S:
            severity = "warn"
        elif best_gap <= RANGE_PROVENANCE_FAIL_S:
            severity = "fail"
        else:
            severity = "fail"

        msg = (
            f"anchor range {start_ts}-{end_ts} does not overlap any "
            f"timeline entry (closest gap {best_gap:.2f}s)"
        )
        candidate = StructureIssue(severity=severity, code="range_provenance", message=msg)
        if worst is None or (candidate.severity == "fail" and worst.severity != "fail"):
            worst = candidate
    return worst


def build_timeline_intervals(
    subtitle_intervals: list[tuple[float, float]] | None = None,
    visual_segments: list[dict[str, object]] | None = None,
) -> list[tuple[float, float]]:
    """Collect (start_s, end_s) pairs from SRT lines and visual segments.

    The result is the universe of timestamps the planner should be choosing
    from. Anchor ranges are checked against this universe by
    `validate_anchored_script` to detect hallucinated timestamps.
    """
    intervals: list[tuple[float, float]] = []
    if subtitle_intervals:
        intervals.extend(subtitle_intervals)
    for segment in visual_segments or ():
        try:
            start_s = timestamp_to_seconds(str(segment["start"]))
            end_s = timestamp_to_seconds(str(segment["end"]))
        except (KeyError, ValueError):
            continue
        if end_s > start_s:
            intervals.append((start_s, end_s))
    return intervals


def validate_anchored_script(
    text: str,
    chars_per_second: float,
    timeline_intervals: list[tuple[float, float]] | None = None,
) -> ScriptValidation:
    """Walk an anchored script and report per-anchor budgets + structure issues.

    Per-anchor:
        budget_chars = anchor.total_seconds * chars_per_second
        ratio        = narration_chars / budget_chars
        severity     = ok ≤1.0 < warn ≤1.10 < fail

    Script-level checks (always run):
        - missing [TITLE]                         → fail (no_title)
        - zero anchors                             → fail (no_anchors)
        - narration text outside any [ANCHOR] /
          [CLOSING] block                          → fail (orphan_narration)
        - anchors not chronologically ordered      → fail (non_monotonic)

    Optional check (only when ``timeline_intervals`` is provided):
        - anchor range doesn't overlap any real
          SRT/visual entry                          → warn (≤1s) or fail (>5s)

    Closing chunks (text after `[CLOSING]` with no anchor) are skipped for
    the budget check but DO trigger orphan_narration if encountered before
    the [CLOSING] marker.

    Example anchored-script fragment::

        [ANCHOR ranges="00:00:10-00:00:20"]
        narration text 50 chars  → budget = 10 × 5.0 = 50 → ratio 1.0 → ok
    """

    chunks: list[AnchorValidation] = []
    issues: list[StructureIssue] = []

    current_anchor: AnchorMarker | None = None
    current_narration: list[str] = []
    in_script = False
    in_closing = False
    in_bad_anchor = False
    saw_title = False
    last_anchor_first_start_s: float | None = None

    def flush() -> None:
        nonlocal current_anchor, current_narration
        if current_anchor is not None:
            narration = "".join(current_narration).strip()
            narration_chars = len(narration)
            budget_chars_f = current_anchor.total_seconds * chars_per_second
            ratio = narration_chars / budget_chars_f if budget_chars_f > 0 else float("inf")
            chunks.append(AnchorValidation(
                index=len(chunks) + 1,
                anchor=current_anchor,
                narration_chars=narration_chars,
                budget_chars=int(round(budget_chars_f)),
                overrun_ratio=ratio,
                severity=_grade_overrun(ratio),
            ))
            provenance = _check_range_provenance(current_anchor, timeline_intervals)
            if provenance is not None:
                issues.append(provenance)
        current_anchor = None
        current_narration = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("[TITLE]"):
            in_script = True
            saw_title = True
            continue

        if not in_script:
            continue

        if line.startswith("[CLOSING]"):
            flush()
            in_closing = True
            in_bad_anchor = False
            # New section → drop the monotonic baseline. CLOSING may
            # callback to an early shot without being flagged.
            last_anchor_first_start_s = None
            continue

        if STRUCTURAL_MARKER_RE.match(line):
            flush()
            in_closing = False
            in_bad_anchor = False
            # New section ([HOOK] or [ACT N]) → drop the monotonic baseline.
            # Each named section is its own coherent micro-narrative; jumps
            # across sections (notably HOOK→ACT 1) are part of the niu-shu
            # storytelling pattern, not a bug.
            last_anchor_first_start_s = None
            continue

        try:
            anchor = parse_anchor_marker(line)
        except ValueError as exc:
            # Malformed anchor: report it but keep validating the rest of the
            # script so the user sees every issue in one pass instead of
            # one-at-a-time crashes.
            flush()
            issues.append(StructureIssue(
                severity="fail",
                code="bad_anchor",
                message=str(exc),
            ))
            in_closing = False
            in_bad_anchor = True
            continue

        if anchor is not None:
            flush()
            current_anchor = anchor
            in_closing = False
            in_bad_anchor = False

            # Monotonicity: each new anchor's first range must start at or
            # after the previous anchor's first range. Strictly increasing
            # is too tight — back-to-back beats from the same scene get a
            # legitimate equality.
            first_start_s = timestamp_to_seconds(anchor.ranges[0][0])
            if last_anchor_first_start_s is not None and first_start_s < last_anchor_first_start_s:
                issues.append(StructureIssue(
                    severity="fail",
                    code="non_monotonic",
                    message=(
                        f"anchor #{len(chunks) + 1} starts at {anchor.ranges[0][0]} "
                        f"which is earlier than the previous anchor's start"
                    ),
                ))
            last_anchor_first_start_s = first_start_s
            continue

        if in_closing:
            # Closing narration plays over a still keyframe — no budget check.
            continue

        if in_bad_anchor:
            # Narration belongs to an anchor we already reported as malformed;
            # don't double-flag it as orphan.
            continue

        if current_anchor is not None:
            current_narration.append(line)
        else:
            # Free narration outside any anchor / closing — Stage 3 will
            # silently drop this. Always a fail.
            issues.append(StructureIssue(
                severity="fail",
                code="orphan_narration",
                message=f"narration text appears with no preceding [ANCHOR]: {line[:80]!r}",
            ))

    flush()

    if not saw_title:
        issues.append(StructureIssue(
            severity="fail",
            code="no_title",
            message="script is missing the [TITLE] marker",
        ))
    if not chunks:
        issues.append(StructureIssue(
            severity="fail",
            code="no_anchors",
            message="script contains zero [ANCHOR] blocks",
        ))

    return ScriptValidation(chunks=chunks, issues=issues)


def load_visual_segments(path: Path | None) -> list[dict[str, object]]:
    if path is None or not path.exists():
        return []
    segments: list[dict[str, object]] = load_json(path)
    for index, segment in enumerate(segments, 1):
        segment.setdefault("id", f"visual:{index:03d}")
    return segments


# Upper bound for a single visual segment. The VLM is instructed to emit
# event-based segments capped at 12s; anything beyond this safety margin is
# almost always a hallucinated end timestamp (we have seen Gemini return
# 9-hour segments on a 2-hour movie).
MAX_VISUAL_SEGMENT_DURATION_S = 30.0


@dataclass
class VisualSegmentDiagnostics:
    kept: int = 0
    dropped_bad_range: int = 0
    dropped_past_eof: int = 0
    dropped_too_long: int = 0
    clamped_to_eof: int = 0

    def as_summary(self) -> str:
        return (
            f"kept={self.kept} "
            f"clamped_to_eof={self.clamped_to_eof} "
            f"dropped_bad_range={self.dropped_bad_range} "
            f"dropped_past_eof={self.dropped_past_eof} "
            f"dropped_too_long={self.dropped_too_long}"
        )


def validate_visual_segments(
    segments: list[dict[str, object]],
    video_duration_s: float,    
) -> tuple[list[dict[str, object]], VisualSegmentDiagnostics]:
    """Clamp and filter visual segments against the real video duration.

    VLMs routinely return timestamps that exceed the video length or span
    implausible ranges. This function is the single gate every downstream
    stage trusts: anything it returns is guaranteed to be inside
    [0, video_duration_s] and no longer than max_segment_duration_s.
    """
    diagnostics = VisualSegmentDiagnostics()
    validated: list[dict[str, object]] = []

    for segment in segments:
        try:
            start_s = timestamp_to_seconds(str(segment["start"]))
            end_s = timestamp_to_seconds(str(segment["end"]))
        except (KeyError, ValueError):
            diagnostics.dropped_bad_range += 1
            continue

        if end_s <= start_s:
            diagnostics.dropped_bad_range += 1
            continue

        if start_s >= video_duration_s:
            diagnostics.dropped_past_eof += 1
            continue

        if end_s > video_duration_s:
            end_s = video_duration_s
            segment = dict(segment)
            segment["end"] = seconds_to_timestamp(end_s)
            diagnostics.clamped_to_eof += 1

        if (end_s - start_s) > MAX_VISUAL_SEGMENT_DURATION_S:
            diagnostics.dropped_too_long += 1
            continue

        diagnostics.kept += 1
        validated.append(segment)

    return validated, diagnostics


def probe_media_duration(media_path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    output = result.stdout.strip()
    if not output:
        return None

    try:
        return float(output)
    except ValueError:
        return None


def get_video_duration(video_path: Path) -> float:
    duration = probe_media_duration(video_path)
    if duration is None:
        raise RuntimeError(f"Unable to determine media duration for {video_path}")
    return duration