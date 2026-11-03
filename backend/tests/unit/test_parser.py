"""T010: transcript_parser 单元测试（FR-007）。

覆盖：说话人标签（`Neil 尼尔` / `Beth:` / 行内 `Beth: Hello`）、按 `. ? ! ;` 切句、
中文占比过半判译文并挂最近段落块、无标签材料空行分话轮、异常行按英文正文兜底。
"""

from backend.app.core import transcript_parser as tp


def parse(text: str):
    return tp.parse(text)


def sentences_of(result):
    return [
        s.text
        for t in result.turns
        for b in t.blocks
        for s in b.sentences
    ]


def test_label_with_chinese_translation_name():
    result = parse(
        "Neil 尼尔\n"
        "Hello and welcome to the programme. I'm Neil.\n"
        "Georgie 乔治\n"
        "And I'm Georgie. Let's start.\n"
    )
    assert len(result.turns) == 2
    assert result.turns[0].speakerName == "Neil"
    assert result.turns[0].speakerNameZh == "尼尔"
    assert result.turns[1].speakerName == "Georgie"
    assert result.turns[1].speakerNameZh == "乔治"
    assert len(result.turns[0].blocks[0].sentences) == 2
    assert sentences_of(result)[0] == "Hello and welcome to the programme."


def test_label_with_colon():
    result = parse("Beth:\nHi there. How are you?\n")
    assert len(result.turns) == 1
    assert result.turns[0].speakerName == "Beth"
    assert result.turns[0].speakerNameZh is None
    assert [s.text for s in result.turns[0].blocks[0].sentences] == [
        "Hi there.",
        "How are you?",
    ]


def test_inline_label_starts_turn_with_content():
    result = parse(
        "Neil 尼尔\n"
        "Welcome back.\n"
        "Beth: Hello everyone. Nice to see you.\n"
    )
    assert len(result.turns) == 2
    assert result.turns[1].speakerName == "Beth"
    assert [s.text for s in result.turns[1].blocks[0].sentences] == [
        "Hello everyone.",
        "Nice to see you.",
    ]


def test_sentence_split_on_dot_question_exclamation_semicolon():
    result = parse(
        "Neil\n"
        "One two. Three four? Five six! Seven; eight nine.\n"
    )
    sents = sentences_of(result)
    assert sents == [
        "One two.",
        "Three four?",
        "Five six!",
        "Seven;",
        "eight nine.",
    ]


def test_translation_lines_attach_to_nearest_english_block_in_order():
    result = parse(
        "Neil 尼尔\n"
        "This is the first English paragraph.\n"
        "这是第一段的第一行译文。\n"
        "这是第一段的第二行译文。\n"
        "Georgie\n"
        "Second turn English text.\n"
    )
    first_turn = result.turns[0]
    assert first_turn.blocks[0].translationLines == [
        "这是第一段的第一行译文。",
        "这是第一段的第二行译文。",
    ]
    assert len(result.turns[1].blocks[0].sentences) == 1
    assert result.stats["translationLineCount"] == 2


def test_translation_attaches_across_blank_line_to_previous_block():
    result = parse(
        "Neil\n"
        "English paragraph here.\n"
        "\n"
        "译文跟在空行后仍归属最近英文块。\n"
    )
    assert result.turns[0].blocks[0].translationLines == ["译文跟在空行后仍归属最近英文块。"]


def test_unlabeled_continuation_is_new_block_in_same_turn():
    result = parse(
        "Neil\n"
        "First paragraph of the turn.\n"
        "\n"
        "Second paragraph without a label.\n"
    )
    assert len(result.turns) == 1
    assert len(result.turns[0].blocks) == 2
    assert result.turns[0].blocks[1].sentences[0].text == "Second paragraph without a label."


def test_untagged_material_splits_turns_on_blank_lines():
    result = parse(
        "First paragraph has some English text.\n"
        "It continues on a second line.\n"
        "\n"
        "Second paragraph becomes another turn.\n"
        "\n"
        "Third paragraph here.\n"
    )
    assert len(result.turns) == 3
    assert all(t.speakerName is None for t in result.turns)
    assert len(result.turns[0].blocks[0].sentences) == 2
    assert sentences_of(result)[-1] == "Third paragraph here."


def test_unknown_line_falls_back_to_english_content():
    result = parse(
        "Neil\n"
        "Some English first.\n"
        "=== weird separator ===\n"
        "More English after.\n"
    )
    sents = sentences_of(result)
    assert any("weird separator" in s for s in sents)
    assert len(result.turns) == 1


def test_stats_structure():
    result = parse(
        "Neil 尼尔\n"
        "Line one. Line two.\n"
        "译文一行。\n"
        "Beth:\n"
        "Beth line.\n"
    )
    stats = result.stats
    assert stats["speakers"] == [
        {"name": "Neil", "nameZh": "尼尔"},
        {"name": "Beth", "nameZh": None},
    ]
    assert stats["turnCount"] == 2
    assert stats["blockCount"] == 2
    assert stats["translationLineCount"] == 1


def test_no_content_lost_every_english_word_preserved():
    transcript = (
        "Neil 尼尔\n"
        "Hello and welcome.\n"
        "完全无法归类的??内容\n"
        "Bye for now.\n"
    )
    result = parse(transcript)
    joined = " ".join(sentences_of(result))
    for word in ["Hello", "welcome", "Bye", "now"]:
        assert word in joined
    # 中文行占比>0.5 判译文，不算丢内容
    assert result.stats["translationLineCount"] == 1


def test_to_models_produces_unaligned_sentences_with_indexes():
    result = parse("Neil 尼尔\nHello there. Bye now.\n")
    models = tp.to_models(result, material_id="mat1")
    assert len(models["turns"]) == 1
    assert len(models["blocks"]) == 1
    assert len(models["sentences"]) == 2
    s0, s1 = models["sentences"]
    assert s0.materialId == "mat1"
    assert (s0.index, s1.index) == (0, 1)
    assert s0.aligned is False
    assert s0.words == []
    assert s0.startSec is None
    assert models["turns"][0].speakerNameZh == "尼尔"


# ---------- 2026-10-29 修复回归：译文行后的英文开新段落块（BBC 粘贴格式） ----------


def test_en_after_translation_starts_new_block_without_blank_line():
    """BBC 网页粘贴：段落间无空行，靠 英-译-英 换段；译文不得跟在后续英文之后。"""
    text = (
        "Neil 尼尔\n"
        "Hi, Georgie. Yes, I am feeling a little bit festive.\n"
        "是的，我有点感受到节日气氛了。\n"
        "In the UK, we have lots of celebrations coming up.\n"
        "在英国，我们有很多即将到来的庆祝活动。"
    )
    result = parse(text)
    turn = result.turns[0]
    assert len(turn.blocks) == 2, "译文后的英文行应开新段落块"
    assert turn.blocks[0].translationLines == ["是的，我有点感受到节日气氛了。"]
    assert turn.blocks[1].translationLines == ["在英国，我们有很多即将到来的庆祝活动。"]
    assert "festive." in turn.blocks[0].sentences[-1].text
    assert "In the UK" in turn.blocks[1].sentences[0].text


def test_multi_translation_lines_still_merge_into_one_block():
    """同一英文段落块后的多行译文仍按原序拼接（不受换段规则影响）。"""
    text = "Beth: Hello there.\n第一行译文。\n第二行译文。"
    result = parse(text)
    turn = result.turns[0]
    assert len(turn.blocks) == 1
    assert turn.blocks[0].translationLines == ["第一行译文。", "第二行译文。"]


# ---------- 2026-10-29 修复回归：中英混行与中文句号切分 ----------


def test_mixed_en_zh_line_splits_into_sentences_and_translation():
    """中英混在同一行：英文片段进句子、中文片段进译文，且受译文开关控制。"""
    text = "Beth: Hello there. 你好，世界。 How are you? 你好吗？"
    result = parse(text)
    block = result.turns[0].blocks[0]
    assert [s.text for s in block.sentences] == ["Hello there.", "How are you?"]
    assert block.translationLines == ["你好，世界。", "你好吗？"]


def test_chinese_full_stop_does_not_glue_to_english_sentence():
    """中文句号 。 参与切句：'I'm Georgie。我是乔治。' 不得黏成一个句子。"""
    text = "I'm Georgie。我是乔治。"
    result = parse(text)
    block = result.turns[0].blocks[0]
    assert [s.text for s in block.sentences] == ["I'm Georgie。"]
    assert block.translationLines == ["我是乔治。"]


def test_mixed_line_untagged_material():
    """无标签材料同样按片段分类处理中英混行。"""
    text = "Hello world. 你好世界。\n\nNice day. 好日子。"
    result = parse(text)
    assert len(result.turns) == 2
    b0 = result.turns[0].blocks[0]
    assert [s.text for s in b0.sentences] == ["Hello world."]
    assert b0.translationLines == ["你好世界。"]


# ---------- 2026-10-29 修复回归：域名/URL 中的点不参与切句 ----------


def test_domain_dot_not_treated_as_sentence_end():
    assert tp.split_sentences("find a worksheet on bbclearningenglish.com. It helps.") == [
        "find a worksheet on bbclearningenglish.com.",
        "It helps.",
    ]


def test_plain_sentences_still_split():
    assert tp.split_sentences("I'm Beth. And I'm Neil.") == ["I'm Beth.", "And I'm Neil."]
