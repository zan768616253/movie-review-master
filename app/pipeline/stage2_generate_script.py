"""Stage 2: planner-writer prompt assembler (single pass).

Replaces the old writer + grounder two-pass design. One LLM call now picks
visual anchors AND writes narration that fits inside those anchors.
Narration character count is bounded by ``sum(range_seconds) * chars_per_second``
so audio always fits the visual budget. Stage 5 trims excess video shot-aware.

Manual flow stays the same shape:

    1. Run ``stage2-generate-script`` to print the planner prompt to stdout.
    2. Paste the prompt into your LLM (Gemini 2.5 Pro recommended).
    3. Paste the LLM reply into ``anchored_script.txt``.
    4. ``validate_anchored_script`` (in ``script_contract``) checks budgets.

See ``docs/OVERHAUL_PLAN.md`` §3, §4 for the architecture rationale.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.pipeline.common.script_contract import (
    MAX_ANCHOR_RANGE_DURATION_S,
    MAX_ANCHOR_TOTAL_DURATION_S,
    REAL_TTS_CPS,
    build_coverage_budget,
    build_review_budget,
    load_visual_segments,
    read_style_chars_per_second,
    seconds_to_timestamp,
    should_collapse_segment_inner_cuts,
    timestamp_to_seconds,
)
from app.pipeline.stage1_parse_subtitles import parse_subtitles


# Sub-shots shorter than this are visual flickers, not real beats. Stage 0
# scene-detect occasionally produces tight clusters of boundaries on flash
# frames or quick whip-pans; collapsing those keeps the [shot:NNN] timeline
# free of unselectable 0.1s entries.
MIN_SHOT_DURATION_S = 0.5


PLANNER_ROLE = (
    "You are the planner-writer for a Chinese movie-review pipeline. You pick "
    "visual anchors from the source movie AND write narration in the target "
    "style — both in one pass. Your output is the final script; there is no "
    "second editor."
)
DEFAULT_GENRE = "general"
DEFAULT_TARGET_SECONDS = 540.0  # 9 min. Hint only; the planner is allowed to flex ±30%.


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def get_segment_characters(segment: dict[str, object]) -> list[str]:
    raw_characters = segment.get("characters")
    if not isinstance(raw_characters, list):
        return []
    return [character for character in raw_characters if isinstance(character, str)]


def infer_movie_title(subtitle_srt_path: Path, explicit_title: str | None) -> str:
    return explicit_title or subtitle_srt_path.stem


def split_segment_into_shots(
    segment: dict[str, object],
) -> list[tuple[float, float]]:
    """Split one Stage 0 visual segment into its constituent source shots.

    Stage 0 emits each segment with a `shot_boundaries_s` list — the cuts
    that fall strictly inside the segment's window. The segment's own
    `start` and `end` are themselves shot boundaries (they were snapped
    there by Stage 0). Combining the three gives the full set of cuts
    inside the segment, which we expand into back-to-back sub-shots.

    Empty `shot_boundaries_s` ⇒ the whole segment is one shot. A segment
    with two inner cuts ⇒ three sub-shots.

    Sub-shots shorter than `MIN_SHOT_DURATION_S` are dropped — those are
    flicker frames the planner cannot use as a meaningful range.

    Inner-cut collapse: if any surviving sub-shot is still shorter than
    ``COLLAPSE_INNER_CUTS_BELOW_S``, all inner cuts are dropped and the
    whole segment is emitted as one shot. This treats rapid editorial
    cuts inside one continuous beat as the single editorial unit they
    are, which prevents the LLM from producing single-range anchors
    that span 3-4 micro-cuts (the dominant cause of
    range_shot_crossing failures pre-collapse). The validator's
    ``build_shot_boundary_set`` applies the same rule so the two
    consumers stay in sync.
    """
    try:
        seg_start = timestamp_to_seconds(str(segment["start"]))
        seg_end = timestamp_to_seconds(str(segment["end"]))
    except (KeyError, ValueError):
        return []
    if seg_end <= seg_start:
        return []

    if should_collapse_segment_inner_cuts(segment, MIN_SHOT_DURATION_S):
        return [(seg_start, seg_end)]

    inner: list[float] = []
    for raw in segment.get("shot_boundaries_s") or ():  # type: ignore[union-attr]
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if seg_start < value < seg_end:
            inner.append(value)
    inner.sort()

    cut_points = [seg_start, *inner, seg_end]
    shots: list[tuple[float, float]] = []
    for i in range(len(cut_points) - 1):
        start = cut_points[i]
        end = cut_points[i + 1]
        if end - start >= MIN_SHOT_DURATION_S:
            shots.append((start, end))
    return shots


def _enumerate_shots(visual_segments_path: Path) -> list[tuple[int, float, float, str]]:
    """Walk every Stage 0 visual segment and emit (index, start_s, end_s, label).

    Each entry corresponds to one source shot. A multi-cut segment expands
    into multiple back-to-back shots via ``split_segment_into_shots``; all
    sub-shots from one segment share the parent's `summary`, `characters`,
    and `ocr_text` (the segment described one event; per-shot ranges exist
    for pacing control).
    """
    segments = load_visual_segments(visual_segments_path)
    shots: list[tuple[int, float, float, str]] = []
    shot_index = 0
    for segment in segments:
        characters = "|".join(get_segment_characters(segment))
        chars_part = f"chars={characters} | " if characters else ""
        summary = collapse_whitespace(str(segment.get("summary") or ""))
        ocr_text = collapse_whitespace(str(segment.get("ocr_text") or ""))
        ocr_part = f" | ocr={ocr_text}" if ocr_text else ""
        label = f"{chars_part}{summary}{ocr_part}"
        for shot_start, shot_end in split_segment_into_shots(segment):
            shot_index += 1
            shots.append((shot_index, shot_start, shot_end, label))
    return shots


def build_shot_menu(visual_segments_path: Path) -> str:
    """The ONLY legal source of anchor-range timestamps.

    Each line is one source shot, formatted so the planner can copy the
    `start → end` timestamps verbatim into an [ANCHOR ranges="..."] block.
    Lines do not interleave with dialogue — keeping shots in their own
    section makes it visually obvious that two adjacent shots are
    separate units, not one continuous span (the #1 cause of the
    range_shot_crossing failures we used to see).

    Example lines::

        [shot:042] 00:23:00.000 → 00:23:08.000 (8.0s) :: chars=Yuta | walks into bloody room
        [shot:043] 00:23:08.000 → 00:23:14.000 (6.0s) :: chars=Villain | villain stands in corner
    """
    shots = _enumerate_shots(visual_segments_path)
    lines: list[str] = []
    for index, start_s, end_s, label in shots:
        duration_s = end_s - start_s
        lines.append(
            f"[shot:{index:03d}] "
            f"{seconds_to_timestamp(start_s)} → "
            f"{seconds_to_timestamp(end_s)} "
            f"({duration_s:.1f}s) :: "
            f"{label}"
        )
    return "\n".join(lines)


def build_dialogue_block(
    subtitle_srt_path: Path, visual_segments_path: Path
) -> str:
    """Spoken dialogue, each line tagged with the shot it falls inside.

    Context only — the planner reads this to know what is *said* during a
    beat, but anchor ranges MUST come from the shot menu, never from
    these timestamps. Each `[srt:NNN]` line is annotated with
    ``inside shot:NNN`` so the planner can map "I want the beat where
    they say X" → "that's inside shot:NNN" → "use shot:NNN's start/end
    in the range."

    Example line::

        [srt:128 inside shot:043] 00:23:11.000 → 00:23:13.500 :: Yuta: 你是谁
    """
    subtitles = parse_subtitles(subtitle_srt_path)
    shots = _enumerate_shots(visual_segments_path)

    def find_shot_index(t: float) -> int | None:
        # Binary search would be marginal at typical scale (~1500 shots);
        # the linear scan keeps the code readable and the cost is one-time
        # at prompt-build.
        for shot_idx, start_s, end_s, _ in shots:
            if start_s <= t < end_s:
                return shot_idx
        return None

    lines: list[str] = []
    for index, subtitle in enumerate(subtitles, 1):
        speaker_part = f"{subtitle.speaker}: " if subtitle.speaker else ""
        text = collapse_whitespace(subtitle.text)
        midpoint = (subtitle.start + subtitle.end) / 2.0
        shot_idx = find_shot_index(midpoint) or find_shot_index(subtitle.start)
        anchor_hint = f" inside shot:{shot_idx:03d}" if shot_idx is not None else ""
        lines.append(
            f"[srt:{index:03d}{anchor_hint}] "
            f"{seconds_to_timestamp(subtitle.start)} → "
            f"{seconds_to_timestamp(subtitle.end)} :: "
            f"{speaker_part}{text}"
        )
    return "\n".join(lines)


def _format_shot_example(shots: list[tuple[int, float, float, str]]) -> str:
    """Pick a usable shot for the worked-example block in the prompt.

    Returns a literal `[shot:NNN] HH:MM:SS.mmm → HH:MM:SS.mmm` string the
    planner can compare against its `[ANCHOR ranges="..."]` line.
    """
    # Skip the very first shots — they are usually production logos and
    # would make a confusing example. Find the first shot ≥4s long after
    # the 60s mark; fall back to the first available shot.
    for index, start_s, end_s, _ in shots:
        if start_s >= 60.0 and (end_s - start_s) >= 4.0:
            return (
                f"[shot:{index:03d}] {seconds_to_timestamp(start_s)} → "
                f"{seconds_to_timestamp(end_s)} ({end_s - start_s:.1f}s)"
            )
    if shots:
        index, start_s, end_s, _ = shots[0]
        return (
            f"[shot:{index:03d}] {seconds_to_timestamp(start_s)} → "
            f"{seconds_to_timestamp(end_s)} ({end_s - start_s:.1f}s)"
        )
    return "[shot:042] 00:23:00.000 → 00:23:08.000 (8.0s)"


def _format_adjacent_shots_example(
    shots: list[tuple[int, float, float, str]],
) -> str | None:
    """Find two genuinely-adjacent shots from this movie's menu and format
    a WRONG-vs-RIGHT multi-range example block from them.

    "Adjacent" means shot B starts where shot A ends (within float tolerance).
    Both shots must be ≥4s — short shots make confusing examples, and
    short adjacent shots are exactly the case the inner-cut collapse rule
    already removes.

    Returns None when no qualifying pair is found, in which case the
    caller should fall back to a generic placeholder block.
    """
    for i in range(len(shots) - 1):
        idx_a, start_a, end_a, _ = shots[i]
        idx_b, start_b, end_b, _ = shots[i + 1]
        if start_a < 60.0:
            continue
        if abs(end_a - start_b) > 0.001:
            continue
        if (end_a - start_a) < 4.0 or (end_b - start_b) < 4.0:
            continue
        ts_a_start = seconds_to_timestamp(start_a)
        ts_a_end = seconds_to_timestamp(end_a)  # also = ts_b_start (boundary)
        ts_b_end = seconds_to_timestamp(end_b)
        return (
            f"  [shot:{idx_a:03d}] {ts_a_start} → {ts_a_end} ({end_a - start_a:.1f}s)\n"
            f"  [shot:{idx_b:03d}] {ts_a_end} → {ts_b_end} ({end_b - start_b:.1f}s)\n"
            f"\n"
            f"To narrate one beat covering BOTH shots, write TWO ranges (one per shot):\n"
            f'  [ANCHOR id="chunk-XXX" ranges="{ts_a_start}-{ts_a_end}, {ts_a_end}-{ts_b_end}" characters="..."]\n'
            f"  narration that plays back-to-back across the two shots\n"
            f"\n"
            f"WRONG — never write a single merged range:\n"
            f'  ranges="{ts_a_start}-{ts_b_end}"\n'
            f"  ↑ this crosses the shot boundary at {ts_a_end} and the validator\n"
            f"    rejects it as `range_shot_crossing`. The viewer would see a\n"
            f"    hard cut mid-narration, which is exactly what the contract\n"
            f"    forbids. If you want this whole beat as one anchor, you MUST\n"
            f"    split it into two ranges separated by `, ` as shown above."
        )
    return None


def read_synopsis(synopsis_path: Path | None) -> str:
    """Read the optional synopsis file, returning the empty string when absent.

    Synopsis files are user-authored markdown describing plot, cast, and
    cultural context the planner needs but cannot infer from raw SRT/visuals.
    Recommended structure: one-line pitch, cast list with archetype labels,
    beat outline, cultural hooks. See HANDBOOK §6 (post-overhaul).
    """
    if synopsis_path is None or not synopsis_path.exists():
        return ""
    return synopsis_path.read_text(encoding="utf-8")


def build_planner_prompt(
    style_path: Path,
    subtitle_srt_path: Path,
    visual_segments_path: Path,
    movie_title: str,
    genre: str,
    target_seconds: float,
    synopsis_path: Path | None = None,
    chars_per_second: float | None = None,
) -> str:
    """Assemble the single-pass planner-writer prompt.

    The planner sees the full style rulebook (verbatim), an optional external
    synopsis, a shot menu (legal range source), a separate dialogue block
    (context only), and the budget formula. It outputs the final anchored
    script in one shot.

    `chars_per_second` defaults to whatever the style file declares (read by
    `read_style_chars_per_second`); pass an override only for tests.
    """
    style_text = style_path.read_text(encoding="utf-8")
    if chars_per_second is None:
        chars_per_second = read_style_chars_per_second(style_path)
    # Macro budget uses real TTS speech rate, not the per-anchor writing
    # cap (`chars_per_second`). The cap controls how much the LLM may
    # write per anchor; the macro budget controls how many chars are
    # needed to produce `target_seconds` of audio at TTS playback speed.
    review_budget = build_review_budget(target_seconds, REAL_TTS_CPS)
    coverage_budget = build_coverage_budget(target_seconds, chars_per_second)
    shot_menu = build_shot_menu(visual_segments_path)
    dialogue_block = build_dialogue_block(subtitle_srt_path, visual_segments_path)
    shot_examples = _enumerate_shots(visual_segments_path)
    example_shot_line = _format_shot_example(shot_examples)
    adjacent_pair_block = _format_adjacent_shots_example(shot_examples) or (
        "  (no two adjacent ≥4s shots found in this movie's menu — the\n"
        "   abstract pattern from the multi-shot example below still applies)"
    )
    synopsis_text = read_synopsis(synopsis_path).strip()

    synopsis_block = (
        synopsis_text
        if synopsis_text
        else "(No synopsis provided. Infer plot/character context from the timeline below.)"
    )

    # Macro-level budget — LLMs pace much better when given the global total
    # alongside the per-anchor formula.
    total_budget_chars = review_budget.target_chars
    act1_target_chars = int(total_budget_chars * 0.16)
    act2_target_chars = int(total_budget_chars * 0.24)
    act3_target_chars = int(total_budget_chars * 0.40)
    act4_target_chars = total_budget_chars - act1_target_chars - act2_target_chars - act3_target_chars
    # Total selected source coverage needs its own budget. Too little
    # coverage yields under-length audio; too much coverage forces Stage 6
    # to discard large parts of the chosen visual sequence, which breaks
    # semantic sync even when timing still matches.
    coverage_target = coverage_budget.target_seconds
    coverage_min = coverage_budget.min_seconds
    coverage_max = coverage_budget.max_seconds
    # Anchor-count guidance under the shot-aware contract: each anchor caps
    # at MAX_ANCHOR_TOTAL_DURATION_S (12s) and averages ~8-10s. Lower bound
    # is the math floor (every anchor at the cap); upper bound assumes
    # ~5-6s avg anchor (more rapid cuts for action-heavy material).
    anchor_count_low = max(20, int(coverage_target / float(MAX_ANCHOR_TOTAL_DURATION_S)))
    anchor_count_high = max(anchor_count_low + 10, int(coverage_target / 6))

    return f"""# Role
{PLANNER_ROLE}

# Style Rulebook (your voice authority)
The rulebook below is the single source of truth for tone, structure, beat
density, character naming, and genre modulation. Follow every
rule exactly. The voice you produce must read as if written by a human in
this style — never sacrifice voice quality to fit the budget below.

**Review length, total narration budget, and anchor coverage come ONLY from
the Movie Config Budget below.** If the style rulebook contains any legacy
duration or character-count guidance, ignore that legacy number and follow the
movie config budget instead.

<<<STYLE_RULEBOOK_START>>>
{style_text}
<<<STYLE_RULEBOOK_END>>>

# External Context
Use this to ground character names, plot stakes, cultural hooks, and any
narrative interpretation that cannot be derived from raw dialogue alone.

<<<SYNOPSIS_START>>>
{synopsis_block}
<<<SYNOPSIS_END>>>

# Movie
Title: {movie_title}
Genre: {genre}

# Movie Config Budget — SINGLE SOURCE OF TRUTH
target_seconds = {review_budget.target_seconds:.0f}
acceptable_review_window = {review_budget.min_seconds:.0f}-{review_budget.max_seconds:.0f}s

# TTS Budget — HARD CONSTRAINT
chars_per_second = {chars_per_second}

For every [ANCHOR ...] block, the narration text underneath it must satisfy:

    chars(narration) ≤ sum(range_seconds) × {chars_per_second}

Where `sum(range_seconds)` is the total duration of all ranges in that
anchor. Example: an anchor with ranges totalling 12 seconds has a budget
of 12 × {chars_per_second} = {int(12 * chars_per_second)} characters of narration.

**Per-anchor duration cap (NEW — shot-aware contract):**
Each anchor's total duration MUST be ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s. This is a hard
validator constraint. Beyond {int(MAX_ANCHOR_TOTAL_DURATION_S)}s the within-anchor drift between
narration pace and source-edit pace exceeds ~3s and the audience hears
narration about a beat they aren't seeing yet. If a story moment needs
more than {int(MAX_ANCHOR_TOTAL_DURATION_S)}s of screen time, **split it into two consecutive
anchors**, each describing the next slice of the moment.

**Total-script budget (macro pacing target):**
With a target review of ~{review_budget.target_seconds:.0f}s, your total narration across
ALL anchors must land in {review_budget.min_chars}-{total_budget_chars} characters
(target: {total_budget_chars}). Pace your four acts evenly — do not blow
{int(total_budget_chars * 0.5)} chars on the hook and arrive at the climax with
nothing left. Equally important: **do NOT undershoot.** Under-budget audio
makes the finished video feel thin and unfinished — falling below
{review_budget.min_chars} chars is a failure mode, not a safe choice.

    To support this budget, your selected anchor ranges must stay inside a
    **coverage window**. At the per-anchor cap of {chars_per_second} chars/s,
    producing {total_budget_chars} chars calls for about {coverage_target:.0f}s of
    selected source video, so keep `sum(all_anchor_seconds)` inside
    **{coverage_min:.0f}-{coverage_max:.0f}s** (target ~{coverage_target:.0f}s), distributed across
    ~{anchor_count_low}–{anchor_count_high} anchors total.

    **Do NOT over-cover "just in case."** If you select 2x-3x more footage than
    the narration can support, Stage 6 must discard large parts of your chosen
    visual sequence and the final video stops matching the spoken story beat.
    Every selected second should carry story value.

A downstream validator rejects narrations that exceed any single anchor's
budget by more than 10% — Stage 5 then trims any small remaining video
slack shot-aware. The 10% over-budget cap is the only ceiling; the floor is
the macro range above.

**Local writing targets — track these WHILE drafting, not after the fact:**
- Act 1 target: ~{act1_target_chars} chars
- Act 2 target: ~{act2_target_chars} chars
- Act 3 target: ~{act3_target_chars} chars
- Act 4 target: ~{act4_target_chars} chars
- For most anchors, use roughly **85–95% of the local per-anchor budget**.
  Thin anchors are a major failure mode: one short sentence may be valid,
  but if you leave 15–30 unused chars in 60+ anchors, the final audio
  collapses minutes short.
- Per-anchor fill examples at `chars_per_second = {chars_per_second}`:
  - 6s anchor → budget {int(round(6 * chars_per_second))} chars → aim for ~{int(round(6 * chars_per_second * 0.85))}-{int(round(6 * chars_per_second * 0.95))} chars
  - 8s anchor → budget {int(round(8 * chars_per_second))} chars → aim for ~{int(round(8 * chars_per_second * 0.85))}-{int(round(8 * chars_per_second * 0.95))} chars
  - 10s anchor → budget {int(round(10 * chars_per_second))} chars → aim for ~{int(round(10 * chars_per_second * 0.85))}-{int(round(10 * chars_per_second * 0.95))} chars
- Only underfill an anchor on purpose when the beat truly needs a brief
  reaction, pause, or transition. Otherwise, expand the narration until the
  anchor feels full.

# Source Material — TWO sections, used differently
The story material below is split into a **Shot Menu** (the only legal
source of anchor-range timestamps) and a **Dialogue** block (context only —
NEVER usable as a range source). Treat them as two distinct lookup tables.

- `[shot:NNN] HH:MM:SS.mmm → HH:MM:SS.mmm (Xs) :: ...` — one **source shot**
  (the editor's atomic visual unit). The `(Xs)` annotation is the shot's
  duration. **Every anchor range MUST be a copy of one shot's timestamps**
  (or a sub-window inside one shot — see "Sub-shot trims" below). Each
  shot lives on its own line; two adjacent shots are SEPARATE units, not
  one continuous span.
- `[srt:NNN inside shot:MMM] HH:MM:SS.mmm → HH:MM:SS.mmm :: speaker: line` —
  one spoken-dialogue line, tagged with the shot it falls inside.
  **NEVER use `[srt:NNN]` timestamps as anchor ranges.** When you want a
  beat where someone is talking, look up the line in Dialogue, then use
  the timestamps from the `inside shot:MMM` shot instead.

**How to choose shots:**

- **Prefer long shots (≥5s).** A long single-shot anchor is the most
  comfortable pacing for the audience. Use multi-range anchors only when
  the beat is genuinely shown across multiple shots in the source.
- **Avoid very short shots (<2s)** unless one specific frame is essential
  to the beat. They cause rapid cuts and make the review feel switchy.
- **Multi-range anchors** are how you cover a multi-shot beat (e.g. wide
  shot then reaction). Each range = exactly ONE `[shot:NNN]`. Never widen
  a range to cover two shots — that bridges a hard cut and the validator
  rejects it.
- **Sub-shot trims are allowed.** You may pick less than a full shot's
  duration (e.g. only the last 3s of an 8s shot), but you MUST stay
  inside that one shot — never let a range cross a `[shot:NNN]` boundary.

# Worked Examples — copy-paste patterns from THIS movie's menu

**Single-shot anchor (preferred default):**
Reference shot from this movie's menu:
  {example_shot_line}

```
[ANCHOR id="chunk-007" ranges="<paste this shot's start>-<paste this shot's end>" characters="Name A"]
narration text — sized to fit (shot duration) × {chars_per_second}
```

**Multi-shot anchor — RIGHT vs WRONG with REAL adjacent shots from this movie:**
Two genuinely-adjacent shots taken from your shot menu:
{adjacent_pair_block}

The "WRONG" form above — a single range whose start and end come from
two different shots — is the dominant failure mode the validator
catches. ALWAYS use the "RIGHT" form: one comma-separated range per
shot, with the boundary timestamp appearing twice (once as the end of
range #1, once as the start of range #2). Even if two shots have the
same `chars=...` and the same description, they are SEPARATE shots in
the source edit; the audience sees a cut between them.

**Sub-shot trim (range stays inside one shot):**
```
[ANCHOR id="chunk-009" ranges="<shot:050 start>-<shot:050 start + 4s>" characters="Name A"]
narration covering only the first 4s of an 8s shot
```

**Splitting a 16s beat into two anchors (because 12s cap):**
```
[ANCHOR id="chunk-010" ranges="<shot:060 start>-<shot:060 end>" characters="Name A"]
first half of the beat (≤ 8s of narration)

[ANCHOR id="chunk-011" ranges="<shot:061 start>-<shot:061 end>" characters="Name A"]
second half of the same beat (≤ 8s of narration)
```

# Final Budget Reminder — READ NOW, BEFORE THE SHOT MENU
The shot menu below is long. Lock these numbers in working memory now,
because once you start scanning shots it is easy to forget the macro
budget and stop expanding the script too early.

- **Total narration must land in {review_budget.min_chars}-{total_budget_chars} characters
  (target {total_budget_chars}).** Anything below {review_budget.min_chars} is a failure
  — the resulting audio will be too short to cover the movie's plot.
- **Per-act guideline (sums to {total_budget_chars}, climax-weighted):**
  Act 1 ≈ {act1_target_chars} chars, Act 2 ≈ {act2_target_chars} chars,
  Act 3 ≈ {act3_target_chars} chars, Act 4 ≈ {act4_target_chars} chars.
  The climax (Act 3) is the largest act on purpose — it is where maximum
  information density and the biggest payoff land. Compress Act 1/Act 2
  ruthlessly (cut subplots, merge minor characters) before borrowing from
  Act 3.
 - **Anchor coverage:** keep the sum of all selected anchor seconds inside
   {coverage_min:.0f}-{coverage_max:.0f}s (target ~{coverage_target:.0f}s), distributed across
   ~{anchor_count_low}-{anchor_count_high} anchors (avg ~{int(coverage_target / max(anchor_count_low, 1))}s per anchor, capped at {int(MAX_ANCHOR_TOTAL_DURATION_S)}s).
   Do not select large extra coverage as "backup" footage.
- **Per-anchor budget:** chars(narration) ≤ sum(range_seconds) × {chars_per_second}.
- **Per-anchor fill target:** for most anchors, aim to use ~85-95% of that
  local budget. Do NOT habitually write one thin sentence under a long anchor.
- **Per-anchor duration cap:** sum(range_seconds) ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s.
- **Per-range shot rule:** each range must stay inside ONE `[shot:NNN]`.
- **Every anchor must declare an id:** `id="chunk-NNN"`, sequential and
  zero-padded to 3 digits, starting from `chunk-001`.

**Pre-output self-check (do this mentally before emitting the script):**
1. Will my total narration fall in {review_budget.min_chars}-{total_budget_chars} chars?
2. Is each act close to its local target (Act 1 ~{act1_target_chars}, Act 2 ~{act2_target_chars}, Act 3 ~{act3_target_chars}, Act 4 ~{act4_target_chars}; Act 3 the largest)?
3. Is my total selected anchor coverage inside {coverage_min:.0f}-{coverage_max:.0f}s (target ~{coverage_target:.0f}s), rather than under-covering or selecting 2x extra footage?
4. For most anchors, did I use ~85-95% of the local budget instead of stopping at one thin sentence?
5. Does every range I wrote come from a `[shot:NNN]` line, not `[srt:NNN]`?
6. Does every anchor's total duration stay ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s?
7. Does every anchor have a unique `id="chunk-NNN"`?

If any answer is "no", expand or fix the script before outputting — do NOT
emit a short or under-labeled script "to be safe."

<<<SHOT_MENU_START>>>
{shot_menu}
<<<SHOT_MENU_END>>>

<<<DIALOGUE_START>>>
{dialogue_block}
<<<DIALOGUE_END>>>

# Authoring Algorithm
1. Read the style rulebook. Internalize the voice.
2. Read the synopsis (if any) and skim the dialogue block + shot menu for the story shape.
3. Identify the narrative beats worth featuring. Each beat = one anchor.
   Be selective — the shot menu is not a quota; you may leave large
   portions of the source unselected.
4. Allocate screen-time roughly: climax beats deserve more anchors, setup
   beats fewer. Aim for ~{anchor_count_low}–{anchor_count_high} anchors total
   for a {review_budget.target_seconds:.0f}s review.
5. For each beat, choose its anchor's ranges from the `[shot:NNN]` lines:
   - **Single-shot anchor (preferred default):** pick one shot, ideally
     ≥5s long. `ranges="<shot's start>-<shot's end>"`.
   - **Multi-shot anchor:** pick 2-3 shots that visualize the same beat
     (wide → reaction; or rapid action covered by 2-3 cuts). The ranges
     play back-to-back as one continuous beat under one narration line.
   - **Sub-shot trim:** if you only want the last few seconds of a long
     shot, write a range with timestamps inside that shot. Just stay
     inside ONE `[shot:NNN]` — never bridge two.
   - Total anchor duration (sum of range durations) ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s.
6. Write narration in the style voice. Size each beat's character count
   to fit `sum(range_seconds) × {chars_per_second}` and usually consume
   ~85-95% of that local budget. A thin anchor is not "safe" if it leaves
   obvious unused room.
7. Total review length: aim for roughly {review_budget.target_seconds:.0f}s
   ({review_budget.min_seconds:.0f}–{review_budget.max_seconds:.0f}s acceptable).

# Output Schema

```
[TITLE] {movie_title}
[HOOK]
[ANCHOR id="chunk-001" ranges="HH:MM:SS.mmm-HH:MM:SS.mmm" characters="Name A|Name B"]
narration text bounded by sum_of_range_seconds × {chars_per_second}

[ACT 1 - SETUP]
[ANCHOR id="chunk-002" ranges="HH:MM:SS-HH:MM:SS, HH:MM:SS-HH:MM:SS"]
narration spanning two consecutive shots

[ACT 2 - ESCALATION]
[ANCHOR id="chunk-003" ...]
narration

[ACT 3 - CLIMAX]
[ANCHOR id="chunk-004" ...]
narration

[ACT 4 - RESOLUTION]
[ANCHOR id="chunk-005" ...]
narration

[CLOSING]
narration with NO [ANCHOR] — plays over a still keyframe
```

The exact ACT suffixes follow the style rulebook (some styles use
"REVEAL + CLIMAX" instead of "CLIMAX").

# Hard Constraints (re-stated — the validator will reject any violation)
1. **Every [ANCHOR] line MUST include `id="chunk-NNN"`** (sequential,
   zero-padded 3 digits, unique across the script, starting from chunk-001).
2. Anchors must be in chronological order across the script (early-movie
   before later-movie within each ACT, and ACTs in story order).
3. Within one [ANCHOR], multi-range entries must NOT overlap.
4. **All range timestamps MUST come from `[shot:NNN]` lines** in the Shot
   Menu above. Never use `[srt:NNN]` timestamps; never invent times.
5. **Each range must stay inside ONE `[shot:NNN]`.** A range that bridges
   two consecutive shots crosses a hard cut — the validator rejects it
   because the audience sees a jump cut mid-narration. To cover two shots
   in one beat, use a multi-range anchor with one range per shot.
6. **Each individual range duration must be ≤ {int(MAX_ANCHOR_RANGE_DURATION_S)}s.**
7. **Each anchor's total duration (sum of range durations) must be ≤ {int(MAX_ANCHOR_TOTAL_DURATION_S)}s.**
   If a beat needs more screen time, split into two consecutive anchors
   (chunk-NNN, chunk-(NNN+1)) — see worked examples above.
8. **Per-anchor narration budget:** chars(narration) ≤ sum(range_seconds) × {chars_per_second}.
9. Closing chunk has narration but no [ANCHOR].

# Final Output Gate
Before you output, stop and verify these four points one last time:
- total narration is at least {review_budget.min_chars} chars
- total selected anchor coverage stays inside {coverage_min:.0f}-{coverage_max:.0f}s
- each act is near its local target and Act 3 is the largest act
- most anchors use ~85-95% of their local budget rather than one thin sentence

# Produce
Output ONLY the anchored script. No preamble, no code fences, no commentary.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stage2-generate-script",
        description="Print the Stage 2 planner-writer prompt to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("style", type=Path, help="Path to the style .md file")
    parser.add_argument("subtitle_srt", type=Path, help="Source subtitle file (.srt or .ass)")
    parser.add_argument("visual_segments", type=Path, help="visual_segments.json from Stage 0")
    parser.add_argument(
        "--movie-title",
        help="Movie title with optional language. Defaults to the subtitle filename stem.",
    )
    parser.add_argument(
        "--genre",
        default=DEFAULT_GENRE,
        help="Genre keyword for genre-modulated voice.",
    )
    parser.add_argument(
        "--synopsis",
        type=Path,
        default=None,
        help="Optional path to a synopsis markdown file (plot, cast, cultural context).",
    )
    parser.add_argument(
        "--target-seconds",
        type=float,
        default=DEFAULT_TARGET_SECONDS,
        help="Authoritative Stage 2 review target in seconds; prompt and validation derive their macro budget from it.",
    )
    return parser


def missing_input_paths(paths: list[Path]) -> list[Path]:
    return [p for p in paths if not p.exists()]


def report_missing_paths(missing: list[Path]) -> None:
    for path_arg in missing:
        print(f"Input not found: {path_arg}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    required = [args.style, args.subtitle_srt, args.visual_segments]
    missing_paths = missing_input_paths(required)
    if missing_paths:
        report_missing_paths(missing_paths)
        return 1

    if args.synopsis is not None and not args.synopsis.exists():
        # Optional input — but if the user asked for one, fail loud rather
        # than silently producing a context-less prompt.
        print(f"Synopsis not found: {args.synopsis}", file=sys.stderr)
        return 1

    movie_title = infer_movie_title(args.subtitle_srt, args.movie_title)
    print(
        build_planner_prompt(
            style_path=args.style,
            subtitle_srt_path=args.subtitle_srt,
            visual_segments_path=args.visual_segments,
            movie_title=movie_title,
            genre=args.genre,
            target_seconds=args.target_seconds,
            synopsis_path=args.synopsis,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
