"""T012: scoring 单元测试（判分归一化，Assumptions 2026-10-28）。

归一化 = trim + 忽略大小写 + 忽略全部标点 + 全角转半角（NFKC）；缩写不展开。
"""

from backend.app.core import scoring


def test_normalize_ignores_case_and_punctuation():
    assert scoring.normalize("Hello, World!") == "hello world"
    assert scoring.normalize("  Spaced   out . ") == "spaced out"


def test_normalize_fullwidth_to_halfwidth():
    assert scoring.normalize("Ｈｅｌｌｏ，　Ｗｏｒｌｄ！") == "hello world"


def test_normalize_removes_all_punctuation():
    assert scoring.normalize("don't-stop_believin'…") == "dontstopbelievin"
    assert scoring.normalize("a。b、c！d？") == "abcd"


def test_grade_equal_after_normalization():
    assert scoring.grade("Hello, World!", "hello world") is True
    assert scoring.grade("  Fully Ｃorrect。 ", "fully correct") is True


def test_grade_not_equal():
    assert scoring.grade("hello worlds", "hello world") is False
    assert scoring.grade("goodbye", "hello") is False


def test_grade_does_not_expand_contractions():
    # 判分归一化不展开缩写：I'm ≠ I am
    assert scoring.grade("I'm fine.", "im fine") is True
    assert scoring.grade("I'm", "I am") is False
