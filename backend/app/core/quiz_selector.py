"""测验抽题（FR-029 + 2026-11-03 修订：滤水句、跟读同源、主旨优先）。

规则层（始终可用，离线兜底）：
- 池 = aligned 且**有检测价值**的句子：≥4 个词且非纯语气词（OK/Right/Bye 之类直接排除）；
- 优先级：没听懂 > 含生词/短语 > **跟读清单中的句子**（与跟读推荐同源）> 其余随机。

LLM 层（配置了大模型时由 api/quiz 先走 llm/quiz_pick，失败或未配置回退本规则）。
"""

import random

from ..models import ReviewItem, Sentence

# 纯语气/寒暄：无检测价值（2026-11-03 用户反馈"连 OK 都能推荐出来"）
_MIN_WORDS = 4
_INTERJECTIONS = {
    "ok", "okay", "right", "yeah", "yes", "no", "nope", "bye", "hello", "hi",
    "oh", "wow", "hmm", "ah", "ha", "great", "good", "fine", "sure", "well",
}


def is_quizworthy(sentence: Sentence) -> bool:
    """有检测价值的句子：已对齐、≥4 词、非纯语气词。"""
    if not sentence.aligned:
        return False
    tokens = sentence.text.split()
    if len(tokens) < _MIN_WORDS:
        return False
    if all(t.strip(".?!,;'\"“”").lower() in _INTERJECTIONS for t in tokens):
        return False
    return True


def select(
    sentences: list[Sentence],
    review_items: list[ReviewItem],
    count: int = 10,
    shadowing_sentence_ids: set[str] | None = None,
) -> list[str]:
    pool = [s for s in sentences if is_quizworthy(s)]
    vocab_sentence_ids = {r.sentenceId for r in review_items if r.type in ("word", "phrase")}
    shadow_ids = shadowing_sentence_ids or set()

    not_understood = [s for s in pool if s.notUnderstood]
    with_vocab = [s for s in pool if not s.notUnderstood and s.id in vocab_sentence_ids]
    in_shadowing = [
        s
        for s in pool
        if not s.notUnderstood and s.id not in vocab_sentence_ids and s.id in shadow_ids
    ]
    rest = [
        s
        for s in pool
        if not s.notUnderstood and s.id not in vocab_sentence_ids and s.id not in shadow_ids
    ]
    random.shuffle(rest)

    ordered = not_understood + with_vocab + in_shadowing + rest
    return [s.id for s in ordered[:count]]
