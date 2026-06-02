"""Pure helpers for the TV-series running continuity file.

The continuity file (``workbench/work/<series_slug>/series_context.md``) is a
sequence of per-episode "回顾" blocks, auto-seeded from each episode's digest
``## 承上启下`` section and injected as background into later episodes' prompts.

Everything here is string-in / string-out so it is trivially testable and has no
filesystem or config dependency.
"""

from __future__ import annotations

import re

CONTINUITY_HEADER = "承上启下"

# A digest carryover section: "## 承上启下 ..." up to the next "## " or EOF.
_CARRYOVER_RE = re.compile(
    rf"^##\s*{CONTINUITY_HEADER}[^\n]*\n(?P<body>.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)

# An episode block header: "## 第 N 集 回顾 — title".
_EPISODE_HEADER_RE = re.compile(r"^##\s*第\s*(?P<no>\d+)\s*集", re.MULTILINE)


def extract_continuity_section(digest_text: str) -> str | None:
    """Return the text under the digest's ``## 承上启下`` header, or ``None``.

    Captures everything between the header line and the next ``##`` heading (or
    end of file), stripped. Returns ``None`` when the section is missing or its
    body is empty/whitespace.
    """
    match = _CARRYOVER_RE.search(digest_text)
    if not match:
        return None
    body = match.group("body").strip()
    return body or None


def _episode_title_header(episode_no: int, episode_title: str) -> str:
    title = (episode_title or "").strip()
    base = f"## 第 {episode_no} 集 回顾"
    return f"{base} — {title}" if title else base


def _split_blocks(series_md: str) -> tuple[str, dict[int, str]]:
    """Split the running file into (preamble, {episode_no: block_text}).

    ``block_text`` includes the block's own ``## 第 N 集`` header line. Any text
    before the first episode block is preserved as the preamble.
    """
    headers = list(_EPISODE_HEADER_RE.finditer(series_md))
    if not headers:
        return series_md.strip(), {}

    preamble = series_md[: headers[0].start()].strip()
    blocks: dict[int, str] = {}
    for index, header in enumerate(headers):
        start = header.start()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(series_md)
        episode_no = int(header.group("no"))
        blocks[episode_no] = series_md[start:end].strip()
    return preamble, blocks


def _render(preamble: str, blocks: dict[int, str]) -> str:
    ordered = [blocks[n] for n in sorted(blocks)]
    parts = ([preamble] if preamble else []) + ordered
    return "\n\n".join(parts).strip() + "\n"


def update_series_context(
    existing_md: str,
    episode_no: int,
    episode_title: str,
    carryover: str,
) -> str:
    """Insert or replace the ``episode_no`` block, returning the rebuilt file.

    Idempotent per episode: re-running with the same ``episode_no`` overwrites
    only that block. Blocks are always rendered in ascending episode order; any
    human-written preamble before the first block is preserved.
    """
    preamble, blocks = _split_blocks(existing_md)
    header = _episode_title_header(episode_no, episode_title)
    blocks[episode_no] = f"{header}\n\n{carryover.strip()}"
    return _render(preamble, blocks)


def assemble_prior_context(series_md: str, before_episode_no: int) -> str:
    """Concatenate the blocks for every episode strictly before ``before_episode_no``.

    Returns ``""`` when there is nothing prior (e.g. episode 1).
    """
    _, blocks = _split_blocks(series_md)
    prior = [blocks[n] for n in sorted(blocks) if n < before_episode_no]
    return "\n\n".join(prior)
