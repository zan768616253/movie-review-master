from __future__ import annotations

from app.pipeline.stage_2.pass_2_story import build_story_prompt


def test_story_prompt_without_prior_context_has_no_recap_mode() -> None:
    """Movie / episode-1 behavior: no recap directive, no series block."""
    prompt = build_story_prompt(
        style_text="STYLE RULES",
        digest_text="DIGEST BODY",
        movie_title="Demo",
    )
    assert "Previously in the series" not in prompt
    assert "Episode recap opening" not in prompt
    assert "[RECAP]" not in prompt


def test_story_prompt_with_prior_context_emits_recap_directive() -> None:
    prompt = build_story_prompt(
        style_text="STYLE RULES",
        digest_text="DIGEST BODY",
        movie_title="Demo EP2",
        prior_context_text="第 1 集 回顾：主角发现自己被诅咒缠身。",
    )
    # Recap source block + the prior text.
    assert "Previously in the series" in prompt
    assert "第 1 集 回顾：主角发现自己被诅咒缠身。" in prompt
    # Recap-opening directive.
    assert "Episode recap opening" in prompt
    assert "[RECAP]" in prompt
    assert "<refs>recap</refs>" in prompt


def test_story_prompt_recap_mode_keeps_hard_grounding_for_normal_sentences() -> None:
    prompt = build_story_prompt(
        style_text="STYLE RULES",
        digest_text="DIGEST BODY",
        movie_title="Demo EP2",
        prior_context_text="第 1 集 回顾：xxx。",
    )
    # The grounding requirement still applies to non-recap sentences.
    assert "Grounding requirement" in prompt


def test_story_prompt_blank_prior_context_is_treated_as_no_recap() -> None:
    prompt = build_story_prompt(
        style_text="STYLE RULES",
        digest_text="DIGEST BODY",
        movie_title="Demo",
        prior_context_text="   ",
    )
    assert "Episode recap opening" not in prompt
