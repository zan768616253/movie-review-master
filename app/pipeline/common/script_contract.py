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
        [ANCHOR id="chunk-024" ranges="00:23:10.000-00:23:18.000, 00:24:02.000-00:24:09.000" characters="Yuta|Rika"]

    Parsed into:
        AnchorMarker(
            id="chunk-024",
            ranges=[("00:23:10.000", "00:23:18.000"),
                    ("00:24:02.000", "00:24:09.000")],
            characters=["Yuta", "Rika"],
        )

    `id` is the stable handle the validator uses to refer back to a specific
    anchor in feedback messages. The planner is asked to emit `id="chunk-NNN"`
    on every anchor; if it doesn't, callers can use ``inject_missing_anchor_ids``
    to fill them in sequentially before validation runs.
    """

    ranges: list[tuple[str, str]]
    characters: list[str] = field(default_factory=list)
    raw: str | None = None
    id: str | None = None

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
        id=(attributes.get("id") or None),
    )


# Regex used by ``inject_missing_anchor_ids`` to locate `[ANCHOR ...]` lines
# from a script verbatim, so we can rewrite only the marker line and leave
# narration text byte-identical.
ANCHOR_LINE_RE = re.compile(r"^(\s*)\[ANCHOR\s+(.*?)\]\s*$")


def inject_missing_anchor_ids(text: str, prefix: str = "chunk-") -> tuple[str, int]:
    """Add ``id="chunk-NNN"`` to every anchor line that lacks one.

    Returns ``(new_text, injected_count)``. Existing ids are preserved
    untouched. Ids assigned to anchors that already have an id are NOT
    renumbered — only missing ones get filled in, sequenced from 1.

    The function rewrites whole `[ANCHOR ...]` lines but never touches the
    narration text below them, so it is safe to call before validation
    without disturbing the human-edited script body.
    """
    out_lines: list[str] = []
    next_index = 1
    used_ids: set[str] = set()
    # First pass — collect ids already present so we can avoid colliding
    # when we generate new ones.
    for line in text.splitlines():
        match = ANCHOR_LINE_RE.match(line)
        if not match:
            continue
        try:
            marker = parse_anchor_marker(line.strip())
        except ValueError:
            continue
        if marker is not None and marker.id:
            used_ids.add(marker.id)

    injected = 0
    for line in text.splitlines():
        match = ANCHOR_LINE_RE.match(line)
        if not match:
            out_lines.append(line)
            continue
        indent, body = match.group(1), match.group(2)
        try:
            marker = parse_anchor_marker(line.strip())
        except ValueError:
            # Malformed anchor — leave it for the validator to flag rather
            # than try to repair it here.
            out_lines.append(line)
            continue
        if marker is None or marker.id:
            out_lines.append(line)
            continue
        # Find the next unused chunk-NNN id.
        while True:
            candidate = f"{prefix}{next_index:03d}"
            next_index += 1
            if candidate not in used_ids:
                used_ids.add(candidate)
                break
        out_lines.append(f'{indent}[ANCHOR id="{candidate}" {body}]')
        injected += 1
    return "\n".join(out_lines) + ("\n" if text.endswith("\n") else ""), injected


# --- Style file reader ----------------------------------------------------

CHARS_PER_SECOND_RE = re.compile(r"chars_per_second\s*=\s*([\d.]+)")

# Real measured TTS speech rate for the pipeline's target voice
# (Qwen3-TTS Voice Clone on the Niu Shu base voice). Mean across 57 chunks
# of real JJK0 niu-shu output (2026-04-27): 6.74 ± 0.58 cps. This is the
# *truth-in-conversion* rate from Chinese chars to audio seconds — used
# for macro-budget computation (target_seconds × REAL_TTS_CPS = total
# chars to produce that many seconds of audio).
#
# This is intentionally distinct from the per-anchor `chars_per_second`
# in the style file, which is the planner's *writing cap* and must sit
# below this value so audio always fits inside its anchor's video. See
# styles/niu-shu.md TTS Budget paragraph for the rationale.
REAL_TTS_CPS = 6.74


def read_style_chars_per_second(style_path: Path, default: float = 5.0) -> float:
    """Read the planner CPS budget from a style markdown file.

    Looks for a `chars_per_second = N.N` token anywhere in the file (e.g.
    on the `**TTS Budget (planner authority):**` line in `niu-shu.md`).
    Returns `default` when the style file lacks that line, so callers can
    still operate on a generic budget.

    Example:
        >>> read_style_chars_per_second(Path("styles/niu-shu.md"))
        6.0
    """
    text = style_path.read_text(encoding="utf-8")
    match = CHARS_PER_SECOND_RE.search(text)
    if match:
        return float(match.group(1))
    return default


@dataclass(frozen=True)
class ReviewBudget:
    """Authoritative Stage 2 review-length budget derived from target_seconds."""

    target_seconds: float
    min_seconds: float
    max_seconds: float
    target_chars: int
    min_chars: int


def build_review_budget(target_seconds: float, chars_per_second: float) -> ReviewBudget:
    """Convert the movie config's target_seconds into Stage 2 macro budgets."""
    safe_target_seconds = max(1.0, float(target_seconds))
    target_chars = int(round(safe_target_seconds * chars_per_second))
    return ReviewBudget(
        target_seconds=safe_target_seconds,
        min_seconds=max(60.0, safe_target_seconds * 0.7),
        max_seconds=safe_target_seconds * 1.3,
        target_chars=target_chars,
        min_chars=int(round(target_chars * 0.85)),
    )


@dataclass(frozen=True)
class CoverageBudget:
    """Target window for total selected anchor coverage in Stage 2."""

    target_seconds: float
    min_seconds: float
    max_seconds: float


def build_coverage_budget(
    target_seconds: float,
    chars_per_second: float,
    *,
    macro_chars_per_second: float = REAL_TTS_CPS,
) -> CoverageBudget:
    """Derive a total anchor-coverage window from the review target + planner cap.

    Stage 2 needs enough selected source-video seconds to hold the narration
    it plans to write at the local per-anchor cap, but not so much that Stage 6
    must throw away huge portions of the chosen visual sequence.
    """
    review_budget = build_review_budget(target_seconds, macro_chars_per_second)
    safe_planner_cps = max(0.1, float(chars_per_second))
    coverage_target_seconds = max(
        review_budget.target_seconds,
        review_budget.target_chars / safe_planner_cps,
    )
    return CoverageBudget(
        target_seconds=coverage_target_seconds,
        min_seconds=max(review_budget.min_seconds, coverage_target_seconds * 0.85),
        max_seconds=max(review_budget.max_seconds, coverage_target_seconds * 1.20),
    )


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
# A single anchor range is expected to represent ONE source shot — a
# continuous beat in the editor's intended pacing. Most shots run 1-8s;
# the 12s cap accommodates long takes while catching planner typos in end
# timestamps (e.g. `00:29:53-01:00:00` where `00:30:00` was meant). Was
# 60s before the shot-aware overhaul; tightened to keep within-anchor
# audio-vs-video drift bounded by one shot length.
MAX_ANCHOR_RANGE_DURATION_S = 12.0

# Hard cap on an anchor's total duration (sum of its range durations).
# Beyond this the within-anchor drift between narration pace and source-
# editing pace can exceed ~3s, which becomes audibly out of sync. Pick a
# new anchor instead of widening an existing one.
MAX_ANCHOR_TOTAL_DURATION_S = 12.0

# A range "crosses a shot boundary" when an internal cut lies strictly
# inside (start, end). This tolerance is the float-safety margin around
# start/end that we forgive — anything within this distance of an edge is
# considered "at" the edge, not "inside" the range.
SHOT_BOUNDARY_TOLERANCE_S = 0.3


@dataclass
class AnchorValidation:
    """Per-anchor budget check result.

    `severity` is one of: ``"ok"`` (narration fits the budget),
    ``"warn"`` (over by ≤10%, Stage 5 can absorb it visually), or
    ``"fail"`` (over by >10%, requires manual rewrite — narration is
    sacred, the pipeline never trims it automatically).

    ``chunk_id`` is the stable handle from the anchor's ``id="..."``
    attribute. Falls back to ``"anchor-#N"`` when the planner did not emit
    an id; the validator's caller should normally inject ids via
    ``inject_missing_anchor_ids`` before validation so this fallback is rare.
    """

    index: int
    anchor: AnchorMarker
    narration_chars: int
    budget_chars: int
    overrun_ratio: float
    severity: str

    @property
    def chunk_id(self) -> str:
        return self.anchor.id or f"anchor-#{self.index}"


@dataclass
class StructureIssue:
    """A script-level problem that isn't tied to a single anchor's budget.

    ``chunk_id`` is set when the issue can be traced to a specific anchor
    (the common case), or None for script-level issues (missing TITLE,
    zero anchors, orphan narration).
    """

    severity: str  # "warn" or "fail"
    code: str
    message: str
    chunk_id: str | None = None


@dataclass
class ScriptValidation:
    """Aggregate result of validating a full anchored script.

    Reports per-anchor budget issues (`chunks`) AND script-level
    structural problems (`issues`) like missing TITLE, zero anchors,
    orphan narration, anchor non-monotonicity, or range provenance.
    """

    chunks: list[AnchorValidation]
    issues: list[StructureIssue] = field(default_factory=list)
    total_narration_chars: int = 0
    total_anchor_seconds: float = 0.0

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
    chunk_id: str | None = None,
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
        candidate = StructureIssue(
            severity=severity, code="range_provenance", message=msg, chunk_id=chunk_id,
        )
        if worst is None or (candidate.severity == "fail" and worst.severity != "fail"):
            worst = candidate
    return worst


# Sub-shots produced by Stage 0's scene-detect that are shorter than this
# threshold are treated as "false granularity" — micro-cuts inside what
# was editorially one continuous beat (rapid action, motion changes,
# camera shake). When ANY sub-shot of a Stage 0 segment falls below this
# bar after flicker-drop, the whole segment's inner cuts are collapsed:
# the shot menu emits one shot for the segment, and the validator's
# boundary set excludes the segment's `shot_boundaries_s`. This kills
# the "LLM merges 4 adjacent same-summary shots into one range" failure
# mode — those shots no longer appear separately. Long-shot segments
# (every sub-shot ≥ this threshold) are still split, because the LLM
# should be choosing among them at fine granularity.
COLLAPSE_INNER_CUTS_BELOW_S = 3.0


def should_collapse_segment_inner_cuts(
    segment: dict[str, object], min_subshot_s: float = 0.5
) -> bool:
    """Decide whether to merge a segment's inner shot boundaries.

    Returns True iff, after dropping flickers (sub-shots shorter than
    ``min_subshot_s``), any remaining sub-shot is still shorter than
    ``COLLAPSE_INNER_CUTS_BELOW_S``. In that case the segment is
    treated as one editorial beat throughout the pipeline:

    - ``split_segment_into_shots`` emits one shot for the whole segment
    - ``build_shot_boundary_set`` skips the segment's inner cuts

    Both consumers must apply the same rule, otherwise the prompt would
    show one shot but the validator would still reject ranges that
    cross the omitted cuts.
    """
    try:
        seg_start = timestamp_to_seconds(str(segment["start"]))
        seg_end = timestamp_to_seconds(str(segment["end"]))
    except (KeyError, ValueError):
        return False
    if seg_end <= seg_start:
        return False

    inner: list[float] = []
    for raw in segment.get("shot_boundaries_s") or ():  # type: ignore[union-attr]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if seg_start < value < seg_end:
            inner.append(value)
    if not inner:
        return False
    inner.sort()

    # Walk the cut points and drop flicker sub-shots first, mirroring
    # what split_segment_into_shots does. After flicker drop, check
    # whether any surviving sub-shot is still under the collapse bar.
    cut_points = [seg_start, *inner, seg_end]
    surviving: list[tuple[float, float]] = []
    for i in range(len(cut_points) - 1):
        a, b = cut_points[i], cut_points[i + 1]
        if b - a >= min_subshot_s:
            surviving.append((a, b))
    if not surviving:
        return False
    return any((b - a) < COLLAPSE_INNER_CUTS_BELOW_S for a, b in surviving)


def build_shot_boundary_set(
    visual_segments: list[dict[str, object]] | None,
) -> list[float]:
    """Collect every shot-boundary timestamp from Stage 0's visual segments.

    Stage 0 snaps each visual segment to ffmpeg-detected shot cuts and also
    annotates each segment with `shot_boundaries_s` — the cut times that
    fall strictly inside the (snapped) segment. The full set of "places
    where a shot cut happens" is therefore:

    - every visual segment's start timestamp (excluding the very first one
      at t=0, which is the movie start, not a cut)
    - every visual segment's end timestamp
    - every entry in any segment's `shot_boundaries_s` list — UNLESS the
      segment qualifies for inner-cut collapse (see
      ``should_collapse_segment_inner_cuts``); in that case the inner
      cuts are omitted so the validator and the prompt agree on the
      effective shot granularity.

    Returns sorted, deduplicated absolute seconds. The validator uses this
    set to reject anchor ranges that cross a cut: if any boundary B falls
    strictly inside (start, end) — outside a small tolerance window — the
    range bridges two shots and the audience will perceive a hard cut
    inside what was supposed to be one continuous beat.
    """
    if not visual_segments:
        return []

    boundaries: set[float] = set()
    for segment in visual_segments:
        try:
            start_s = timestamp_to_seconds(str(segment["start"]))
            end_s = timestamp_to_seconds(str(segment["end"]))
        except (KeyError, ValueError):
            continue
        if start_s > 0.001:
            boundaries.add(round(start_s, 3))
        boundaries.add(round(end_s, 3))
        if should_collapse_segment_inner_cuts(segment):
            continue
        for raw in segment.get("shot_boundaries_s") or ():  # type: ignore[union-attr]
            try:
                boundaries.add(round(float(raw), 3))
            except (TypeError, ValueError):
                continue
    return sorted(boundaries)


def _check_range_shot_alignment(
    anchor: AnchorMarker,
    shot_boundaries: list[float] | None,
    tolerance_s: float = SHOT_BOUNDARY_TOLERANCE_S,
    chunk_id: str | None = None,
) -> list[StructureIssue]:
    """Reject anchor ranges that span a source-movie shot cut.

    A range with one boundary strictly inside (start + tol, end - tol)
    contains a hard cut from one shot to another. The narration over that
    range is one continuous sentence, but the visual jumps mid-beat —
    exactly the within-anchor drift the shot-aware contract was added to
    prevent. The remedy is to split the offending range into two anchors,
    or to use a multi-range anchor with each range bounded by one shot.

    Returns a StructureIssue per offending range. Returns an empty list
    when `shot_boundaries` is None (caller has no Stage 0 data).
    """
    if shot_boundaries is None:
        return []
    issues: list[StructureIssue] = []
    for start_ts, end_ts in anchor.ranges:
        start_s = timestamp_to_seconds(start_ts)
        end_s = timestamp_to_seconds(end_ts)
        for boundary in shot_boundaries:
            if start_s + tolerance_s < boundary < end_s - tolerance_s:
                issues.append(
                    StructureIssue(
                        severity="fail",
                        code="range_shot_crossing",
                        message=(
                            f"anchor range {start_ts}-{end_ts} crosses a shot "
                            f"boundary at {seconds_to_timestamp(boundary)}; "
                            f"split it into two anchors or use a multi-range "
                            f"anchor with each range bounded by one shot"
                        ),
                        chunk_id=chunk_id,
                    )
                )
                break
    return issues


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
    shot_boundaries: list[float] | None = None,
    target_seconds: float | None = None,
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
        - anchor.total_seconds > MAX_ANCHOR_TOTAL_
          DURATION_S                                → fail (anchor_too_long)

    Optional check (only when ``timeline_intervals`` is provided):
        - anchor range doesn't overlap any real
          SRT/visual entry                          → warn (≤1s) or fail (>5s)

    Optional check (only when ``shot_boundaries`` is provided):
        - anchor range crosses a shot cut          → fail (range_shot_crossing)
          The shot-aware contract: each range must stay inside one source
          shot so the narration can never describe a beat the audience
          isn't yet seeing.

    Optional macro checks (only when ``target_seconds`` is provided):
        - total spoken narration below the movie
          config floor                             → fail (script_too_short)
        - total selected anchor coverage below
          the movie config floor                   → fail (anchor_coverage_short)
        - total selected anchor coverage above
          the planner-support ceiling              → fail (anchor_coverage_long)

    Closing chunks (text after `[CLOSING]` with no anchor) are skipped for
    the per-anchor budget check but DO count toward the script-level spoken
    total. Narration before the [CLOSING] marker still triggers
    orphan_narration when it appears outside an anchor.

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
    closing_narration_chars = 0

    def flush() -> None:
        nonlocal current_anchor, current_narration
        if current_anchor is not None:
            narration = "".join(current_narration).strip()
            narration_chars = len(narration)
            budget_chars_f = current_anchor.total_seconds * chars_per_second
            ratio = narration_chars / budget_chars_f if budget_chars_f > 0 else float("inf")
            validation = AnchorValidation(
                index=len(chunks) + 1,
                anchor=current_anchor,
                narration_chars=narration_chars,
                budget_chars=int(round(budget_chars_f)),
                overrun_ratio=ratio,
                severity=_grade_overrun(ratio),
            )
            chunks.append(validation)
            provenance = _check_range_provenance(
                current_anchor, timeline_intervals, chunk_id=validation.chunk_id,
            )
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
            # Stable handle for every issue tied to this anchor. The harness
            # is expected to call ``inject_missing_anchor_ids`` before
            # validation, so anchor.id is normally set; the "anchor-#N"
            # fallback exists for direct callers (e.g. unit tests) that
            # don't bother with ids.
            current_chunk_id = anchor.id or f"anchor-#{len(chunks) + 1}"

            # Reject any single range that's grossly too long. Provenance
            # alone can't catch this — a 30-min range still "overlaps"
            # plenty of real timeline entries — so duration is a separate
            # check on the policy layer.
            for start_ts, end_ts in anchor.ranges:
                duration_s = timestamp_to_seconds(end_ts) - timestamp_to_seconds(start_ts)
                if duration_s > MAX_ANCHOR_RANGE_DURATION_S:
                    issues.append(StructureIssue(
                        severity="fail",
                        code="range_too_long",
                        message=(
                            f"anchor range {start_ts}-{end_ts} spans {duration_s:.1f}s "
                            f"(cap is {MAX_ANCHOR_RANGE_DURATION_S:.0f}s); "
                            f"split long beats into multiple short ranges"
                        ),
                        chunk_id=current_chunk_id,
                    ))

            # Reject anchors whose total duration exceeds the cap. This is
            # the macro analogue of range_too_long: it bounds the worst-case
            # within-anchor drift between narration pace and source-edit
            # pace. Multi-range anchors covering more than ~12s should be
            # split into two narrative beats.
            if anchor.total_seconds > MAX_ANCHOR_TOTAL_DURATION_S:
                issues.append(StructureIssue(
                    severity="fail",
                    code="anchor_too_long",
                    message=(
                        f"anchor total duration {anchor.total_seconds:.1f}s exceeds the "
                        f"{MAX_ANCHOR_TOTAL_DURATION_S:.0f}s cap; split into two anchors "
                        f"so within-anchor sync drift stays bounded"
                    ),
                    chunk_id=current_chunk_id,
                ))

            # Shot-aware check: each range must stay inside ONE source shot.
            # Stage 0 emits shot boundaries; a range that contains a boundary
            # strictly inside its window will play a hard cut mid-narration.
            issues.extend(_check_range_shot_alignment(
                anchor, shot_boundaries, chunk_id=current_chunk_id,
            ))

            # Monotonicity: each new anchor's first range starts at or
            # after the previous anchor's first range — UNLESS the planner
            # is deliberately cross-cutting between two parallel
            # storylines (a standard niu-shu device, signaled in narration
            # by `另一边` / `与此同时`). The pipeline plays anchors in
            # script order regardless of timestamp, so a cross-cut works
            # downstream; only narrative quality is at stake. Emit as a
            # `warn` so the planner sees the jump but is not blocked —
            # genuine planner scrambling is rare and the user can decide
            # case-by-case from the warning output.
            first_start_s = timestamp_to_seconds(anchor.ranges[0][0])
            if last_anchor_first_start_s is not None and first_start_s < last_anchor_first_start_s:
                issues.append(StructureIssue(
                    severity="warn",
                    code="non_monotonic",
                    message=(
                        f"anchor {current_chunk_id} starts at {anchor.ranges[0][0]} "
                        f"which is earlier than the previous anchor's start "
                        f"(intentional cross-cut? if not, reorder)"
                    ),
                    chunk_id=current_chunk_id,
                ))
            last_anchor_first_start_s = first_start_s
            continue

        if in_closing:
            # Closing narration plays over a still keyframe, so it skips the
            # per-anchor budget check. It still counts toward the total spoken
            # runtime because Stage 3 voices it into the final mp3.
            closing_narration_chars += len(line)
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

    total_anchor_seconds = sum(chunk.anchor.total_seconds for chunk in chunks)
    total_narration_chars = sum(chunk.narration_chars for chunk in chunks) + closing_narration_chars

    if target_seconds is not None and chunks:
        # Macro budget uses real TTS speech rate, not the per-anchor writing
        # cap. The script-too-short check needs to know how many chars are
        # required to produce `target_seconds` of audio, which is governed by
        # how fast TTS reads the text — not by what the planner is allowed
        # to write per anchor.
        review_budget = build_review_budget(target_seconds, REAL_TTS_CPS)
        coverage_budget = build_coverage_budget(target_seconds, chars_per_second)
        if total_narration_chars < review_budget.min_chars:
            issues.append(StructureIssue(
                severity="fail",
                code="script_too_short",
                message=(
                    f"total spoken narration is {total_narration_chars} chars, below the "
                    f"minimum {review_budget.min_chars} chars for a "
                    f"{review_budget.target_seconds:.0f}s target"
                ),
            ))
        if total_anchor_seconds < coverage_budget.min_seconds:
            issues.append(StructureIssue(
                severity="fail",
                code="anchor_coverage_short",
                message=(
                    f"selected anchor coverage is {total_anchor_seconds:.1f}s, below the "
                    f"minimum {coverage_budget.min_seconds:.1f}s needed to support a "
                    f"{review_budget.target_seconds:.0f}s target at "
                    f"{chars_per_second:g} chars/s"
                ),
            ))
        if total_anchor_seconds > coverage_budget.max_seconds:
            issues.append(StructureIssue(
                severity="fail",
                code="anchor_coverage_long",
                message=(
                    f"selected anchor coverage is {total_anchor_seconds:.1f}s, above the "
                    f"maximum {coverage_budget.max_seconds:.1f}s allowed for a "
                    f"{review_budget.target_seconds:.0f}s target at "
                    f"{chars_per_second:g} chars/s"
                ),
            ))

    return ScriptValidation(
        chunks=chunks,
        issues=issues,
        total_narration_chars=total_narration_chars,
        total_anchor_seconds=total_anchor_seconds,
    )


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
