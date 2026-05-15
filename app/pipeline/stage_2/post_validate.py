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
    for index, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            last_refs = None
            continue
        if _ACT_HEADER_RE.match(line):
            last_refs = None
            continue
        refs_match = _REFS_LINE_RE.match(line)
        if refs_match:
            last_refs = _expand_visual_refs(refs_match.group(1))
            continue

        # Not refs, not header, not blank → candidate narration.
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

    return PostValidationReport(total_sentences=total_sentences, flagged=flagged)
