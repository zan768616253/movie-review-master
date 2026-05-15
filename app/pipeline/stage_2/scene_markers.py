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
