"""T025: quiz_selector 单元测试（FR-029 抽题优先级）。

优先级：没听懂 > 含生词/短语的句子 > 随机；池 = aligned=true；
默认 10 句，不足全出。
"""

from datetime import date, timedelta

from backend.app.core import quiz_selector
from backend.app.models import ReviewItem, Sentence


def make_sentence(sid, index, aligned=True, not_understood=False, text=None):
    return Sentence(
        id=sid,
        materialId="m1",
        turnId="t1",
        blockId="b1",
        index=index,
        text=text or f"Sentence number {index} here today.",
        aligned=aligned,
        notUnderstood=not_understood,
    )


def make_review_item(sid, rtype="word"):
    return ReviewItem(
        type=rtype,
        text="welcome",
        materialId="m1",
        sentenceId=sid,
        contextText="x",
        dueAt=date.today() + timedelta(days=1),
    )


def test_priority_not_understood_first_then_vocab_then_rest():
    sentences = [
        make_sentence("plain0", 0),
        make_sentence("nu", 1, not_understood=True),
        make_sentence("vocab", 2),
        make_sentence("plain3", 3),
        make_sentence("nu2", 4, not_understood=True),
    ]
    review_items = [make_review_item("vocab")]
    selected = quiz_selector.select(sentences, review_items, count=10)
    # 前两档顺序稳定：没听懂在前，含生词句紧随其后；其余随机（只验集合）
    assert selected[0] in ("nu", "nu2")
    assert selected[1] in ("nu", "nu2")
    assert selected[2] == "vocab"
    assert set(selected) == {"nu", "nu2", "vocab", "plain0", "plain3"}


def test_excludes_unaligned_sentences_even_if_marked():
    sentences = [
        make_sentence("un", 0, aligned=False, not_understood=True),
        make_sentence("ok1", 1),
        make_sentence("ok2", 2),
    ]
    selected = quiz_selector.select(sentences, [], count=10)
    assert "un" not in selected
    assert set(selected) == {"ok1", "ok2"}


def test_fewer_than_count_returns_all_aligned():
    sentences = [make_sentence(f"s{i}", i) for i in range(4)]
    selected = quiz_selector.select(sentences, [], count=10)
    assert len(selected) == 4
    assert set(selected) == {s.id for s in sentences}


def test_count_limits_pool_size():
    sentences = [make_sentence(f"s{i}", i, not_understood=(i == 0)) for i in range(20)]
    selected = quiz_selector.select(sentences, [], count=10)
    assert len(selected) == 10
    assert selected[0] == "s0"


def test_phrase_type_also_counts_as_vocab():
    sentences = [make_sentence("ph", 0), make_sentence("other", 1)]
    review_items = [make_review_item("ph", rtype="phrase")]
    selected = quiz_selector.select(sentences, review_items, count=10)
    assert selected[0] == "ph"


def test_sentence_type_review_item_does_not_count_as_vocab():
    sentences = [make_sentence("nu", 0, not_understood=True), make_sentence("other", 1)]
    review_items = [make_review_item("nu", rtype="sentence")]
    selected = quiz_selector.select(sentences, review_items, count=10)
    # 没听懂句仍入选（notUnderstood 档），但 sentence 类型不计入"含生词"档
    assert selected[0] == "nu"


# ---------- 2026-11-03 检测选题修订：滤水句 + 跟读同源 ----------


def test_interjections_and_short_sentences_excluded():
    """OK/Right 之类语气词与过短句无检测价值，不得进入题目池。"""
    sentences = [
        make_sentence("s1", 0, text="OK."),
        make_sentence("s2", 1, text="Right."),
        make_sentence("s3", 2, text="What?"),
        make_sentence("s4", 3, text="Bye bye."),
        make_sentence("s5", 4, text="I would like to go shopping once a week."),
    ]
    ids = quiz_selector.select(sentences, [], count=10)
    assert ids == ["s5"]


def test_shadowing_sentences_priority_tier():
    """跟读清单中的句子排在普通随机句之前（与跟读推荐同源）。"""
    sentences = [
        make_sentence("s1", 0, text="First long sentence here today."),
        make_sentence("s2", 1, text="Second long sentence here today."),
        make_sentence("s3", 2, text="Third long sentence here today."),
        make_sentence("s4", 3, text="Fourth long sentence here today."),
    ]
    ids = quiz_selector.select(sentences, [], count=2, shadowing_sentence_ids={"s3", "s4"})
    assert set(ids) == {"s3", "s4"}


def test_make_sentence_accepts_text_override():
    s = make_sentence("x", 0)
    s2 = make_sentence("y", 1)
    assert quiz_selector.is_quizworthy(s) is True
    assert s2.text.startswith("Sentence number")
