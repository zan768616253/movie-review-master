from __future__ import annotations

from pathlib import Path

import numpy as np

from app.pipeline.stage_3_generate_audio import (
    Chunk,
    Segment,
    build_visual_segment_lookup,
    build_voice_prompt,
    generate_chunks,
    parse_refs_body,
    parse_script_chunks,
    resolve_segment_refs,
    split_text_for_tts,
    strip_inline_refs,
)


def test_parse_refs_body_normalizes_and_expands_ranges() -> None:
    assert parse_refs_body("visual:031, visual:033-035, 40, 50-52") == [
        "visual:031",
        "visual:033",
        "visual:034",
        "visual:035",
        "visual:040",
        "visual:050",
        "visual:051",
        "visual:052",
    ]
    assert parse_refs_body("visual:1") == ["visual:001"]
    assert parse_refs_body("visual:002, visual:002, 2") == ["visual:002"]
    assert parse_refs_body("visual:005–003") == ["visual:003", "visual:004", "visual:005"]
    assert parse_refs_body("") == []


def test_strip_inline_refs_removes_substrings_anywhere() -> None:
    assert strip_inline_refs("故事 <refs>visual:001</refs> 开始") == "故事  开始"
    assert strip_inline_refs("纯文本") == "纯文本"
    assert strip_inline_refs("<refs>visual:001</refs><refs>visual:002</refs>x") == "x"


def test_parse_script_chunks_with_refs_builds_per_sentence_segments() -> None:
    script_text = """
[HOOK]
<refs>visual:128, visual:312</refs>
看完这部片，我整整两天睡不着。

<refs>visual:033-035</refs>
那场雪山追逐，比我看过的所有动作戏都狠。

[ACT 1 - SETUP]
<refs>visual:031, visual:040</refs>
故事开场，老猜每天送女儿去溜冰场学习。
"""

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 2
    hook = chunks[0]
    assert hook.section == "HOOK"
    assert hook.text == (
        "看完这部片，我整整两天睡不着。\n那场雪山追逐，比我看过的所有动作戏都狠。"
    )
    assert [(seg.text, seg.refs) for seg in hook.segments] == [
        ("看完这部片，我整整两天睡不着。", ["visual:128", "visual:312"]),
        ("那场雪山追逐，比我看过的所有动作戏都狠。", ["visual:033", "visual:034", "visual:035"]),
    ]

    act = chunks[1]
    assert act.section == "ACT 1 - SETUP"
    assert act.segments[0].refs == ["visual:031", "visual:040"]
    assert act.segments[0].text == "故事开场，老猜每天送女儿去溜冰场学习。"


def test_parse_script_chunks_recap_opens_the_script_like_hook() -> None:
    """A series episode opens with [RECAP] instead of [HOOK]; the script must not
    be skipped, and the recap becomes the first chunk."""
    script_text = """
[TITLE]
咒术回战 第2集

[RECAP]
<refs>recap</refs>
上一集，主角发现自己被诅咒缠身。

[ACT 1 - SETUP]
<refs>visual:001</refs>
本集开场。
"""

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 2
    recap = chunks[0]
    assert recap.section == "RECAP"
    assert recap.text == "上一集，主角发现自己被诅咒缠身。"
    assert chunks[1].section == "ACT 1 - SETUP"


def test_parse_script_chunks_recap_sentinel_yields_no_ranges() -> None:
    """`<refs>recap</refs>` carries no visual IDs, so the spoken prose has empty refs."""
    script_text = """
[RECAP]
<refs>recap</refs>
前情提要：黑帮大佬重生回到十六岁。
"""

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 1
    assert chunks[0].section == "RECAP"
    assert chunks[0].segments[0].text == "前情提要：黑帮大佬重生回到十六岁。"
    assert chunks[0].segments[0].refs == []


def test_parse_script_chunks_handles_orphan_prose_before_refs() -> None:
    script_text = """
[HOOK]
开篇这句没有 refs
<refs>visual:001</refs>
这句有 refs
"""

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 1
    segments = chunks[0].segments
    assert len(segments) == 2
    assert segments[0].refs == []
    assert segments[0].text == "开篇这句没有 refs"
    assert segments[1].refs == ["visual:001"]
    assert segments[1].text == "这句有 refs"


def test_parse_script_chunks_strips_inline_refs_from_prose() -> None:
    script_text = """
[HOOK]
<refs>visual:001</refs>
这是 <refs>visual:002</refs> 干扰的一行。
"""

    chunks = parse_script_chunks(script_text)
    segment = chunks[0].segments[0]
    assert "<refs>" not in segment.text
    assert segment.refs == ["visual:001"]


def test_build_visual_segment_lookup_maps_ids_to_seconds() -> None:
    visual_segments = [
        {"id": "visual:001", "start": "00:00:05.000", "end": "00:00:09.500"},
        {"id": "visual:002", "start": "00:01:00.000", "end": "00:01:04.000"},
        {"id": "visual:003", "start": "00:02:00.000", "end": "00:02:00.000"},
    ]
    lookup = build_visual_segment_lookup(visual_segments)
    assert lookup == {
        "visual:001": (5.0, 9.5),
        "visual:002": (60.0, 64.0),
    }


def test_resolve_segment_refs_populates_ranges_and_records_unknowns() -> None:
    chunk = Chunk(
        index=1,
        section="HOOK",
        text="any",
        segments=[
            Segment(text="一", refs=["visual:001", "visual:999"]),
            Segment(text="二", refs=["visual:002"]),
        ],
    )
    lookup = {
        "visual:001": (5.0, 9.5),
        "visual:002": (60.0, 64.0),
    }
    resolved, dropped, sample_unknown = resolve_segment_refs([chunk], lookup)

    assert resolved == 2
    assert dropped == 1
    assert sample_unknown == ["visual:999"]
    assert chunk.segments[0].ranges_s == [(5.0, 9.5)]
    assert chunk.segments[0].unknown_refs == ["visual:999"]
    assert chunk.segments[1].ranges_s == [(60.0, 64.0)]
    assert chunk.segments[1].unknown_refs == []


def test_parse_script_chunks_plain_script_uses_structural_sections() -> None:
    script_text = """
[TITLE]
连环杀局

[HOOK]
注意看
有钱人为了活命能有多疯狂

[ACT 1 - SETUP]
老洪需要换心
永强被送进黑狱

[CLOSING]
我们下期再见
"""

    chunks = parse_script_chunks(script_text)

    assert [(chunk.section, chunk.text) for chunk in chunks] == [
        ("HOOK", "注意看\n有钱人为了活命能有多疯狂"),
        ("ACT 1 - SETUP", "老洪需要换心\n永强被送进黑狱"),
        ("CLOSING", "我们下期再见"),
    ]
    assert all(chunk.ranges == [] for chunk in chunks)


def test_parse_script_chunks_anchored_script_preserves_anchor_metadata() -> None:
    script_text = """
[TITLE]
Demo

[HOOK]
[ANCHOR ranges="00:00:01-00:00:05" characters="永强, 铁柱"]
第一句
第二句

[ACT 1 - SETUP]
[ANCHOR ranges="00:00:06-00:00:09, 00:00:10-00:00:12"]
第三句

[CLOSING]
收尾一句
"""

    chunks = parse_script_chunks(script_text)

    assert len(chunks) == 3
    assert chunks[0].section == "HOOK"
    assert chunks[0].ranges == [("00:00:01", "00:00:05")]
    assert chunks[0].characters == ["永强", "铁柱"]
    assert chunks[0].text == "第一句\n第二句"
    assert chunks[1].section == "ACT 1 - SETUP"
    assert chunks[1].ranges == [
        ("00:00:06", "00:00:09"),
        ("00:00:10", "00:00:12"),
    ]
    assert chunks[2].section == "CLOSING"
    assert chunks[2].ranges == []
    assert chunks[2].text == "收尾一句"


def test_build_voice_prompt_uses_icl_transcript(tmp_path: Path) -> None:
    ref_audio = tmp_path / "ref.mp3"
    ref_audio.write_bytes(b"audio")
    ref_text = tmp_path / "ref.txt"
    ref_text.write_text("你好世界\n", encoding="utf-8")

    class FakeModel:
        def __init__(self) -> None:
            self.kwargs = None

        def create_voice_clone_prompt(self, **kwargs):
            self.kwargs = kwargs
            return object()

    model = FakeModel()

    build_voice_prompt(
        model,
        ref_audio,
        ref_text,
    )

    assert model.kwargs == {
        "ref_audio": str(ref_audio),
        "ref_text": "你好世界",
    }


def test_split_text_for_tts_keeps_requests_within_limit() -> None:
    text = "\n".join(
        [
            "第一句比较短。",
            "第二句也比较短。",
            "第三句稍微长一点但是还在可控范围内。",
            "第四句继续往下说，方便测试换段。",
        ]
    )

    requests = split_text_for_tts(text, max_chars_per_request=20)

    assert requests == [
        "第一句比较短。\n第二句也比较短。",
        "第三句稍微长一点但是还在可控范围内。",
        "第四句继续往下说，方便测试换段。",
    ]
    assert all(len(request) <= 20 for request in requests)


def test_generate_chunks_splits_long_chunk_but_keeps_manifest_granularity() -> None:
    chunk = Chunk(
        index=1,
        section="ACT 2",
        text="\n".join(
            [
                "甲" * 40 + "。",
                "乙" * 40 + "。",
                "丙" * 40 + "。",
            ]
        ),
    )

    class FakeModel:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_voice_clone(self, **kwargs):
            self.calls.append(kwargs)
            return [np.ones(24, dtype=np.float32)], 12

    model = FakeModel()
    wavs, sample_rate = generate_chunks(
        model,
        [chunk],
        voice_prompt=object(),
        max_chars_per_request=90,
    )

    assert len(wavs) == 1
    assert sample_rate == 12
    assert len(model.calls) == 2
    assert all(len(str(call["text"])) <= 90 for call in model.calls)
    assert len(wavs[0]) == 48


def test_generate_chunks_retries_with_smaller_requests_when_model_hits_cap() -> None:
    chunk = Chunk(
        index=1,
        section="ACT 3",
        text=("甲" * 45 + "。\n" + "乙" * 45 + "。"),
    )

    class FakeModel:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_voice_clone(self, **kwargs):
            self.calls.append(kwargs)
            text = str(kwargs["text"])
            max_new_tokens = int(kwargs["max_new_tokens"])
            if len(text) > 80:
                return [np.ones(max_new_tokens, dtype=np.float32)], 12
            return [np.ones(120, dtype=np.float32)], 12

    model = FakeModel()
    wavs, sample_rate = generate_chunks(
        model,
        [chunk],
        voice_prompt=object(),
        max_chars_per_request=120,
    )

    assert len(wavs) == 1
    assert sample_rate == 12
    assert len(model.calls) == 3
    assert len(str(model.calls[0]["text"])) > 80
    assert all(len(str(call["text"])) <= 80 for call in model.calls[1:])
    assert len(wavs[0]) == 240
