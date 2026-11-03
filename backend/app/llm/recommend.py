"""大模型跟读推荐（contracts/api.md「跟读 Shadowing」节，FR-024/FR-028）。

OpenAI 兼容客户端；三厂商预设 base_url（FR-044）。prompt 仅含材料文稿文本
（不上传音频），要求返回 JSON 数组候选；候选 text 在材料句序列中做词级归一化
匹配（可跨句），映射回 {anchorStart, anchorEnd}，定位失败的候选跳过。

错误约定（api.md）：未配置大模型（未启用/缺 key/缺模型名）→ LlmNotConfiguredError
（API 层转 400）；调用失败 → LlmCallError（API 层转 502）。
"""

import json
import re
from typing import Optional

from ..models import Sentence, Settings
from ..models import LlmSettings

PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "kimi": "https://api.moonshot.cn/v1",
}

PROMPT_TEMPLATE = (
    "以下是一篇英语听力材料的全部句子（每行一句）：\n\n{context}\n\n"
    "任务：按下面三条标准，**精选最多 10 个**最值得跟读的片段——宁缺毋滥，"
    "不要把所有句子都列出来：\n"
    "1. 句型高频、可迁移——句型骨架练会一句、多处复用（提观点、举例、转折、建议、比较等）；\n"
    "2. 连读弱读典型、能练到嘴——含自然的连读、弱读、重音或语调样板，模仿价值高；\n"
    "3. 表达地道、值得整句搬走——native 高频语块、惯用表达。\n"
    "要求：\n"
    "- 每个候选必须至少命中一条标准；\n"
    "- 排除寒暄与信息量少的话（如 Hello / How are you / Right / OK / What about you / Bye 等）；\n"
    "- 候选必须逐字摘自上面的句子，可跨相邻句组合成一个语块，不要改写、翻译或添加内容；\n"
    '- 每个候选用 reason 字段标注命中的标准编号（"1" "2" "3"，可多个，如 "1,2"）。\n'
    '严格返回 JSON 数组：[{{"text": "...", "reason": "1,2"}}]，不要输出任何其他内容。'
)


class LlmNotConfiguredError(Exception):
    """未配置大模型（未启用、缺 API Key 或缺模型名）。"""


class LlmCallError(Exception):
    """大模型调用失败或返回不可用。"""


_PUNCT_RE = re.compile(r"[^\w\s]|_")


def _norm_tokens(text: str) -> list[str]:
    """词级归一化：小写 + 去标点/下划线 + 按空白切分。"""
    return _PUNCT_RE.sub("", text.lower()).split()


def _create_client(settings: LlmSettings, max_retries: int | None = None):
    from openai import OpenAI

    kwargs: dict = {
        "api_key": settings.apiKey,
        "base_url": PROVIDER_BASE_URLS[settings.provider],
    }
    if max_retries is not None:
        kwargs["max_retries"] = max_retries  # 客户端级参数：长输出调用禁用自动重试
    return OpenAI(**kwargs)


def thinking_extra_body(llm: LlmSettings) -> dict:
    """思考模式传参（Kimi 私有扩展）：默认关闭思考——K2 思考型模型关闭后速度接近 turbo。

    仅 Kimi 服务商支持该参数；其他厂商不传，避免未知字段导致 400。
    """
    if llm.provider != "kimi":
        return {}
    return {"thinking": {"type": "enabled" if llm.thinking else "disabled"}}


def _extract_texts(content: str) -> list[dict]:
    """从模型输出中提取候选列表 [{text, reason}]；容忍 markdown 代码围栏。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LlmCallError(f"大模型返回不是合法 JSON: {exc}") from exc
    if not isinstance(data, list):
        raise LlmCallError("大模型返回不是 JSON 数组")
    items: list[dict] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            candidate = item["text"].strip()
            if candidate:
                reason = str(item.get("reason", "") or "").strip()
                items.append({"text": candidate, "reason": reason})
    return items


def _build_tokens(sentences: list[Sentence]) -> list[tuple[str, str, int]]:
    """全局词序列：(归一化词, sentenceId, wordIndex)，仅含已对齐且有词时间戳的句。"""
    tokens: list[tuple[str, str, int]] = []
    for sentence in sentences:
        if not sentence.aligned or not sentence.words:
            continue
        for idx, word in enumerate(sentence.words):
            norm = _norm_tokens(word.w)
            if norm:
                tokens.append((norm[0], sentence.id, idx))
    return tokens


def _locate(
    candidate: str, tokens: list[tuple[str, str, int]]
) -> Optional[dict]:
    """候选文本在全局词序列中连续匹配，返回锚点；失败返回 None。"""
    needle = _norm_tokens(candidate)
    if not needle:
        return None
    seq = [t[0] for t in tokens]
    n = len(needle)
    for i in range(len(seq) - n + 1):
        if seq[i : i + n] == needle:
            first = tokens[i]
            last = tokens[i + n - 1]
            return {
                "anchorStart": {"sentenceId": first[1], "wordIndex": first[2]},
                "anchorEnd": {"sentenceId": last[1], "wordIndex": last[2]},
            }
    return None


def recommend(sentences: list[Sentence], settings: Settings) -> list[dict]:
    """生成跟读候选 [{text, anchorStart, anchorEnd}]；定位失败的候选跳过。"""
    llm = settings.llm
    if (
        not llm.enabled
        or not llm.apiKey
        or llm.apiKey.startswith("****")
        or not llm.model
    ):
        raise LlmNotConfiguredError("未配置大模型")

    usable = [s for s in sentences if s.aligned and s.words]
    context = "\n".join(s.text for s in usable)
    if not context.strip():
        raise LlmCallError("材料中没有已对齐的句子，无法推荐")

    client = _create_client(llm)
    kwargs: dict = {
        "model": llm.model,
        "messages": [
            {"role": "system", "content": "你是英语听力学习助手，只输出 JSON。"},
            {"role": "user", "content": PROMPT_TEMPLATE.format(context=context)},
        ],
    }
    extra = thinking_extra_body(llm)
    if extra:
        kwargs["extra_body"] = extra
    try:
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
    except LlmNotConfiguredError:
        raise
    except Exception as exc:
        detail = str(exc)
        status = getattr(exc, "status_code", None)
        if status is not None:
            body = getattr(getattr(exc, "response", None), "text", "") or ""
            detail = f"HTTP {status}: {body[:300]}" if body else f"HTTP {status}: {detail}"
        raise LlmCallError(f"大模型调用失败: {detail}") from exc

    tokens = _build_tokens(usable)
    candidates: list[dict] = []
    seen: set[tuple] = set()
    for item in _extract_texts(content):
        text = item["text"]
        located = _locate(text, tokens)
        if located is None:
            continue
        key = (
            located["anchorStart"]["sentenceId"],
            located["anchorStart"]["wordIndex"],
            located["anchorEnd"]["sentenceId"],
            located["anchorEnd"]["wordIndex"],
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"text": text, "reason": item["reason"], **located})
    return candidates
