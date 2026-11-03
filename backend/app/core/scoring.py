"""测验判分归一化（data-model.md「抽题规则」Assumptions 2026-10-28）。

归一化 = trim + 忽略大小写 + 忽略全部标点（Unicode P 类，含全角/连接号）+
全角转半角（NFKC）；缩写不展开。
"""

import unicodedata


def _strip_punct(s: str) -> str:
    return "".join(ch for ch in s if not unicodedata.category(ch).startswith("P"))


def normalize(s: str) -> str:
    """NFKC + 小写 + 去全部标点 + 压缩空白。"""
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = _strip_punct(s)
    return " ".join(s.split())


def grade(user_input: str, reference: str) -> bool:
    """归一化后相等判对。"""
    return normalize(user_input) == normalize(reference)
