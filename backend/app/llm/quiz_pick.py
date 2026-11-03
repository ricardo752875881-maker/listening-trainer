"""LLM 检测选题（2026-11-03，与跟读推荐同源）。

目标：出的题能检验"是否真听懂了这篇文章"——按**主旨覆盖 + 适合整句听写**选句，
优先用户标记过（没听懂/生词）的句子。结果由调用方缓存于 Material.quizFocusIds，
再测复用不重复调用；未配置或失败时回退规则抽题（quiz_selector）。
"""

from typing import Optional

from ..core.quiz_selector import is_quizworthy
from ..models import LlmSettings, ReviewItem, Sentence, Settings
from .recommend import _create_client, thinking_extra_body

PROMPT_TEMPLATE = (
    "以下是一篇英语听力材料的全部句子（每行：句子ID | 文本 | 用户标记）：\n\n{lines}\n\n"
    "任务：从中**精选最多 {count} 句**作为整句听写测验题，检验学习者是否真正听懂文章主旨。\n"
    "标准：\n"
    "1. 覆盖文章的主要信息点与关键论述（主旨优先，不要偏题碎句）；\n"
    "2. 适合整句听写——实义词为主、长度适中，排除寒暄与语气词（如 OK / Right / Bye 等）；\n"
    "3. 用户标记了【没听懂】【生词】的句子优先入选。\n"
    "只从给定句子中选择，返回句子 ID 数组。\n"
    '严格返回 JSON：{{"sentence_ids": ["<句子ID>", ...]}}，不要输出其他内容。'
)


def _flags(s: Sentence, vocab_ids: set[str]) -> str:
    marks = []
    if s.notUnderstood:
        marks.append("没听懂")
    if s.id in vocab_ids:
        marks.append("生词")
    return "、".join(marks) if marks else "-"


def pick(
    sentences: list[Sentence],
    review_items: list[ReviewItem],
    count: int,
    settings: Settings,
    client=None,
) -> list[str]:
    """返回选中的 sentenceId 列表（池 = 有检测价值的句子）；未配置/失败返回 []。"""
    llm: LlmSettings = settings.llm
    if (
        not llm.enabled
        or not llm.apiKey
        or llm.apiKey.startswith("****")
        or not llm.model
    ):
        return []
    usable = [s for s in sentences if is_quizworthy(s)]
    if not usable:
        return []
    if client is None:
        client = _create_client(llm)
    vocab_ids = {r.sentenceId for r in review_items if r.type in ("word", "phrase")}
    lines = "\n".join(
        f"{s.id} | {s.text} | {_flags(s, vocab_ids)}" for s in usable
    )
    kwargs: dict = {
        "model": llm.model,
        "messages": [
            {"role": "system", "content": "你是英语听力测验命题助手，只输出 JSON。"},
            {"role": "user", "content": PROMPT_TEMPLATE.format(lines=lines, count=count)},
        ],
    }
    extra = thinking_extra_body(llm)
    if extra:
        kwargs["extra_body"] = extra
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    return _extract_ids(content, {s.id for s in usable}, count)


def _extract_ids(content: str, valid_ids: set[str], count: int) -> list[str]:
    import json
    import re

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    data = json.loads(text[start : end + 1])
    ids = data.get("sentence_ids")
    if not isinstance(ids, list):
        return []
    picked: list[str] = []
    seen: set[str] = set()
    for sid in ids:
        if isinstance(sid, str) and sid in valid_ids and sid not in seen:
            picked.append(sid)
            seen.add(sid)
        if len(picked) >= count:
            break
    return picked
