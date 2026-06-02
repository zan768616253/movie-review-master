# Stage 2 Multi-Pass Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `app/pipeline/stage_2_build_prompt.py` into a 3-pass pipeline (Pass 0 scene outline → Pass 1 act-weighted digest → Pass 2 story), plus an opt-in chunked digest mode and a deterministic post-validation step, with clean separation between the default and chunked paths.

**Architecture:** Introduce a new `app/pipeline/stage_2/` subpackage; relocate existing prompt builders into focused per-pass modules; add a new outline builder and post-validator; thin the existing `stage_2_build_prompt.py` to a CLI dispatcher only.

**Tech Stack:** Python 3.12, pytest, argparse, json. No new third-party dependencies.

**Spec:** `docs/specs/2026-05-15-stage2-multi-pass-design.md`

---

## File structure

**New files:**
- `app/pipeline/stage_2/__init__.py` — subpackage marker; re-exports the public API
- `app/pipeline/stage_2/timeline.py` — shared timeline helpers (relocated)
- `app/pipeline/stage_2/pass_0_outline.py` — outline prompt builder + thin-timeline view
- `app/pipeline/stage_2/scene_markers.py` — scene_markers.json schema + loader
- `app/pipeline/stage_2/pass_1_digest_single.py` — single-mode digest builder
- `app/pipeline/stage_2/pass_1_digest_chunked.py` — chunked-mode digest orchestrator
- `app/pipeline/stage_2/pass_2_story.py` — story prompt builder (relocated)
- `app/pipeline/stage_2/post_validate.py` — script ref-validator
- `tests/pipeline/test_pass_0_outline.py`
- `tests/pipeline/test_pass_1_digest_single.py`
- `tests/pipeline/test_pass_1_digest_chunked.py`
- `tests/pipeline/test_post_validate.py`
- `tests/pipeline/test_stage_2_integration.py`

**Modified files:**
- `app/pipeline/stage_2_build_prompt.py` — thinned to CLI dispatcher; re-exports kept for backward compat
- `workbench/step_2_build_prompt.py` — handles 3-pass flow + `digest_mode` config
- `workbench/_common.py` — adds `outline_prompt`, `scene_markers`, `hallucination_report` to `PipelinePaths`
- `workbench/configs/_template.toml` — documents `digest_mode` field
- `tests/pipeline/test_stage_2_build_prompt.py` — adjusted imports to new module layout (existing assertions kept)

**Untouched:**
- Stage 1, 3, 4 pipeline files
- `styles/niu-shu.md` and all `styles/genres/**` files
- `app/pipeline/common/script_contract.py`

---

## Test execution conventions

All Python commands in this plan run under the project's conda env. The required prefix is:

```
conda run -n py312_machine_learning --no-capture-output
```

For brevity, the steps below write `python -m pytest ...` etc.; **prepend the conda prefix to every actual run**. Reference: `docs/agent-rules/python-environment.md`.

---

## Task 1: Bootstrap `app/pipeline/stage_2/` subpackage

**Files:**
- Create: `app/pipeline/stage_2/__init__.py`
- Test: `tests/pipeline/test_stage_2_build_prompt.py` (existing — must stay green)

- [ ] **Step 1: Create the subpackage marker**

Create `app/pipeline/stage_2/__init__.py` with the content:

```python
"""Stage 2 multi-pass prompt builders.

Each pass lives in its own module:

- :mod:`pass_0_outline` — Pass 0 (scene outline + act-tags)
- :mod:`pass_1_digest_single` — Pass 1 single-call digest
- :mod:`pass_1_digest_chunked` — Pass 1 act-chunked digest
- :mod:`pass_2_story` — Pass 2 story script prompt
- :mod:`post_validate` — deterministic ref validation

Shared helpers live in :mod:`timeline` and :mod:`scene_markers`.
"""
```

- [ ] **Step 2: Verify existing tests still pass**

```
python -m pytest tests/pipeline/test_stage_2_build_prompt.py -q
```

Expected: all existing tests pass (no behaviour change yet).

- [ ] **Step 3: Commit**

```
git add app/pipeline/stage_2/__init__.py
git commit -m "refactor: bootstrap app/pipeline/stage_2 subpackage"
```

---

## Task 2: Relocate timeline helpers to `stage_2/timeline.py`

Moves the shared building blocks (`TimelineEntry`, `normalize_inline_text`, `parse_style_frontmatter`, `load_subtitles`, `build_timeline_entries`, `render_timeline`, `_read_text`) out of the monolith so every pass can import them without dragging the full file along. Re-exports preserve backward compat.

**Files:**
- Create: `app/pipeline/stage_2/timeline.py`
- Modify: `app/pipeline/stage_2_build_prompt.py` (replace inline helpers with re-exports)
- Test: `tests/pipeline/test_stage_2_build_prompt.py` (existing assertions must stay green)

- [ ] **Step 1: Create the new `timeline.py` module**

Write `app/pipeline/stage_2/timeline.py` with the helpers moved verbatim from the top of `stage_2_build_prompt.py` (lines covering `TimelineEntry`, regex constants `_FRONTMATTER_RE` and `_SUBTITLE_TXT_PATTERN`, and functions `normalize_inline_text`, `_read_text`, `parse_style_frontmatter`, `load_subtitles`, `build_timeline_entries`, `render_timeline`):

```python
"""Shared timeline helpers used by every Stage 2 pass."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.common.script_contract import (
    seconds_to_timestamp,
    timestamp_to_seconds,
)


@dataclass(frozen=True)
class TimelineEntry:
    kind: str
    start_s: float
    end_s: float
    body: str
    priority: int
    sequence: int

    def render(self) -> str:
        start = seconds_to_timestamp(self.start_s)
        end = seconds_to_timestamp(self.end_s)
        return f"[{self.kind} {start} -> {end}] {self.body}"


_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?\n)---[ \t]*\n", re.DOTALL)
_SUBTITLE_TXT_PATTERN = re.compile(
    r"^\[(?P<start>\d{2}:\d{2}:\d{2}\.\d+) -> (?P<end>\d{2}:\d{2}:\d{2}\.\d+)\]\s*(?P<body>.*)$"
)


def normalize_inline_text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    return " / ".join(part.strip() for part in text.split("\n") if part.strip())


def read_text_strict(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Text file is empty: {path}")
    return text


def parse_style_frontmatter(style_text: str) -> tuple[dict[str, object], str]:
    """Extract simple key-value frontmatter from a style markdown file."""
    m = _FRONTMATTER_RE.match(style_text)
    if not m:
        return {}, style_text
    meta: dict[str, object] = {}
    for line in m.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        val = val.strip()
        for convert in (int, float):
            try:
                val = convert(val)  # type: ignore[assignment]
                break
            except (ValueError, TypeError):
                continue
        meta[key] = val
    return meta, style_text[m.end():]


def load_subtitles(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []

    subtitles: list[dict[str, object]] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        match = _SUBTITLE_TXT_PATTERN.match(line)
        if not match:
            raise ValueError(f"Invalid subtitle line format: {line}")
        subtitles.append({
            "start": match.group("start"),
            "end": match.group("end"),
            "text": match.group("body"),
        })
    return subtitles


def build_timeline_entries(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []

    for index, segment in enumerate(visual_segments):
        try:
            start = str(segment["start"])
            end = str(segment["end"])
        except KeyError as exc:
            raise ValueError(f"Visual segment #{index + 1} is missing {exc.args[0]!r}") from exc

        start_s = timestamp_to_seconds(start)
        end_s = timestamp_to_seconds(end)
        if end_s <= start_s:
            raise ValueError(f"Visual segment #{index + 1} has end <= start")

        segment_id = str(segment.get("id") or f"visual:{index + 1:03d}")
        summary = normalize_inline_text(segment.get("summary")) or "(no visual summary)"
        parts = [f"{segment_id} | {summary}"]

        characters = segment.get("characters")
        if isinstance(characters, list):
            character_names = [normalize_inline_text(item) for item in characters if normalize_inline_text(item)]
            if character_names:
                parts.append(f"characters: {', '.join(character_names)}")

        ocr_text = normalize_inline_text(segment.get("ocr_text"))
        if ocr_text:
            parts.append(f"on-screen text: {ocr_text}")

        entries.append(TimelineEntry(
            kind="VISUAL",
            start_s=start_s,
            end_s=end_s,
            body=" | ".join(parts),
            priority=0,
            sequence=index,
        ))

    for index, subtitle in enumerate(subtitles):
        try:
            start_s = timestamp_to_seconds(str(subtitle["start"]))
            end_s = timestamp_to_seconds(str(subtitle["end"]))
        except KeyError as exc:
            raise ValueError(f"Subtitle #{index + 1} is missing {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Subtitle #{index + 1} has invalid timing values") from exc

        if end_s <= start_s:
            raise ValueError(f"Subtitle #{index + 1} has end <= start")

        text = normalize_inline_text(subtitle.get("text"))
        if not text:
            continue

        speaker = normalize_inline_text(subtitle.get("speaker"))
        body = f"{speaker}: {text}" if speaker else text

        entries.append(TimelineEntry(
            kind="SUBTITLE",
            start_s=start_s,
            end_s=end_s,
            body=body,
            priority=1,
            sequence=index,
        ))

    return sorted(entries, key=lambda item: (item.start_s, item.priority, item.end_s, item.sequence))


def render_timeline(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> str:
    return "\n".join(entry.render() for entry in build_timeline_entries(visual_segments, subtitles))
```

Note: the original `_read_text` is renamed to `read_text_strict` (public, no underscore) since it's now used cross-module.

- [ ] **Step 2: Replace inline helpers in `stage_2_build_prompt.py` with re-exports**

In `app/pipeline/stage_2_build_prompt.py`, delete the inline definitions of `TimelineEntry`, `_FRONTMATTER_RE`, `_SUBTITLE_TXT_PATTERN`, `normalize_inline_text`, `_read_text`, `parse_style_frontmatter`, `load_subtitles`, `build_timeline_entries`, `render_timeline` (currently around lines 38–196). Replace the block with:

```python
from app.pipeline.stage_2.timeline import (
    TimelineEntry,
    build_timeline_entries,
    load_subtitles,
    normalize_inline_text,
    parse_style_frontmatter,
    read_text_strict as _read_text,
    render_timeline,
)
```

The `read_text_strict as _read_text` alias preserves the existing private name used elsewhere in the file.

- [ ] **Step 3: Run existing tests to verify behaviour is preserved**

```
python -m pytest tests/pipeline/test_stage_2_build_prompt.py -q
```

Expected: all tests pass with no warnings about missing symbols.

- [ ] **Step 4: Commit**

```
git add app/pipeline/stage_2/timeline.py app/pipeline/stage_2_build_prompt.py
git commit -m "refactor: relocate stage 2 timeline helpers to stage_2/timeline.py"
```

---

## Task 3: Relocate `build_digest_prompt` to `stage_2/pass_1_digest_single.py`

Pulls the existing digest builder out of the monolith. Behaviour is preserved (this is a pure move + import-update). The function will be modified in Task 6 to consume `scene_markers`.

**Files:**
- Create: `app/pipeline/stage_2/pass_1_digest_single.py`
- Modify: `app/pipeline/stage_2_build_prompt.py` (replace inline definition with re-export)
- Test: `tests/pipeline/test_stage_2_build_prompt.py` (existing assertions must stay green)

- [ ] **Step 1: Create `pass_1_digest_single.py` with the digest builder moved verbatim**

Cut the entire `build_digest_prompt(...)` function (current lines ~424–538 in `stage_2_build_prompt.py`) and place it in a new file:

```python
"""Pass 1 single-mode digest prompt builder.

Today's behaviour: produces a chronological digest prompt from the full
timeline. Task 6 of the multi-pass plan adds scene-marker awareness and
act-weighted beat targets without changing the import path.
"""

from __future__ import annotations


def build_digest_prompt(
    *,
    timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_rules_text: str | None = None,
    target_minutes: float = 12.0,
) -> str:
    """Assemble the Pass 1 digest prompt."""
    # [Paste the function body verbatim from stage_2_build_prompt.py]
```

(The body is verbatim — no edits in this task. The body assembles `sections` and joins them; see the current implementation.)

- [ ] **Step 2: Replace the inline digest builder in `stage_2_build_prompt.py` with a re-export**

Delete the function from `stage_2_build_prompt.py` and add to the imports block:

```python
from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt
```

- [ ] **Step 3: Run existing tests**

```
python -m pytest tests/pipeline/test_stage_2_build_prompt.py -q
```

Expected: all tests pass; the `test_build_digest_prompt_injects_genre_rules_before_timeline` test should still find the function via the existing import.

- [ ] **Step 4: Commit**

```
git add app/pipeline/stage_2/pass_1_digest_single.py app/pipeline/stage_2_build_prompt.py
git commit -m "refactor: relocate build_digest_prompt to stage_2/pass_1_digest_single.py"
```

---

## Task 4: Relocate `build_story_prompt` to `stage_2/pass_2_story.py`

Same shape as Task 3 — pure move with re-export. Includes the `_extract_golden_paragraph` and `_grounding_section` helpers that only Pass 2 uses.

**Files:**
- Create: `app/pipeline/stage_2/pass_2_story.py`
- Modify: `app/pipeline/stage_2_build_prompt.py`
- Test: `tests/pipeline/test_stage_2_build_prompt.py`

- [ ] **Step 1: Create `pass_2_story.py`**

Move `_extract_golden_paragraph`, `_grounding_section`, and `build_story_prompt` from `stage_2_build_prompt.py` into a new file:

```python
"""Pass 2 story script prompt builder.

Produces the prompt that asks the LLM to write the styled retelling script
from either the raw timeline (single-pass mode) or the plot digest
(two-pass mode).
"""

from __future__ import annotations


def _extract_golden_paragraph(genre_text: str, max_lines: int = 20) -> str | None:
    # [verbatim from current stage_2_build_prompt.py]


def _grounding_section(*, use_digest: bool) -> str:
    # [verbatim from current stage_2_build_prompt.py]


def build_story_prompt(
    *,
    style_text: str,
    timeline_text: str | None = None,
    digest_text: str | None = None,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_text: str | None = None,
    genre_rules_text: str | None = None,
    target_minutes: float | None = None,
    chars_per_minute: int = 250,
) -> str:
    # [verbatim from current stage_2_build_prompt.py]
```

- [ ] **Step 2: Re-export from `stage_2_build_prompt.py`**

Replace the three deleted definitions with:

```python
from app.pipeline.stage_2.pass_2_story import build_story_prompt
```

(The private `_extract_golden_paragraph` and `_grounding_section` helpers stay private to the new module — they are not referenced outside.)

- [ ] **Step 3: Run existing tests**

```
python -m pytest tests/pipeline/test_stage_2_build_prompt.py -q
```

Expected: all 8 tests pass.

- [ ] **Step 4: Commit**

```
git add app/pipeline/stage_2/pass_2_story.py app/pipeline/stage_2_build_prompt.py
git commit -m "refactor: relocate build_story_prompt to stage_2/pass_2_story.py"
```

---

## Task 5: Define `scene_markers` schema + loader

Provides the data contract that Pass 0 produces and Pass 1, Pass 2, and post-validation consume. Implemented before Pass 0 itself so downstream code has stable types to import.

**Files:**
- Create: `app/pipeline/stage_2/scene_markers.py`
- Test: `tests/pipeline/test_scene_markers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_scene_markers.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pipeline.stage_2.scene_markers import (
    ACT_TAGS,
    SceneMarker,
    SceneMarkersDocument,
    load_scene_markers,
)


def _write_doc(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "scene_markers.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_act_tags_are_the_six_documented_values() -> None:
    assert ACT_TAGS == ("HOOK", "SETUP", "ESCALATION", "CLIMAX", "RESOLUTION", "CLOSING")


def test_load_scene_markers_parses_a_minimal_valid_document(tmp_path: Path) -> None:
    path = _write_doc(tmp_path, {
        "character_glossary": [
            {"original_name": "乙骨忧太", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        "scenes": [
            {
                "id": "scene:01",
                "label": "校园偶遇",
                "act_tag": "SETUP",
                "visual_id_range": ["visual:001", "visual:031"],
                "time_range": ["00:00:01.201", "00:03:42.500"],
                "hook": "孤独高中生被诅咒纠缠",
            },
        ],
    })
    doc = load_scene_markers(path)
    assert isinstance(doc, SceneMarkersDocument)
    assert len(doc.scenes) == 1
    scene = doc.scenes[0]
    assert isinstance(scene, SceneMarker)
    assert scene.id == "scene:01"
    assert scene.act_tag == "SETUP"
    assert scene.visual_id_range == ("visual:001", "visual:031")
    assert doc.character_glossary[0]["original_name"] == "乙骨忧太"


def test_load_scene_markers_rejects_unknown_act_tag(tmp_path: Path) -> None:
    path = _write_doc(tmp_path, {
        "character_glossary": [],
        "scenes": [
            {
                "id": "scene:01",
                "label": "x",
                "act_tag": "TURNING_POINT",
                "visual_id_range": ["visual:001", "visual:001"],
                "time_range": ["00:00:00.000", "00:00:01.000"],
                "hook": "x",
            },
        ],
    })
    with pytest.raises(ValueError, match="act_tag"):
        load_scene_markers(path)


def test_load_scene_markers_rejects_overlapping_visual_id_ranges(tmp_path: Path) -> None:
    path = _write_doc(tmp_path, {
        "character_glossary": [],
        "scenes": [
            {
                "id": "scene:01", "label": "a", "act_tag": "SETUP",
                "visual_id_range": ["visual:001", "visual:010"],
                "time_range": ["00:00:00.000", "00:01:00.000"], "hook": "a",
            },
            {
                "id": "scene:02", "label": "b", "act_tag": "ESCALATION",
                "visual_id_range": ["visual:008", "visual:020"],
                "time_range": ["00:00:50.000", "00:02:00.000"], "hook": "b",
            },
        ],
    })
    with pytest.raises(ValueError, match="overlap"):
        load_scene_markers(path)


def test_scenes_by_act_tag_groups_correctly() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[],
        scenes=[
            SceneMarker("scene:01", "a", "SETUP", ("visual:001", "visual:010"), ("00:00:00.000", "00:01:00.000"), "a"),
            SceneMarker("scene:02", "b", "CLIMAX", ("visual:011", "visual:020"), ("00:01:00.000", "00:02:00.000"), "b"),
            SceneMarker("scene:03", "c", "CLIMAX", ("visual:021", "visual:030"), ("00:02:00.000", "00:03:00.000"), "c"),
        ],
    )
    by_tag = doc.scenes_by_act_tag()
    assert [s.id for s in by_tag["CLIMAX"]] == ["scene:02", "scene:03"]
    assert [s.id for s in by_tag["SETUP"]] == ["scene:01"]
```

- [ ] **Step 2: Run the test and verify it fails**

```
python -m pytest tests/pipeline/test_scene_markers.py -q
```

Expected: ImportError (`app.pipeline.stage_2.scene_markers` does not exist yet).

- [ ] **Step 3: Implement `scene_markers.py`**

Create `app/pipeline/stage_2/scene_markers.py`:

```python
"""Scene markers data contract (Pass 0 output, consumed by Pass 1+ and validation)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

ACT_TAGS: tuple[str, ...] = ("HOOK", "SETUP", "ESCALATION", "CLIMAX", "RESOLUTION", "CLOSING")


@dataclass(frozen=True)
class SceneMarker:
    id: str
    label: str
    act_tag: str
    visual_id_range: tuple[str, str]
    time_range: tuple[str, str]
    hook: str


@dataclass
class SceneMarkersDocument:
    character_glossary: list[dict[str, str]]
    scenes: list[SceneMarker]

    def scenes_by_act_tag(self) -> Mapping[str, list[SceneMarker]]:
        out: dict[str, list[SceneMarker]] = defaultdict(list)
        for scene in self.scenes:
            out[scene.act_tag].append(scene)
        return out


def _visual_id_number(visual_id: str) -> int:
    # "visual:031" -> 31
    if not visual_id.startswith("visual:"):
        raise ValueError(f"Expected 'visual:NNN', got {visual_id!r}")
    try:
        return int(visual_id.split(":", 1)[1])
    except ValueError as exc:
        raise ValueError(f"Invalid visual id: {visual_id!r}") from exc


def load_scene_markers(path: Path) -> SceneMarkersDocument:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("scene_markers.json must be an object with 'character_glossary' and 'scenes'")
    glossary = data.get("character_glossary")
    raw_scenes = data.get("scenes")
    if not isinstance(glossary, list) or not isinstance(raw_scenes, list):
        raise ValueError("scene_markers.json must have list 'character_glossary' and list 'scenes'")

    scenes: list[SceneMarker] = []
    for index, raw in enumerate(raw_scenes):
        try:
            scene = SceneMarker(
                id=str(raw["id"]),
                label=str(raw["label"]),
                act_tag=str(raw["act_tag"]),
                visual_id_range=(str(raw["visual_id_range"][0]), str(raw["visual_id_range"][1])),
                time_range=(str(raw["time_range"][0]), str(raw["time_range"][1])),
                hook=str(raw["hook"]),
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"scene #{index + 1} is malformed: {exc}") from exc
        if scene.act_tag not in ACT_TAGS:
            raise ValueError(
                f"scene {scene.id!r} has unknown act_tag {scene.act_tag!r}; "
                f"expected one of {ACT_TAGS}"
            )
        scenes.append(scene)

    # Check visual_id_range overlap (sorted by start).
    indexed = sorted(scenes, key=lambda s: _visual_id_number(s.visual_id_range[0]))
    for prev, curr in zip(indexed, indexed[1:]):
        prev_end = _visual_id_number(prev.visual_id_range[1])
        curr_start = _visual_id_number(curr.visual_id_range[0])
        if curr_start <= prev_end:
            raise ValueError(
                f"scenes {prev.id!r} and {curr.id!r} have overlapping visual_id_range "
                f"({prev.visual_id_range[1]} >= {curr.visual_id_range[0]})"
            )

    return SceneMarkersDocument(character_glossary=glossary, scenes=scenes)
```

- [ ] **Step 4: Run the tests and verify they pass**

```
python -m pytest tests/pipeline/test_scene_markers.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add app/pipeline/stage_2/scene_markers.py tests/pipeline/test_scene_markers.py
git commit -m "feat: add scene_markers schema and loader for Pass 0 output"
```

---

## Task 6: Implement Pass 0 — scene-outline prompt builder

The new LLM call that produces `scene_markers.json`. Sees a thin-timeline view (no `summary` field on visual lines), full subtitles, and the synopsis. Emits a prompt instructing the LLM to return JSON matching the schema from Task 5.

**Files:**
- Create: `app/pipeline/stage_2/pass_0_outline.py`
- Test: `tests/pipeline/test_pass_0_outline.py`

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_pass_0_outline.py`:

```python
from __future__ import annotations

from app.pipeline.stage_2.pass_0_outline import (
    build_outline_prompt,
    render_thin_timeline,
)


def test_thin_timeline_drops_visual_summary_but_keeps_id_time_chars_ocr() -> None:
    segments = [
        {
            "id": "visual:001",
            "start": "00:00:00.000",
            "end": "00:00:05.000",
            "summary": "the hero enters the warehouse — VERY LONG PROSE",
            "ocr_text": "EXIT",
            "characters": ["Hero", "Boss"],
        },
    ]
    subtitles = [
        {"start": 1.5, "end": 2.1, "text": "有人来了", "speaker": "Boss"},
    ]
    rendered = render_thin_timeline(segments, subtitles)

    # The summary text MUST NOT appear in the thin view.
    assert "VERY LONG PROSE" not in rendered
    # ID, time, characters, OCR all preserved.
    assert "visual:001" in rendered
    assert "00:00:00.000" in rendered
    assert "Hero" in rendered and "Boss" in rendered
    assert "EXIT" in rendered
    # Subtitles still appear (they are already compact).
    assert "有人来了" in rendered


def test_thin_timeline_keeps_every_visual_segment() -> None:
    segments = [
        {"id": f"visual:{i:03d}", "start": f"00:00:{i:02d}.000", "end": f"00:00:{i+1:02d}.000",
         "summary": "x", "ocr_text": "", "characters": []}
        for i in range(10)
    ]
    rendered = render_thin_timeline(segments, [])
    for i in range(10):
        assert f"visual:{i:03d}" in rendered


def test_build_outline_prompt_includes_required_sections_and_act_tags() -> None:
    prompt = build_outline_prompt(
        thin_timeline_text="visual:001 | 00:00:00.000-00:00:05.000 | chars: Hero | ocr: -",
        movie_title="Test Movie",
        synopsis_text="A simple story.",
    )
    # Schema instructions present.
    assert "scene_markers.json" in prompt or "JSON" in prompt
    # All six act-tags documented.
    for tag in ("HOOK", "SETUP", "ESCALATION", "CLIMAX", "RESOLUTION", "CLOSING"):
        assert tag in prompt
    # Hard rules from the spec.
    assert "no gaps" in prompt.lower() or "no overlap" in prompt.lower()
    assert "15" in prompt and "25" in prompt  # 15-25 scenes
    # Movie title threads through.
    assert "Test Movie" in prompt
    # Synopsis is included.
    assert "A simple story." in prompt


def test_build_outline_prompt_works_without_synopsis() -> None:
    prompt = build_outline_prompt(
        thin_timeline_text="visual:001 | 00:00:00.000-00:00:05.000 | chars: - | ocr: -",
        movie_title="Test Movie",
    )
    assert "Test Movie" in prompt
    assert "<<<SYNOPSIS_START>>>" not in prompt
```

- [ ] **Step 2: Run the test and verify it fails**

```
python -m pytest tests/pipeline/test_pass_0_outline.py -q
```

Expected: ImportError on `app.pipeline.stage_2.pass_0_outline`.

- [ ] **Step 3: Implement `pass_0_outline.py`**

```python
"""Pass 0 — scene outline prompt + thin-timeline view.

Pass 0 ingests a compressed view of the timeline (the prose ``summary`` field is
dropped per the spec; every other field stays) plus subtitles, and asks the LLM
to produce ``scene_markers.json`` matching the schema in
:mod:`app.pipeline.stage_2.scene_markers`.
"""

from __future__ import annotations

from app.pipeline.common.script_contract import (
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from app.pipeline.stage_2.timeline import normalize_inline_text


def _thin_visual_line(index: int, segment: dict[str, object]) -> str:
    seg_id = str(segment.get("id") or f"visual:{index + 1:03d}")
    start = str(segment["start"])
    end = str(segment["end"])
    chars = segment.get("characters") or []
    chars_str = ", ".join(normalize_inline_text(c) for c in chars if normalize_inline_text(c)) or "-"
    ocr = normalize_inline_text(segment.get("ocr_text")) or "-"
    return f"{seg_id} | {start}-{end} | chars: {chars_str} | ocr: {ocr}"


def _thin_subtitle_line(subtitle: dict[str, object]) -> str | None:
    text = normalize_inline_text(subtitle.get("text"))
    if not text:
        return None
    start_raw = subtitle["start"]
    end_raw = subtitle["end"]
    if isinstance(start_raw, (int, float)):
        start = seconds_to_timestamp(float(start_raw))
    else:
        start = str(start_raw)
    if isinstance(end_raw, (int, float)):
        end = seconds_to_timestamp(float(end_raw))
    else:
        end = str(end_raw)
    speaker = normalize_inline_text(subtitle.get("speaker"))
    body = f"{speaker}: {text}" if speaker else text
    return f"SUB | {start}-{end} | {body}"


def render_thin_timeline(
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
) -> str:
    """Compact one-line-per-item view, lossless except for the visual `summary`."""
    lines: list[tuple[float, int, str]] = []
    for index, segment in enumerate(visual_segments):
        start_s = timestamp_to_seconds(str(segment["start"]))
        lines.append((start_s, 0, _thin_visual_line(index, segment)))
    for subtitle in subtitles:
        raw = subtitle["start"]
        start_s = float(raw) if isinstance(raw, (int, float)) else timestamp_to_seconds(str(raw))
        thin = _thin_subtitle_line(subtitle)
        if thin is None:
            continue
        lines.append((start_s, 1, thin))
    lines.sort(key=lambda t: (t[0], t[1]))
    return "\n".join(line for _, _, line in lines)


def build_outline_prompt(
    *,
    thin_timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
) -> str:
    """Assemble the Pass 0 prompt that asks the LLM for scene_markers.json."""
    movie_label = movie_title.strip() or "Unknown movie"
    sections: list[str] = []

    sections.append(
        "# Task\n"
        f"You are reading a compressed timeline of the movie {movie_label}. Your job is to "
        "produce a JSON document describing the movie's scene structure — the SCAFFOLDING that a "
        "downstream digester will use to write the plot digest, and that an editor will use to find "
        "footage. Quality of every downstream step depends on the accuracy of this scaffold."
    )

    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            f"# Synopsis for {movie_label}\n"
            "Authoritative for character names, relationships, and overall arc. "
            "May reference off-screen plot points — those are fine here (Pass 0 only); "
            "downstream passes will not invent footage from them.\n"
            "<<<SYNOPSIS_START>>>\n"
            f"{synopsis_text.strip()}\n"
            "<<<SYNOPSIS_END>>>"
        )

    sections.append(
        "# Compressed timeline (thin view)\n"
        "Every visual_segment is represented once. The prose `summary` field has been removed "
        "to save space — use characters, OCR text, and subtitle dialogue to infer what is happening.\n"
        "<<<THIN_TIMELINE_START>>>\n"
        f"{thin_timeline_text.strip()}\n"
        "<<<THIN_TIMELINE_END>>>"
    )

    sections.append(
        "# Output format: scene_markers.json\n"
        "Return ONE JSON object with two keys: `character_glossary` and `scenes`. No prose, no "
        "code fences, no comments.\n\n"
        "## character_glossary (array)\n"
        "One entry per important on-screen character (max 10). Each entry:\n"
        "- `original_name`: the character's name as it appears in the movie\n"
        "- `role`: one of `protagonist | antagonist | ally | victim | mentor | rival | minor`\n"
        "- `first_seen_scene`: the `id` of the scene where they first appear (see scenes below)\n\n"
        "## scenes (array of 15-25 entries)\n"
        "Each entry:\n"
        "- `id`: `scene:NN` (zero-padded sequential, starting at 01)\n"
        "- `label`: one-line Chinese label (max 20 chars)\n"
        "- `act_tag`: EXACTLY one of `HOOK`, `SETUP`, `ESCALATION`, `CLIMAX`, `RESOLUTION`, `CLOSING`\n"
        "- `visual_id_range`: `[\"visual:NNN\", \"visual:MMM\"]` (inclusive, first and last visual_segment in the scene)\n"
        "- `time_range`: `[\"HH:MM:SS.SSS\", \"HH:MM:SS.SSS\"]` (matching the visual_id_range's times)\n"
        "- `hook`: one-line description of why this scene matters\n\n"
        "## Hard rules\n"
        "- Every visual_segment must fall into exactly ONE scene. No gaps. No overlaps.\n"
        "- Exactly one scene tagged `HOOK` — the strongest opening candidate (not necessarily the first scene).\n"
        "- At least 3 scenes tagged `CLIMAX` — the decisive confrontation can span multiple scenes.\n"
        "- 15 to 25 scenes total. Shorter movies get fewer; epics get more.\n"
        "- The act_tag distribution should roughly match: HOOK ~3-5% of runtime, SETUP 15-20%, "
        "ESCALATION 25-30%, CLIMAX 35-40%, RESOLUTION 10-15%, CLOSING 2-4%.\n"
        "- Do NOT invent scenes that have no visual_segments backing them.\n"
        "- Do NOT output anything other than the JSON object."
    )

    return "\n\n".join(sections).rstrip() + "\n"
```

- [ ] **Step 4: Run the tests and verify they pass**

```
python -m pytest tests/pipeline/test_pass_0_outline.py -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```
git add app/pipeline/stage_2/pass_0_outline.py tests/pipeline/test_pass_0_outline.py
git commit -m "feat: add Pass 0 outline prompt builder and thin-timeline view"
```

---

## Task 7: Make `build_digest_prompt` consume `scene_markers` with act-weighted beat targets

This is the behaviour change for Pass 1 single mode. The function gains a new optional `scene_markers` parameter; when provided, the prompt is restructured to require beats organized by scene, with strict per-tag beat counts. Backward compat: when `scene_markers` is None, the old prompt structure is produced.

**Files:**
- Modify: `app/pipeline/stage_2/pass_1_digest_single.py`
- Test: `tests/pipeline/test_pass_1_digest_single.py` (new)
- Test: `tests/pipeline/test_stage_2_build_prompt.py` (existing test must still pass)

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_pass_1_digest_single.py`:

```python
from __future__ import annotations

from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument


def _make_scene(scene_id: str, act_tag: str, vid_start: str, vid_end: str) -> SceneMarker:
    return SceneMarker(
        id=scene_id, label="x", act_tag=act_tag,
        visual_id_range=(vid_start, vid_end),
        time_range=("00:00:00.000", "00:00:01.000"),
        hook="x",
    )


def test_digest_prompt_without_scene_markers_uses_legacy_flat_structure() -> None:
    prompt = build_digest_prompt(
        timeline_text="[VISUAL ...] visual:001 | x",
        movie_title="Demo",
    )
    # The legacy "30-50 beats in chronological order" instruction is still present
    # when no scene markers are provided.
    assert "30-50" in prompt or "30 to 50" in prompt
    assert "Plot Beats" in prompt or "剧情脉络" in prompt


def test_digest_prompt_with_scene_markers_uses_scene_structure_and_act_targets() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[
            {"original_name": "Hero", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        scenes=[
            _make_scene("scene:01", "HOOK", "visual:001", "visual:010"),
            _make_scene("scene:02", "SETUP", "visual:011", "visual:030"),
            _make_scene("scene:03", "CLIMAX", "visual:031", "visual:050"),
        ],
    )
    prompt = build_digest_prompt(
        timeline_text="[VISUAL ...] visual:001 | x",
        movie_title="Demo",
        scene_markers=doc,
    )
    # Per-tag beat targets must appear.
    assert "HOOK" in prompt and "1-2" in prompt  # tag + beat range
    assert "CLIMAX" in prompt and "4-6" in prompt
    # Scene structure is enforced.
    assert "scene:01" in prompt and "scene:02" in prompt and "scene:03" in prompt
    # Character glossary is injected.
    assert "Hero" in prompt
    # The legacy "30-50" instruction is REPLACED, not appended.
    assert "30-50" not in prompt


def test_digest_prompt_with_scene_markers_drops_legacy_no_gap_warning_for_skips() -> None:
    """When scene markers are supplied, every scene must be covered — no SKIP."""
    doc = SceneMarkersDocument(
        character_glossary=[],
        scenes=[_make_scene("scene:01", "SETUP", "visual:001", "visual:010")],
    )
    prompt = build_digest_prompt(
        timeline_text="[VISUAL ...] visual:001 | x",
        scene_markers=doc,
    )
    # No instruction to SKIP empty stretches when scenes are explicit.
    assert "SKIP it rather than inventing" not in prompt
    # Instead: every scene must have at least 1 beat.
    assert "every scene" in prompt.lower() or "each scene" in prompt.lower()
```

- [ ] **Step 2: Run the test and verify it fails**

```
python -m pytest tests/pipeline/test_pass_1_digest_single.py -q
```

Expected: tests fail because `build_digest_prompt` does not yet accept a `scene_markers` kwarg.

- [ ] **Step 3: Update `pass_1_digest_single.py` to accept scene markers**

Modify `build_digest_prompt` in `app/pipeline/stage_2/pass_1_digest_single.py`:

```python
"""Pass 1 single-mode digest prompt builder."""

from __future__ import annotations

from app.pipeline.stage_2.scene_markers import SceneMarkersDocument

# Per-tag beat targets — these are the act-balance safeguards.
_ACT_BEAT_TARGETS: tuple[tuple[str, str], ...] = (
    ("HOOK",       "1-2"),
    ("SETUP",      "1-2"),
    ("ESCALATION", "2-3"),
    ("CLIMAX",     "4-6"),
    ("RESOLUTION", "2-3"),
    ("CLOSING",    "1"),
)


def _scene_anchored_beats_section(scene_markers: SceneMarkersDocument) -> str:
    targets_table = "\n".join(
        f"- `{tag}`: {beats} beats per scene" for tag, beats in _ACT_BEAT_TARGETS
    )

    glossary_lines = "\n".join(
        f"- {entry.get('original_name', '?')}: {entry.get('role', '?')} (first seen in {entry.get('first_seen_scene', '?')})"
        for entry in scene_markers.character_glossary
    ) or "- (none provided)"

    scene_lines = "\n".join(
        f"- {s.id} [{s.act_tag}] {s.visual_id_range[0]}–{s.visual_id_range[1]}: {s.label}"
        for s in scene_markers.scenes
    )

    return (
        "## 角色表 (Character Table) — already supplied\n"
        "The Pass 0 character glossary below is authoritative for names. Use it; do not invent "
        "new characters or rename existing ones in the digest:\n"
        f"{glossary_lines}\n\n"
        "## 剧情脉络 (Plot Beats) — organize BY SCENE\n"
        "Pass 0 has already identified the scene structure. Write beats GROUPED UNDER each scene's "
        "id, in scene order. Every scene listed below must have at least one beat — no scene "
        "may be skipped, because every scene's footage exists in the timeline.\n\n"
        "**Per-tag beat targets (HARD — count your beats against these):**\n"
        f"{targets_table}\n\n"
        "Higher beat counts on CLIMAX-tagged scenes is mandatory; this is the scaffolding that lets "
        "the downstream story script keep ACT 3 longer than ACT 2 (the act-balance invariant in "
        "`styles/niu-shu.md` §4.0). Compress SETUP brutally; linger on CLIMAX.\n\n"
        "**For EACH beat under a scene:**\n"
        "- 镜头: Comma-separated visual_segment IDs from THAT scene's `visual_id_range` ONLY "
        "(e.g. `visual:031, visual:033-035`). REQUIRED. Do not cite IDs outside the scene.\n"
        "- 事件: What happens (2-3 sentences). Describe ONLY what the cited segments show.\n"
        "- 因果: Why this happens / what it causes.\n"
        "- 台词: Key dialogue if any (quote verbatim).\n"
        "- 情绪: Emotional register.\n\n"
        "## Scene list (write beats under each, in order):\n"
        f"{scene_lines}"
    )


def build_digest_prompt(
    *,
    timeline_text: str,
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_rules_text: str | None = None,
    scene_markers: SceneMarkersDocument | None = None,
    target_minutes: float = 12.0,
) -> str:
    """Assemble the Pass 1 digest prompt.

    When ``scene_markers`` is provided, the digest is required to be organized by scene with
    strict per-tag beat targets (recommended path). Without scene markers, the legacy flat
    "30-50 beats in chronological order" structure is used (backward compat).
    """
    movie_label = movie_title.strip() or "Unknown movie"
    use_scenes = scene_markers is not None and len(scene_markers.scenes) > 0

    sections: list[str] = []

    sections.append(
        "# Task\n"
        "You are a movie analyst preparing a detailed plot digest for a movie REVIEWER.\n"
        "The reviewer will use your digest to write an entertaining, detail-rich "
        f"movie retelling script (~{target_minutes:.0f} minutes of spoken narration).\n\n"
        "Your job is to extract EVERYTHING the reviewer needs — not just the bare plot, "
        "but the moments that make this movie interesting, funny, tense, absurd, or "
        "emotionally powerful to talk about.\n\n"
        "A good digest preserves:\n"
        "- The full plot with causal reasoning (WHY things happen, not just WHAT)\n"
        "- Memorable dialogue worth quoting verbatim\n"
        "- Visually striking or absurd moments\n"
        "- Ironic situations, satisfying revenge, and emotional gut-punches\n"
        "- Character dynamics, power shifts, and betrayals\n"
        "- Action set-pieces with enough detail to narrate vividly\n"
        "- The actual ending (no spoiler avoidance)\n\n"
        "A bad digest is a dry plot summary that loses all the flavor."
    )

    if synopsis_text is not None and synopsis_text.strip():
        sections.append(
            f"# Synopsis for {movie_label}\n"
            "Use this as authoritative context for character names, relationships, "
            "and overall story arc.\n"
            "<<<SYNOPSIS_START>>>\n"
            f"{synopsis_text.strip()}\n"
            "<<<SYNOPSIS_END>>>"
        )

    if genre_rules_text is not None and genre_rules_text.strip():
        sections.append(
            "# Genre focus\n"
            "Read this before the timeline. It tells you which beats deserve "
            "extra detail in the digest and which can be compressed.\n"
            "<<<GENRE_RULES_START>>>\n"
            f"{genre_rules_text.strip()}\n"
            "<<<GENRE_RULES_END>>>"
        )

    sections.append(
        "# Chronological Movie Timeline\n"
        "This timeline contains VISUAL segments (what happens on screen) and "
        "SUBTITLE segments (what characters say). Read it carefully to "
        "reconstruct the full movie.\n"
        "<<<MOVIE_TIMELINE_START>>>\n"
        f"{timeline_text.strip()}\n"
        "<<<MOVIE_TIMELINE_END>>>"
    )

    if use_scenes:
        output_format = (
            f"# Output Format: Plot Digest for {movie_label}\n"
            "Write the entire digest in Chinese. Be detailed — the reviewer cannot "
            "watch the movie, so your digest is their only source.\n\n"
            + _scene_anchored_beats_section(scene_markers)
            + "\n\n"
            "## 权力结构 (Power Map)\n"
            "Describe who controls what, who deceives whom, and how power shifts.\n\n"
            "## 名场面 (Reviewable Moments) — 10-15 entries\n"
            "Movie-reviewer gold: striking images, ironic situations, satisfying revenge, "
            "shocking reveals, action choreography, emotional gut-punches. For each, list "
            "supporting `镜头: visual:NNN` ids and 2-4 sentences of vivid detail.\n\n"
            "## 核心矛盾 (Core Conflict & Themes)\n"
            "- What is this movie really about? (1-2 sentences)\n"
            "- What is the central irony or contradiction?\n\n"
            "## 结局 (Full Ending)\n"
            "Describe the climax resolution, every main character's final fate, and the "
            "emotional aftertaste."
        )
    else:
        # Legacy structure preserved for backward compat (no scene markers supplied).
        output_format = (
            f"# Output Format: Plot Digest for {movie_label}\n"
            "Write the entire digest in Chinese. Be detailed — the reviewer cannot "
            "watch the movie, so your digest is their only source.\n\n"
            "## 角色表 (Character Table)\n"
            "For each important character (max 8-10), provide:\n"
            "- 原名: Original name from the movie\n"
            "- 身份: Role (protagonist / antagonist / ally / victim / etc.)\n"
            "- 关系: Key relationships to other characters\n"
            "- 动机: What they want\n"
            "- 结局: What ultimately happens to them\n"
            "- 性格特点: 1-2 defining personality traits\n\n"
            "## 权力结构 (Power Map)\n"
            "Describe who controls what, who deceives whom, and how power shifts "
            "throughout the movie. Who is pretending? Who is trapped? Who holds "
            "the real leverage?\n\n"
            "## 剧情脉络 (Plot Beats)\n"
            "List 30-50 major story beats in chronological order. For EACH beat:\n"
            "- 镜头: Comma-separated visual_segment IDs from the timeline that show this beat "
            "(e.g. `visual:031, visual:033-035`). REQUIRED. The reviewer uses these IDs to ground "
            "every sentence — a beat without 镜头 cannot be safely retold.\n"
            "- 事件: What happens (2-3 sentences, vivid and specific). Describe ONLY what the cited "
            "visual segments actually show; do not extrapolate beyond them.\n"
            "- 因果: Why this happens / what it causes (the causal chain)\n"
            "- 台词: Key dialogue if any (quote the most impactful lines verbatim)\n"
            "- 情绪: Emotional register (tension / humor / horror / tenderness / etc.)\n\n"
            "IMPORTANT: Be detailed enough that someone who has never seen the movie "
            "can retell the FULL story. Each major scene transition should be a "
            "separate beat. Do NOT merge multiple scenes into one vague beat. "
            "If a stretch of the timeline has no clear footage, SKIP it rather than inventing a beat.\n\n"
            "## 名场面 (Reviewable Moments)\n"
            "List 10-15 moments a movie reviewer would love to describe. For each moment, "
            "include the supporting visual_segment IDs (镜头: visual:NNN, ...) followed by "
            "2-4 sentences of vivid detail describing ONLY what those segments show.\n\n"
            "## 核心矛盾 (Core Conflict & Themes)\n"
            "- What is this movie really about? (1-2 sentences)\n"
            "- What is the central irony or contradiction?\n\n"
            "## 结局 (Full Ending)\n"
            "Describe the climax resolution, every main character's final fate, and the "
            "emotional aftertaste."
        )

    sections.append(output_format)
    return "\n\n".join(sections).rstrip() + "\n"
```

- [ ] **Step 4: Run the new and existing tests**

```
python -m pytest tests/pipeline/test_pass_1_digest_single.py tests/pipeline/test_stage_2_build_prompt.py -q
```

Expected: all pass. The existing test `test_build_digest_prompt_injects_genre_rules_before_timeline` still passes because it calls `build_digest_prompt` without `scene_markers` and asserts on the genre-rules wiring (which is preserved).

- [ ] **Step 5: Commit**

```
git add app/pipeline/stage_2/pass_1_digest_single.py tests/pipeline/test_pass_1_digest_single.py
git commit -m "feat: Pass 1 digest consumes scene_markers with act-weighted beat targets"
```

---

## Task 8: Implement Pass 1 chunked mode

A separate orchestrator that, given `scene_markers`, produces three prompts (front-buildup, climax, tail) and a helper to concatenate the three LLM replies into a single `plot_digest.txt`. Each sub-prompt is built by REUSING `build_digest_prompt` from Task 7 with a filtered timeline and a scene-markers document containing only that chunk's scenes — no duplication of prompt construction logic.

**Files:**
- Create: `app/pipeline/stage_2/pass_1_digest_chunked.py`
- Test: `tests/pipeline/test_pass_1_digest_chunked.py`

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_pass_1_digest_chunked.py`:

```python
from __future__ import annotations

from app.pipeline.stage_2.pass_1_digest_chunked import (
    CHUNK_ORDER,
    build_chunked_digest_prompts,
    concatenate_digest_chunks,
    partition_scenes,
)
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument


def _make_scene(scene_id: str, act_tag: str, vid_start: str, vid_end: str) -> SceneMarker:
    return SceneMarker(
        id=scene_id, label="x", act_tag=act_tag,
        visual_id_range=(vid_start, vid_end),
        time_range=("00:00:00.000", "00:00:01.000"),
        hook="x",
    )


def test_partition_scenes_groups_by_chunk_order() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[],
        scenes=[
            _make_scene("scene:01", "HOOK",       "visual:001", "visual:005"),
            _make_scene("scene:02", "SETUP",      "visual:006", "visual:015"),
            _make_scene("scene:03", "ESCALATION", "visual:016", "visual:030"),
            _make_scene("scene:04", "CLIMAX",     "visual:031", "visual:050"),
            _make_scene("scene:05", "CLIMAX",     "visual:051", "visual:060"),
            _make_scene("scene:06", "RESOLUTION", "visual:061", "visual:070"),
            _make_scene("scene:07", "CLOSING",    "visual:071", "visual:075"),
        ],
    )

    front, climax, tail = partition_scenes(doc)
    assert [s.id for s in front] == ["scene:01", "scene:02", "scene:03"]
    assert [s.id for s in climax] == ["scene:04", "scene:05"]
    assert [s.id for s in tail] == ["scene:06", "scene:07"]


def test_build_chunked_digest_prompts_returns_three_prompts_each_with_chunk_label() -> None:
    doc = SceneMarkersDocument(
        character_glossary=[
            {"original_name": "Hero", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        scenes=[
            _make_scene("scene:01", "SETUP",  "visual:001", "visual:010"),
            _make_scene("scene:02", "CLIMAX", "visual:011", "visual:020"),
            _make_scene("scene:03", "CLOSING", "visual:021", "visual:025"),
        ],
    )
    visual_segments = [
        {"id": f"visual:{i:03d}", "start": f"00:00:{i:02d}.000",
         "end": f"00:00:{i+1:02d}.000", "summary": "x",
         "ocr_text": "", "characters": []}
        for i in range(1, 26)
    ]

    prompts = build_chunked_digest_prompts(
        scene_markers=doc, visual_segments=visual_segments, subtitles=[],
        movie_title="Demo",
    )
    assert set(prompts.keys()) == set(CHUNK_ORDER)
    # Each chunk's prompt contains its own scene ids and not other chunks'.
    assert "scene:01" in prompts["front"]
    assert "scene:02" not in prompts["front"]
    assert "scene:02" in prompts["climax"]
    assert "scene:03" not in prompts["climax"]
    # Character glossary appears in every chunk (no name drift).
    for prompt in prompts.values():
        assert "Hero" in prompt
    # Per-tag beat targets present in every chunk (delegated to single-mode builder).
    for prompt in prompts.values():
        assert "CLIMAX" in prompt and "4-6" in prompt


def test_concatenate_digest_chunks_preserves_chunk_order() -> None:
    replies = {
        "tail":   "## tail content\n",
        "front":  "## front content\n",
        "climax": "## climax content\n",
    }
    out = concatenate_digest_chunks(replies)
    front_pos = out.index("front content")
    climax_pos = out.index("climax content")
    tail_pos = out.index("tail content")
    assert front_pos < climax_pos < tail_pos
```

- [ ] **Step 2: Run the test and verify it fails**

```
python -m pytest tests/pipeline/test_pass_1_digest_chunked.py -q
```

Expected: ImportError on `pass_1_digest_chunked`.

- [ ] **Step 3: Implement `pass_1_digest_chunked.py`**

```python
"""Pass 1 chunked-mode digest orchestrator.

Produces three sub-prompts when invoked, each delegating to
:func:`app.pipeline.stage_2.pass_1_digest_single.build_digest_prompt` with a
filtered scene-markers document and timeline slice. No prompt-construction
logic lives here — only partitioning and orchestration.
"""

from __future__ import annotations

from typing import Mapping

from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument
from app.pipeline.stage_2.timeline import render_timeline

CHUNK_ORDER: tuple[str, ...] = ("front", "climax", "tail")

# Which act tags belong to each chunk.
_FRONT_TAGS = frozenset({"HOOK", "SETUP", "ESCALATION"})
_CLIMAX_TAGS = frozenset({"CLIMAX"})
_TAIL_TAGS = frozenset({"RESOLUTION", "CLOSING"})


def partition_scenes(
    scene_markers: SceneMarkersDocument,
) -> tuple[list[SceneMarker], list[SceneMarker], list[SceneMarker]]:
    front: list[SceneMarker] = []
    climax: list[SceneMarker] = []
    tail: list[SceneMarker] = []
    for scene in scene_markers.scenes:
        if scene.act_tag in _FRONT_TAGS:
            front.append(scene)
        elif scene.act_tag in _CLIMAX_TAGS:
            climax.append(scene)
        elif scene.act_tag in _TAIL_TAGS:
            tail.append(scene)
        else:  # pragma: no cover — scene_markers.load enforces tag membership
            raise ValueError(f"unexpected act_tag {scene.act_tag!r} in {scene.id!r}")
    return front, climax, tail


def _visual_id_to_int(visual_id: str) -> int:
    return int(visual_id.split(":", 1)[1])


def _filter_visuals_to_scenes(
    visual_segments: list[dict[str, object]],
    scenes: list[SceneMarker],
) -> list[dict[str, object]]:
    if not scenes:
        return []
    allowed_ranges = [
        (_visual_id_to_int(s.visual_id_range[0]), _visual_id_to_int(s.visual_id_range[1]))
        for s in scenes
    ]
    out: list[dict[str, object]] = []
    for index, seg in enumerate(visual_segments):
        seg_id = str(seg.get("id") or f"visual:{index + 1:03d}")
        seg_num = _visual_id_to_int(seg_id)
        if any(lo <= seg_num <= hi for lo, hi in allowed_ranges):
            out.append(seg)
    return out


def _filter_subtitles_to_time_span(
    subtitles: list[dict[str, object]],
    scenes: list[SceneMarker],
) -> list[dict[str, object]]:
    if not scenes:
        return []
    from app.pipeline.common.script_contract import timestamp_to_seconds
    spans = [(timestamp_to_seconds(s.time_range[0]), timestamp_to_seconds(s.time_range[1])) for s in scenes]
    out: list[dict[str, object]] = []
    for sub in subtitles:
        raw = sub["start"]
        start_s = float(raw) if isinstance(raw, (int, float)) else timestamp_to_seconds(str(raw))
        if any(lo <= start_s <= hi for lo, hi in spans):
            out.append(sub)
    return out


def build_chunked_digest_prompts(
    *,
    scene_markers: SceneMarkersDocument,
    visual_segments: list[dict[str, object]],
    subtitles: list[dict[str, object]],
    movie_title: str = "",
    synopsis_text: str | None = None,
    genre_rules_text: str | None = None,
    target_minutes: float = 12.0,
) -> dict[str, str]:
    """Build the three chunked Pass 1 prompts. Returns a dict keyed by CHUNK_ORDER."""
    front, climax, tail = partition_scenes(scene_markers)
    chunks: list[tuple[str, list[SceneMarker]]] = [
        ("front", front), ("climax", climax), ("tail", tail),
    ]
    out: dict[str, str] = {}
    for label, scenes in chunks:
        chunk_doc = SceneMarkersDocument(
            character_glossary=scene_markers.character_glossary,
            scenes=scenes,
        )
        chunk_visuals = _filter_visuals_to_scenes(visual_segments, scenes)
        chunk_subtitles = _filter_subtitles_to_time_span(subtitles, scenes)
        chunk_timeline = render_timeline(chunk_visuals, chunk_subtitles) if scenes else ""
        chunk_movie_title = f"{movie_title} (chunk: {label})" if movie_title else f"(chunk: {label})"
        out[label] = build_digest_prompt(
            timeline_text=chunk_timeline,
            movie_title=chunk_movie_title,
            synopsis_text=synopsis_text,
            genre_rules_text=genre_rules_text,
            scene_markers=chunk_doc,
            target_minutes=target_minutes,
        )
    return out


def concatenate_digest_chunks(replies: Mapping[str, str]) -> str:
    """Join the three chunked-digest replies in canonical CHUNK_ORDER."""
    parts: list[str] = []
    for label in CHUNK_ORDER:
        body = replies.get(label, "").strip()
        if body:
            parts.append(body)
    return "\n\n".join(parts) + ("\n" if parts else "")
```

- [ ] **Step 4: Run the tests and verify they pass**

```
python -m pytest tests/pipeline/test_pass_1_digest_chunked.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```
git add app/pipeline/stage_2/pass_1_digest_chunked.py tests/pipeline/test_pass_1_digest_chunked.py
git commit -m "feat: add Pass 1 chunked-mode orchestrator (front/climax/tail)"
```

---

## Task 9: Implement deterministic post-validation

Reads `script.txt`, `visual_segments.json`, and `scene_markers.json`. Walks every `<refs>` tag, verifies each cited `visual:NNN` exists and overlaps the cited beat's scene's `visual_id_range`. Emits `hallucination_report.json`. **Flag-only: never mutates `script.txt`.**

**Files:**
- Create: `app/pipeline/stage_2/post_validate.py`
- Test: `tests/pipeline/test_post_validate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_post_validate.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.stage_2.post_validate import (
    PostValidationReport,
    validate_script,
)
from app.pipeline.stage_2.scene_markers import SceneMarker, SceneMarkersDocument


def _make_scene(scene_id: str, vid_start: str, vid_end: str) -> SceneMarker:
    return SceneMarker(
        id=scene_id, label="x", act_tag="SETUP",
        visual_id_range=(vid_start, vid_end),
        time_range=("00:00:00.000", "00:00:10.000"),
        hook="x",
    )


def _scene_doc() -> SceneMarkersDocument:
    return SceneMarkersDocument(
        character_glossary=[],
        scenes=[
            _make_scene("scene:01", "visual:001", "visual:010"),
            _make_scene("scene:02", "visual:011", "visual:020"),
        ],
    )


def _visual_ids(ids: list[str]) -> set[str]:
    return set(ids)


def test_clean_script_produces_zero_flags() -> None:
    script = (
        "<refs>visual:001</refs>\n"
        "故事开场，主角进入校园。\n"
        "\n"
        "<refs>visual:003-005</refs>\n"
        "他遇到了里香。\n"
    )
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids([f"visual:{i:03d}" for i in range(1, 21)]),
    )
    assert isinstance(report, PostValidationReport)
    assert report.total_sentences == 2
    assert report.flagged == []


def test_flags_sentence_with_missing_refs_tag() -> None:
    script = "<refs>visual:001</refs>\n故事开场。\n这一句没有 refs。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids(["visual:001"]),
    )
    flagged_issues = [f.issue for f in report.flagged]
    assert any("missing <refs>" in issue.lower() for issue in flagged_issues)


def test_flags_ref_to_non_existent_visual_id() -> None:
    script = "<refs>visual:999</refs>\n这一句引用了不存在的 ID。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids(["visual:001"]),
    )
    assert len(report.flagged) == 1
    assert "visual:999" in report.flagged[0].issue
    assert "not in visual_segments" in report.flagged[0].issue.lower()


def test_flags_ref_outside_any_scene_visual_id_range() -> None:
    # visual:030 exists but is outside both scenes' ranges (which are 001-010 and 011-020).
    script = "<refs>visual:030</refs>\n这一句的 ID 在所有 scene 之外。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids([f"visual:{i:03d}" for i in range(1, 31)]),
    )
    assert len(report.flagged) == 1
    assert "scene" in report.flagged[0].issue.lower()


def test_range_expansion_recognises_dash_form() -> None:
    # visual:003-005 should expand to 003, 004, 005 and all be checked.
    script = "<refs>visual:003-005</refs>\n这一段引用了一个范围。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids([f"visual:{i:03d}" for i in range(1, 11)]),
    )
    assert report.flagged == []


def test_report_writes_json_file_with_expected_schema(tmp_path: Path) -> None:
    script = "<refs>visual:999</refs>\n这一句引用了不存在的 ID。\n"
    report = validate_script(
        script_text=script,
        scene_markers=_scene_doc(),
        all_visual_ids=_visual_ids(["visual:001"]),
    )
    out = tmp_path / "hallucination_report.json"
    report.write_json(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["total_sentences"] == 1
    assert len(payload["flagged"]) == 1
    flagged = payload["flagged"][0]
    assert "line" in flagged and "sentence" in flagged and "refs" in flagged and "issue" in flagged
```

- [ ] **Step 2: Run the test and verify it fails**

```
python -m pytest tests/pipeline/test_post_validate.py -q
```

Expected: ImportError.

- [ ] **Step 3: Implement `post_validate.py`**

```python
"""Stage 2 post-validation: deterministic ref-tag verification.

Flag-only: never mutates ``script.txt``. Produces ``hallucination_report.json``
that the human reviewer triages before TTS.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from app.pipeline.stage_2.scene_markers import SceneMarkersDocument

_REFS_LINE_RE = re.compile(r"<refs>([^<]*)</refs>")
_SENTENCE_END_RE = re.compile(r"[。！？!?]\s*$")
_VISUAL_ID_RE = re.compile(r"visual:(\d+)(?:-(\d+))?")
_ACT_HEADER_RE = re.compile(r"^\[(TITLE|HOOK|ACT [1-4][^\]]*|CLOSING)\]\s*$")


@dataclass(frozen=True)
class FlaggedSentence:
    line: int
    sentence: str
    refs: list[str]
    issue: str


@dataclass
class PostValidationReport:
    total_sentences: int
    flagged: list[FlaggedSentence] = field(default_factory=list)

    def write_json(self, path: Path) -> None:
        payload = {
            "total_sentences": self.total_sentences,
            "flagged": [asdict(f) for f in self.flagged],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _expand_visual_refs(refs_body: str) -> list[str]:
    out: list[str] = []
    for match in _VISUAL_ID_RE.finditer(refs_body):
        lo = int(match.group(1))
        hi = int(match.group(2)) if match.group(2) else lo
        for n in range(lo, hi + 1):
            out.append(f"visual:{n:03d}")
    return out


def _scene_for_ref(ref: str, scene_markers: SceneMarkersDocument) -> str | None:
    n = int(ref.split(":", 1)[1])
    for scene in scene_markers.scenes:
        lo = int(scene.visual_id_range[0].split(":", 1)[1])
        hi = int(scene.visual_id_range[1].split(":", 1)[1])
        if lo <= n <= hi:
            return scene.id
    return None


def validate_script(
    *,
    script_text: str,
    scene_markers: SceneMarkersDocument,
    all_visual_ids: Iterable[str],
) -> PostValidationReport:
    """Walk every sentence and verify its <refs> tags.

    A "sentence" is any non-blank, non-header line that ends with a Chinese or
    English sentence-terminator (。！？.!?). Lines that don't end with a
    terminator are skipped (titles, fragments) — the spec's hard rules apply only
    to narration sentences.
    """
    visual_ids_set = set(all_visual_ids)
    flagged: list[FlaggedSentence] = []
    total_sentences = 0

    lines = script_text.split("\n")
    last_refs: list[str] | None = None
    last_refs_line: int | None = None
    for index, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            last_refs = None
            last_refs_line = None
            continue
        if _ACT_HEADER_RE.match(line):
            last_refs = None
            last_refs_line = None
            continue
        refs_match = _REFS_LINE_RE.match(line)
        if refs_match:
            last_refs = _expand_visual_refs(refs_match.group(1))
            last_refs_line = index
            continue

        # Not refs, not header, not blank → this is candidate narration.
        if not _SENTENCE_END_RE.search(line):
            continue

        total_sentences += 1
        sentence_refs = last_refs if last_refs is not None else []

        if last_refs is None:
            flagged.append(FlaggedSentence(
                line=index, sentence=line, refs=[],
                issue="missing <refs> tag for this sentence",
            ))
        else:
            for ref in sentence_refs:
                if ref not in visual_ids_set:
                    flagged.append(FlaggedSentence(
                        line=index, sentence=line, refs=list(sentence_refs),
                        issue=f"{ref} not in visual_segments",
                    ))
                    break
            else:
                # All refs exist; check they overlap at least one scene.
                if scene_markers.scenes:
                    scenes_hit = {_scene_for_ref(ref, scene_markers) for ref in sentence_refs}
                    scenes_hit.discard(None)
                    if not scenes_hit:
                        flagged.append(FlaggedSentence(
                            line=index, sentence=line, refs=list(sentence_refs),
                            issue="refs fall outside every scene's visual_id_range",
                        ))

        last_refs = None
        last_refs_line = None

    return PostValidationReport(total_sentences=total_sentences, flagged=flagged)
```

- [ ] **Step 4: Run the tests and verify they pass**

```
python -m pytest tests/pipeline/test_post_validate.py -q
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add app/pipeline/stage_2/post_validate.py tests/pipeline/test_post_validate.py
git commit -m "feat: add deterministic post-validation (hallucination_report.json)"
```

---

## Task 10: CLI dispatcher — add `--outline` mode, wire scene_markers and chunked digest

Thinns `stage_2_build_prompt.py` to a dispatcher. Adds three modes via mutually-exclusive flags:
- `--outline`: build the Pass 0 prompt (`outline_prompt.txt`)
- `--digest`: build the Pass 1 prompt; when `--scene-markers <file>` is supplied, uses act-weighted structure; when `--chunked` is also supplied, writes three sibling files
- default (no flag): build the Pass 2 story prompt (unchanged from today's digest mode)

**Files:**
- Modify: `app/pipeline/stage_2_build_prompt.py`
- Test: `tests/pipeline/test_stage_2_build_prompt.py` (add new tests; existing tests stay green)

- [ ] **Step 1: Write the failing tests**

Append to `tests/pipeline/test_stage_2_build_prompt.py`:

```python
def test_main_builds_outline_prompt_when_outline_flag_set(tmp_path: Path) -> None:
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(json.dumps([
        {"start": "00:00:00.000", "end": "00:00:04.000", "summary": "x",
         "ocr_text": "", "characters": []}
    ]), encoding="utf-8")
    subtitles_txt_path = tmp_path / "subtitles.txt"
    subtitles_txt_path.write_text("[00:00:01.000 -> 00:00:02.000] hello\n", encoding="utf-8")

    output_path = tmp_path / "outline_prompt.txt"
    rc = main([
        "--outline",
        "--visual-segments", str(visual_segments_path),
        "--subtitles-txt", str(subtitles_txt_path),
        "--out", str(output_path),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    written = output_path.read_text(encoding="utf-8")
    assert "scene_markers.json" in written or "JSON" in written
    assert "CLIMAX" in written  # act-tag inventory must be in the prompt


def test_main_builds_chunked_digest_writes_three_files(tmp_path: Path) -> None:
    # Minimal valid scene_markers.json.
    scene_markers_path = tmp_path / "scene_markers.json"
    scene_markers_path.write_text(json.dumps({
        "character_glossary": [],
        "scenes": [
            {"id": "scene:01", "label": "a", "act_tag": "SETUP",
             "visual_id_range": ["visual:001", "visual:001"],
             "time_range": ["00:00:00.000", "00:00:04.000"], "hook": "a"},
            {"id": "scene:02", "label": "b", "act_tag": "CLIMAX",
             "visual_id_range": ["visual:002", "visual:002"],
             "time_range": ["00:00:04.000", "00:00:08.000"], "hook": "b"},
            {"id": "scene:03", "label": "c", "act_tag": "CLOSING",
             "visual_id_range": ["visual:003", "visual:003"],
             "time_range": ["00:00:08.000", "00:00:12.000"], "hook": "c"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(json.dumps([
        {"id": "visual:001", "start": "00:00:00.000", "end": "00:00:04.000",
         "summary": "x", "ocr_text": "", "characters": []},
        {"id": "visual:002", "start": "00:00:04.000", "end": "00:00:08.000",
         "summary": "y", "ocr_text": "", "characters": []},
        {"id": "visual:003", "start": "00:00:08.000", "end": "00:00:12.000",
         "summary": "z", "ocr_text": "", "characters": []},
    ]), encoding="utf-8")
    subtitles_txt_path = tmp_path / "subtitles.txt"
    subtitles_txt_path.write_text("", encoding="utf-8")

    out_path = tmp_path / "digest_prompt.txt"
    rc = main([
        "--digest", "--chunked",
        "--scene-markers", str(scene_markers_path),
        "--visual-segments", str(visual_segments_path),
        "--subtitles-txt", str(subtitles_txt_path),
        "--out", str(out_path),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    # Three sibling prompts written: digest_prompt.front.txt, digest_prompt.climax.txt, digest_prompt.tail.txt
    front = tmp_path / "digest_prompt.front.txt"
    climax = tmp_path / "digest_prompt.climax.txt"
    tail = tmp_path / "digest_prompt.tail.txt"
    assert front.is_file() and climax.is_file() and tail.is_file()
    assert "scene:01" in front.read_text(encoding="utf-8")
    assert "scene:02" in climax.read_text(encoding="utf-8")
    assert "scene:03" in tail.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the new tests and verify they fail**

```
python -m pytest tests/pipeline/test_stage_2_build_prompt.py -q
```

Expected: the two new tests fail (no `--outline` mode yet; no chunked support).

- [ ] **Step 3: Refactor `stage_2_build_prompt.py` into a dispatcher**

Replace the file contents end-to-end. The new file is a thin dispatcher; all builder logic lives in the subpackage. Key changes:
- Add `--outline`, `--chunked`, `--scene-markers` flags.
- Add `_run_outline`, update `_run_digest` to accept scene markers and chunked mode, and `_run_story` to accept scene markers (passed through to digest_text consumer in Task 11).

```python
"""Stage 2 CLI dispatcher: build the LLM prompt for the appropriate pass.

Three modes (mutually exclusive):

- ``--outline``           Pass 0 (scene outline)
- ``--digest``            Pass 1 (digest); add ``--chunked`` for the 3-call variant.
                          Add ``--scene-markers <path>`` to activate act-weighted beat targets.
- (default, no flag)      Pass 2 (story script).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from app.pipeline.common.script_contract import load_visual_segments
from app.pipeline.stage_2.pass_0_outline import build_outline_prompt, render_thin_timeline
from app.pipeline.stage_2.pass_1_digest_chunked import (
    CHUNK_ORDER,
    build_chunked_digest_prompts,
)
from app.pipeline.stage_2.pass_1_digest_single import build_digest_prompt
from app.pipeline.stage_2.pass_2_story import build_story_prompt
from app.pipeline.stage_2.scene_markers import (
    SceneMarkersDocument,
    load_scene_markers,
)
from app.pipeline.stage_2.timeline import (
    TimelineEntry,
    build_timeline_entries,
    load_subtitles,
    normalize_inline_text,
    parse_style_frontmatter,
    read_text_strict as _read_text,
    render_timeline,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-prompt",
        description="Stage 2: build the LLM prompt for movie script writing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--outline", action="store_true",
                      help="Build the Pass 0 outline prompt (scene_markers.json producer).")
    mode.add_argument("--digest", action="store_true",
                      help="Build the Pass 1 digest prompt.")
    # Default (no flag) is story mode.

    parser.add_argument("--chunked", action="store_true",
                        help="In --digest mode, build three sibling prompts "
                             "(front/climax/tail) instead of one.")
    parser.add_argument("--scene-markers", type=Path,
                        help="Pass 0 output. Activates scene-anchored, act-weighted beat "
                             "targets in --digest mode. Required when --chunked is set.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output path. In --chunked mode, sibling .front/.climax/.tail "
                             "files are written next to this path.")
    parser.add_argument("--movie-title", default="",
                        help="Optional movie title for prompt framing.")
    parser.add_argument("--target-minutes", type=float, default=None,
                        help="Target script length in minutes of spoken narration.")
    parser.add_argument("--synopsis", type=Path,
                        help="Optional synopsis markdown.")
    parser.add_argument("--visual-segments", type=Path,
                        help="Stage 1 visual_segments.json.")
    parser.add_argument("--subtitles-txt", type=Path,
                        help="Stage 1 subtitles.txt.")
    parser.add_argument("--style", type=Path,
                        help="Style markdown file. Required in story mode.")
    parser.add_argument("--genre",
                        help="Optional genre name. Loads styles/genres/<style>/<genre>.txt and "
                             "<genre>.rules.md when present.")
    parser.add_argument("--plot-digest", type=Path,
                        help="Pass 1 output. When provided in story mode, switches to digest mode.")
    return parser


def _resolve_optional(path: Path | None) -> Path | None:
    return path.expanduser().resolve() if path is not None else None


def _find_genre_asset(style_path: Path, genre: str, filename: str) -> Path | None:
    for parent in ("genres", "genre"):
        candidate = style_path.parent / parent / style_path.stem / filename
        if candidate.exists():
            return candidate
    return None


def _load_genre_rules_for_digest(style_path: Path | None, genre: str | None) -> str | None:
    if not (style_path and genre):
        return None
    rules_file = _find_genre_asset(style_path, genre, f"{genre}.rules.md")
    return _read_text(rules_file) if rules_file else None


def _run_outline(args) -> int:
    visual_path = _resolve_optional(args.visual_segments)
    subs_path = _resolve_optional(args.subtitles_txt)
    syn_path = _resolve_optional(args.synopsis)
    out_path = args.out.expanduser().resolve()

    if visual_path is None or subs_path is None:
        print("Error: --visual-segments and --subtitles-txt are required in --outline mode", file=sys.stderr)
        return 1
    if not visual_path.exists():
        print(f"Error: Visual segments not found: {visual_path}", file=sys.stderr)
        return 1
    if not subs_path.exists():
        print(f"Error: Subtitles not found: {subs_path}", file=sys.stderr)
        return 1

    visual_segments = load_visual_segments(visual_path)
    subtitles = load_subtitles(subs_path)
    thin = render_thin_timeline(visual_segments, subtitles)
    if not thin.strip():
        print("Error: The thin timeline is empty", file=sys.stderr)
        return 1

    synopsis_text = _read_text(syn_path) if syn_path else None
    prompt = build_outline_prompt(
        thin_timeline_text=thin,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt, encoding="utf-8")
    print(f"Generated outline prompt: {out_path}")
    print(f"  visual segments : {len(visual_segments)}")
    print(f"  subtitles       : {len(subtitles)}")
    return 0


def _run_digest(args) -> int:
    visual_path = _resolve_optional(args.visual_segments)
    subs_path = _resolve_optional(args.subtitles_txt)
    syn_path = _resolve_optional(args.synopsis)
    scene_path = _resolve_optional(args.scene_markers)
    style_path = _resolve_optional(args.style)
    out_path = args.out.expanduser().resolve()

    if visual_path is None or subs_path is None:
        print("Error: --visual-segments and --subtitles-txt are required in --digest mode", file=sys.stderr)
        return 1
    if not visual_path.exists() or not subs_path.exists():
        print(f"Error: Stage 1 inputs not found", file=sys.stderr)
        return 1
    if syn_path is not None and not syn_path.exists():
        print(f"Error: Synopsis not found: {syn_path}", file=sys.stderr)
        return 1
    if args.chunked and scene_path is None:
        print("Error: --chunked requires --scene-markers", file=sys.stderr)
        return 1

    scene_doc: SceneMarkersDocument | None = None
    if scene_path is not None:
        if not scene_path.exists():
            print(f"Error: Scene markers not found: {scene_path}", file=sys.stderr)
            return 1
        scene_doc = load_scene_markers(scene_path)

    visual_segments = load_visual_segments(visual_path)
    subtitles = load_subtitles(subs_path)
    synopsis_text = _read_text(syn_path) if syn_path else None
    genre_rules_text = _load_genre_rules_for_digest(style_path, args.genre)
    target_minutes = args.target_minutes if args.target_minutes is not None else 12.0

    if args.chunked:
        prompts = build_chunked_digest_prompts(
            scene_markers=scene_doc,
            visual_segments=visual_segments,
            subtitles=subtitles,
            movie_title=args.movie_title,
            synopsis_text=synopsis_text,
            genre_rules_text=genre_rules_text,
            target_minutes=target_minutes,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        for label in CHUNK_ORDER:
            sibling = out_path.with_suffix(f".{label}{out_path.suffix}")
            sibling.write_text(prompts[label], encoding="utf-8")
            print(f"Generated chunked digest prompt: {sibling}")
        return 0

    timeline_text = render_timeline(visual_segments, subtitles)
    if not timeline_text.strip():
        print("Error: The merged movie timeline is empty", file=sys.stderr)
        return 1
    prompt = build_digest_prompt(
        timeline_text=timeline_text,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
        genre_rules_text=genre_rules_text,
        scene_markers=scene_doc,
        target_minutes=target_minutes,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt, encoding="utf-8")
    print(f"Generated digest prompt: {out_path}")
    print(f"  visual segments : {len(visual_segments)}")
    print(f"  subtitles       : {len(subtitles)}")
    print(f"  scene markers   : {len(scene_doc.scenes) if scene_doc else 0}")
    return 0


def _run_story(args) -> int:
    style_path = _resolve_optional(args.style)
    out_path = args.out.expanduser().resolve()
    syn_path = _resolve_optional(args.synopsis)
    digest_path = _resolve_optional(args.plot_digest)

    if style_path is None:
        print("Error: --style is required in story mode", file=sys.stderr)
        return 1
    if not style_path.exists():
        print(f"Error: Style file not found: {style_path}", file=sys.stderr)
        return 1
    if syn_path is not None and not syn_path.exists():
        print(f"Error: Synopsis file not found: {syn_path}", file=sys.stderr)
        return 1

    style_raw = _read_text(style_path)
    style_meta, style_text = parse_style_frontmatter(style_raw)
    chars_per_minute = int(style_meta.get("chars_per_minute", 250))
    synopsis_text = _read_text(syn_path) if syn_path else None

    use_digest = digest_path is not None
    timeline_text: str | None = None
    digest_text: str | None = None
    visual_segments: list[dict[str, object]] = []
    subtitles: list[dict[str, object]] = []

    if use_digest:
        if not digest_path.exists():
            print(f"Error: Plot digest not found: {digest_path}", file=sys.stderr)
            return 1
        digest_text = _read_text(digest_path)
    else:
        visual_path = _resolve_optional(args.visual_segments)
        subs_path = _resolve_optional(args.subtitles_txt)
        if visual_path is None or subs_path is None:
            print("Error: --visual-segments and --subtitles-txt are required when --plot-digest is not provided",
                  file=sys.stderr)
            return 1
        if not visual_path.exists() or not subs_path.exists():
            print(f"Error: Stage 1 inputs not found", file=sys.stderr)
            return 1
        visual_segments = load_visual_segments(visual_path)
        subtitles = load_subtitles(subs_path)
        timeline_text = render_timeline(visual_segments, subtitles)
        if not timeline_text.strip():
            print("Error: The merged movie timeline is empty", file=sys.stderr)
            return 1

    genre_text = None
    genre_rules_text = None
    if args.genre:
        example_file = _find_genre_asset(style_path, args.genre, f"{args.genre}.txt")
        if example_file is not None:
            genre_text = _read_text(example_file)
        else:
            print(f"Warning: Genre example not found for {args.genre!r} under {style_path.parent}", file=sys.stderr)
        rules_file = _find_genre_asset(style_path, args.genre, f"{args.genre}.rules.md")
        if rules_file is not None:
            genre_rules_text = _read_text(rules_file)

    prompt_text = build_story_prompt(
        style_text=style_text,
        timeline_text=timeline_text,
        digest_text=digest_text,
        movie_title=args.movie_title,
        synopsis_text=synopsis_text,
        genre_text=genre_text,
        genre_rules_text=genre_rules_text,
        target_minutes=args.target_minutes,
        chars_per_minute=chars_per_minute,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt_text, encoding="utf-8")
    mode_label = "digest" if use_digest else "timeline"
    print(f"Generated story prompt ({mode_label} mode): {out_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.outline:
            return _run_outline(args)
        if args.digest:
            return _run_digest(args)
        return _run_story(args)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all stage 2 tests**

```
python -m pytest tests/pipeline/test_stage_2_build_prompt.py tests/pipeline/test_pass_0_outline.py tests/pipeline/test_pass_1_digest_single.py tests/pipeline/test_pass_1_digest_chunked.py tests/pipeline/test_post_validate.py tests/pipeline/test_scene_markers.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add app/pipeline/stage_2_build_prompt.py tests/pipeline/test_stage_2_build_prompt.py
git commit -m "feat: stage 2 CLI dispatches outline/digest(±chunked)/story modes"
```

---

## Task 11: Workbench step_2 — handle 3-pass flow + `digest_mode` config

Update `workbench/step_2_build_prompt.py` so:
- `--outline` is a new wrapper mode (`python workbench/step_2_build_prompt.py --outline`).
- The default story-mode flow still works (unchanged from today).
- The existing `--digest` flag respects `digest_mode` from config: `"single"` (default) calls the single CLI; `"chunked"` calls the chunked CLI.
- `workbench/_common.py`'s `PipelinePaths` exposes `outline_prompt`, `scene_markers`, `hallucination_report`.

**Files:**
- Modify: `workbench/step_2_build_prompt.py`
- Modify: `workbench/_common.py`
- Modify: `workbench/configs/_template.toml` (document `digest_mode`)

- [ ] **Step 1: Read `workbench/_common.py` to learn the existing `PipelinePaths` shape**

```
python -c "from workbench._common import PipelinePaths; print(PipelinePaths.__dataclass_fields__.keys())"
```

(For reference only — used in step 2 to add new fields without breaking existing consumers.)

- [ ] **Step 2: Add the three new paths to `PipelinePaths`**

In `workbench/_common.py`, locate the `PipelinePaths` dataclass and add (alphabetical with the existing stage2 group):

```python
    outline_prompt: Path        # stage2/outline_prompt.txt
    scene_markers: Path         # stage2/scene_markers.json
    hallucination_report: Path  # stage2/hallucination_report.json
```

Locate `build_paths(cfg)` and populate them inside the existing stage2 paths block:

```python
        outline_prompt=stage2_dir / "outline_prompt.txt",
        scene_markers=stage2_dir / "scene_markers.json",
        hallucination_report=stage2_dir / "hallucination_report.json",
```

- [ ] **Step 3: Add `digest_mode` to the config template**

In `workbench/configs/_template.toml`, after the existing `genre = "action"` line, add:

```toml
# Stage 2 digest mode:
#   "single"  (default) — one LLM call for Pass 1
#   "chunked" — three LLM calls (front/climax/tail) for very long movies
digest_mode = "single"
```

- [ ] **Step 4: Update `workbench/step_2_build_prompt.py` to support outline + chunked**

Replace the file with:

```python
"""Step 2 — build the LLM prompts for the multi-pass script pipeline.

Pipeline:

    python workbench/step_2_build_prompt.py --outline   # writes outline_prompt.txt
    # paste outline_prompt.txt into LLM, save reply as scene_markers.json
    python workbench/step_2_build_prompt.py --digest    # writes digest_prompt.txt
                                                        # (or 3 sibling files if digest_mode = "chunked")
    # paste digest_prompt.txt into LLM, save reply as plot_digest.txt
    python workbench/step_2_build_prompt.py             # writes story_prompt.txt
    # paste story_prompt.txt into LLM, save reply as script.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DEFAULT_CONFIG, banner, build_paths, ensure_stage_dirs, fail, load_config

from app.pipeline.stage_2_build_prompt import main as stage_2_main


def _target_minutes(cfg: dict) -> float | None:
    seconds = cfg["common"].get("target_seconds")
    return seconds / 60.0 if seconds else None


def _common_inputs_present(paths) -> int | None:
    if not paths.visual_segments.is_file():
        return fail(f"visual segments not found: {paths.visual_segments}")
    if not paths.subtitles_text.is_file():
        return fail(f"subtitles not found: {paths.subtitles_text}")
    if not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")
    return None


def _run_outline(cfg, paths) -> int:
    rc = _common_inputs_present(paths)
    if rc is not None:
        return rc

    banner(f"Stage 2 — outline (Pass 0) for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles       : {paths.subtitles_text}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"output          : {paths.outline_prompt}")
    print(f"-> paste reply as: {paths.scene_markers.name}")

    args = [
        "--outline",
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.outline_prompt),
    ]
    return stage_2_main(args)


def _run_digest(cfg, paths) -> int:
    rc = _common_inputs_present(paths)
    if rc is not None:
        return rc

    digest_mode = cfg["common"].get("digest_mode", "single")
    if digest_mode not in ("single", "chunked"):
        return fail(f"Invalid digest_mode: {digest_mode!r} (expected 'single' or 'chunked')")

    if not paths.scene_markers.is_file():
        return fail(
            f"scene_markers.json not found: {paths.scene_markers}\n"
            "Run --outline first and paste the LLM reply into that file."
        )

    banner(f"Stage 2 — digest (Pass 1, {digest_mode}) for {cfg['common']['movie_title']}")
    print(f"visual segments : {paths.visual_segments}")
    print(f"subtitles       : {paths.subtitles_text}")
    print(f"synopsis        : {paths.synopsis}")
    print(f"scene markers   : {paths.scene_markers}")
    print(f"output          : {paths.digest_prompt}")

    args = [
        "--digest",
        "--visual-segments", str(paths.visual_segments),
        "--subtitles-txt", str(paths.subtitles_text),
        "--synopsis", str(paths.synopsis),
        "--scene-markers", str(paths.scene_markers),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.digest_prompt),
    ]
    if paths.style.is_file():
        args.extend(["--style", str(paths.style)])
    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])
    target_minutes = _target_minutes(cfg)
    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])
    if digest_mode == "chunked":
        args.append("--chunked")
    return stage_2_main(args)


def _run_story(cfg, paths) -> int:
    if not paths.style.is_file():
        return fail(f"style file not found: {paths.style}")

    use_digest = paths.plot_digest.is_file()
    if not use_digest:
        rc = _common_inputs_present(paths)
        if rc is not None:
            return rc
    elif not paths.synopsis.is_file():
        return fail(f"synopsis not found: {paths.synopsis}")

    paths.script.touch(exist_ok=True)

    mode = "DIGEST (multi-pass)" if use_digest else "TIMELINE (single-pass)"
    banner(f"Stage 2 — story prompt for {cfg['common']['movie_title']} [{mode}]")
    print(f"style           : {paths.style}")
    print(f"synopsis        : {paths.synopsis}")
    if use_digest:
        print(f"plot digest     : {paths.plot_digest}")
    else:
        print(f"visual segments : {paths.visual_segments}")
        print(f"subtitles       : {paths.subtitles_text}")
    print(f"output prompt   : {paths.story_prompt}")

    args = [
        "--style", str(paths.style),
        "--synopsis", str(paths.synopsis),
        "--movie-title", str(cfg["common"]["movie_title"]),
        "--out", str(paths.story_prompt),
    ]
    if use_digest:
        args.extend(["--plot-digest", str(paths.plot_digest)])
    else:
        args.extend([
            "--visual-segments", str(paths.visual_segments),
            "--subtitles-txt", str(paths.subtitles_text),
        ])
    genre = cfg["common"].get("genre")
    if genre:
        args.extend(["--genre", str(genre)])
    target_minutes = _target_minutes(cfg)
    if target_minutes is not None:
        args.extend(["--target-minutes", str(target_minutes)])
    return stage_2_main(args)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--outline", action="store_true", help="Build Pass 0 outline prompt.")
    mode.add_argument("--digest", action="store_true", help="Build Pass 1 digest prompt(s).")
    args = parser.parse_args(argv)

    cfg = load_config(DEFAULT_CONFIG)
    paths = build_paths(cfg)
    ensure_stage_dirs(paths)

    if args.outline:
        return _run_outline(cfg, paths)
    if args.digest:
        return _run_digest(cfg, paths)
    return _run_story(cfg, paths)


if __name__ == "__main__":
    raise SystemExit(run())
```

- [ ] **Step 5: Run all pipeline tests to confirm nothing regressed**

```
python -m pytest tests/pipeline -q
```

Expected: all pass (workbench has no test coverage of its own — the wrappers are exercised via stage_2_main in stage 2 tests).

- [ ] **Step 6: Commit**

```
git add workbench/step_2_build_prompt.py workbench/_common.py workbench/configs/_template.toml
git commit -m "feat: workbench step_2 supports outline + chunked digest via digest_mode"
```

---

## Task 12: End-to-end integration test

A single test that exercises Pass 0 prompt construction → simulated scene_markers.json → Pass 1 prompt with act-weighted structure → Pass 2 prompt with the digest → post-validation against a tiny synthetic script. Catches integration bugs that per-module tests miss.

**Files:**
- Create: `tests/pipeline/test_stage_2_integration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_stage_2_integration.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from app.pipeline.stage_2_build_prompt import main as stage_2_main
from app.pipeline.stage_2.post_validate import validate_script
from app.pipeline.stage_2.scene_markers import load_scene_markers


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    visual_segments_path = tmp_path / "visual_segments.json"
    visual_segments_path.write_text(json.dumps([
        {"id": f"visual:{i:03d}", "start": f"00:00:{i:02d}.000",
         "end": f"00:00:{i+1:02d}.000", "summary": f"shot {i}",
         "ocr_text": "", "characters": ["Hero"]}
        for i in range(1, 11)
    ], ensure_ascii=False), encoding="utf-8")

    subtitles_path = tmp_path / "subtitles.txt"
    subtitles_path.write_text(
        "[00:00:02.000 -> 00:00:03.000] hello\n"
        "[00:00:05.000 -> 00:00:06.000] watch out\n",
        encoding="utf-8",
    )

    synopsis_path = tmp_path / "synopsis.md"
    synopsis_path.write_text("Hero overcomes adversity.", encoding="utf-8")

    style_path = tmp_path / "style.md"
    style_path.write_text("---\nchars_per_minute: 250\n---\n\n# Demo style\nShort sharp lines.\n",
                          encoding="utf-8")

    return visual_segments_path, subtitles_path, synopsis_path, style_path


def _stub_scene_markers(path: Path) -> None:
    path.write_text(json.dumps({
        "character_glossary": [
            {"original_name": "Hero", "role": "protagonist", "first_seen_scene": "scene:01"},
        ],
        "scenes": [
            {"id": "scene:01", "label": "setup", "act_tag": "SETUP",
             "visual_id_range": ["visual:001", "visual:004"],
             "time_range": ["00:00:00.000", "00:00:05.000"], "hook": "setup"},
            {"id": "scene:02", "label": "climax", "act_tag": "CLIMAX",
             "visual_id_range": ["visual:005", "visual:008"],
             "time_range": ["00:00:05.000", "00:00:09.000"], "hook": "climax"},
            {"id": "scene:03", "label": "close", "act_tag": "CLOSING",
             "visual_id_range": ["visual:009", "visual:010"],
             "time_range": ["00:00:09.000", "00:00:11.000"], "hook": "close"},
        ],
    }, ensure_ascii=False), encoding="utf-8")


def test_three_pass_pipeline_end_to_end(tmp_path: Path) -> None:
    visual_p, subs_p, syn_p, style_p = _write_inputs(tmp_path)

    # Pass 0 prompt
    outline_p = tmp_path / "outline_prompt.txt"
    rc = stage_2_main([
        "--outline",
        "--visual-segments", str(visual_p),
        "--subtitles-txt", str(subs_p),
        "--synopsis", str(syn_p),
        "--out", str(outline_p),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    outline_text = outline_p.read_text(encoding="utf-8")
    assert "scene_markers.json" in outline_text or "JSON" in outline_text

    # Simulate the LLM reply by writing a hand-crafted scene_markers.json
    scene_p = tmp_path / "scene_markers.json"
    _stub_scene_markers(scene_p)
    scene_doc = load_scene_markers(scene_p)
    assert scene_doc.scenes[1].act_tag == "CLIMAX"

    # Pass 1 prompt (single mode, scene-anchored)
    digest_prompt_p = tmp_path / "digest_prompt.txt"
    rc = stage_2_main([
        "--digest",
        "--visual-segments", str(visual_p),
        "--subtitles-txt", str(subs_p),
        "--scene-markers", str(scene_p),
        "--out", str(digest_prompt_p),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    digest_text = digest_prompt_p.read_text(encoding="utf-8")
    assert "scene:02" in digest_text
    assert "CLIMAX" in digest_text and "4-6" in digest_text

    # Simulate the LLM digest reply
    plot_digest_p = tmp_path / "plot_digest.txt"
    plot_digest_p.write_text(
        "## scene:01 (SETUP)\n- 镜头: visual:001-002\n- 事件: Hero appears.\n"
        "## scene:02 (CLIMAX)\n- 镜头: visual:005-008\n- 事件: Hero wins.\n",
        encoding="utf-8",
    )

    # Pass 2 prompt
    story_prompt_p = tmp_path / "story_prompt.txt"
    rc = stage_2_main([
        "--style", str(style_p),
        "--synopsis", str(syn_p),
        "--plot-digest", str(plot_digest_p),
        "--out", str(story_prompt_p),
        "--movie-title", "Demo",
    ])
    assert rc == 0
    assert "Hero wins" in story_prompt_p.read_text(encoding="utf-8")

    # Simulate the LLM script reply; include one valid sentence and one with bad refs.
    script_p = tmp_path / "script.txt"
    script_p.write_text(
        "[ACT 1 - SETUP]\n"
        "<refs>visual:001</refs>\n"
        "故事开场，主角登场。\n"
        "\n"
        "<refs>visual:999</refs>\n"
        "这一句的 visual ID 不存在。\n",
        encoding="utf-8",
    )

    # Post-validation
    visual_segments = json.loads(visual_p.read_text(encoding="utf-8"))
    report = validate_script(
        script_text=script_p.read_text(encoding="utf-8"),
        scene_markers=scene_doc,
        all_visual_ids={s["id"] for s in visual_segments},
    )
    assert report.total_sentences == 2
    assert len(report.flagged) == 1
    assert "visual:999" in report.flagged[0].issue
```

- [ ] **Step 2: Run the integration test**

```
python -m pytest tests/pipeline/test_stage_2_integration.py -q
```

Expected: 1 passed.

- [ ] **Step 3: Run the full pipeline test suite as a final check**

```
python -m pytest tests/pipeline -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```
git add tests/pipeline/test_stage_2_integration.py
git commit -m "test: stage 2 end-to-end integration covers outline+digest+story+validation"
```

---

## Spec coverage verification

| Spec requirement | Implemented in task |
|---|---|
| Pass 0 outline builder + thin timeline | Task 6 |
| `scene_markers.json` schema with character glossary | Task 5 |
| Pass 1 single-mode with scene-anchored beats + strict targets | Task 7 |
| Pass 1 chunked-mode orchestrator | Task 8 |
| Pass 2 untouched (style still applied) | Task 4 (relocation only) |
| Deterministic post-validation, flag-only | Task 9 |
| Clean B/C separation (distinct modules, dispatcher only knows about both) | Tasks 5–10 |
| `app/pipeline/stage_2/` subpackage | Tasks 1–9 |
| CLI dispatcher for outline/digest/story | Task 10 |
| Workbench wrapper supports outline + chunked via `digest_mode` config | Task 11 |
| niu-shu.md and styles/genres/** untouched | (verified by Task 4 + Task 11 not modifying them) |
| No shot dropping / lossless representation | Task 6 (thin view only drops the summary field) |
| End-to-end integration with hallucination report fixtures | Task 12 |

No gaps detected.

---

## Notes for the implementing engineer

- **Existing in-flight movies:** `sha_po_lang_2` has a `plot_digest.txt` from the pre-redesign era. It remains valid because Pass 2 still accepts a digest without scene markers. New runs use the new flow; old artifacts don't need migration.
- **Backward compat surface:** the public functions `build_digest_prompt`, `build_story_prompt`, `build_timeline_entries`, `render_timeline`, `load_subtitles` keep their import paths (`from app.pipeline.stage_2_build_prompt import ...`) via re-exports in Tasks 2–4.
- **DRY principle:** Task 8 (chunked) deliberately reuses `build_digest_prompt` from Task 7 — chunked mode contributes only partitioning + concatenation logic, never prompt-construction logic. If you find yourself duplicating prompt strings, stop and re-think.
- **Tests run under conda:** every `pytest` invocation must be prefixed with `conda run -n py312_machine_learning --no-capture-output` per `docs/agent-rules/python-environment.md`.
