from __future__ import annotations

from app.pipeline.series_context import (
    assemble_prior_context,
    extract_continuity_section,
    update_series_context,
)


# --- extract_continuity_section -------------------------------------------------

_DIGEST_WITH_CARRYOVER = """\
## 剧情脉络
- beat one
- beat two

## 承上启下 (Continuity Carryover) — 写给下一集
本集结束时，主角发现自己被诅咒缠身。
反派里香的真实身份仍是个谜。

## 结局
ending text here
"""


def test_extract_returns_text_under_header_up_to_next_h2() -> None:
    out = extract_continuity_section(_DIGEST_WITH_CARRYOVER)
    assert out is not None
    assert "主角发现自己被诅咒缠身" in out
    assert "反派里香的真实身份仍是个谜" in out
    # Must stop before the next ## section.
    assert "ending text here" not in out
    assert "beat one" not in out


def test_extract_reads_to_eof_when_no_following_header() -> None:
    digest = "## 承上启下\n最后一句承上启下。\n"
    out = extract_continuity_section(digest)
    assert out == "最后一句承上启下。"


def test_extract_returns_none_when_absent() -> None:
    assert extract_continuity_section("## 剧情脉络\n- beat\n") is None


def test_extract_returns_none_when_body_is_empty() -> None:
    assert extract_continuity_section("## 承上启下 (Continuity)\n\n## 结局\nx\n") is None


# --- update_series_context ------------------------------------------------------


def test_update_inserts_block_with_title_and_carryover() -> None:
    md = update_series_context("", 1, "第1集 起", "主角登场，发现诅咒。")
    assert "## 第 1 集" in md
    assert "第1集 起" in md
    assert "主角登场，发现诅咒。" in md


def test_update_is_idempotent_per_episode() -> None:
    md = update_series_context("", 1, "第1集", "old summary")
    md = update_series_context(md, 1, "第1集", "new summary")
    assert "new summary" in md
    assert "old summary" not in md
    # Only one episode-1 block.
    assert md.count("## 第 1 集") == 1


def test_update_keeps_blocks_sorted_by_episode_number() -> None:
    md = update_series_context("", 2, "第2集", "ep2 summary")
    md = update_series_context(md, 1, "第1集", "ep1 summary")
    assert md.index("ep1 summary") < md.index("ep2 summary")


# --- assemble_prior_context -----------------------------------------------------


def _three_episode_md() -> str:
    md = update_series_context("", 1, "第1集", "ep1 summary")
    md = update_series_context(md, 2, "第2集", "ep2 summary")
    md = update_series_context(md, 3, "第3集", "ep3 summary")
    return md


def test_assemble_includes_only_episodes_before_target() -> None:
    md = _three_episode_md()
    prior = assemble_prior_context(md, before_episode_no=3)
    assert "ep1 summary" in prior
    assert "ep2 summary" in prior
    assert "ep3 summary" not in prior


def test_assemble_episode_one_is_empty() -> None:
    md = _three_episode_md()
    assert assemble_prior_context(md, before_episode_no=1).strip() == ""


def test_assemble_preserves_episode_order() -> None:
    md = _three_episode_md()
    prior = assemble_prior_context(md, before_episode_no=3)
    assert prior.index("ep1 summary") < prior.index("ep2 summary")
