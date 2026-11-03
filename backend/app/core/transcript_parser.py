"""文稿解析（FR-007）。

把导入的纯文本原文稿解析为 Turn → Block → Sentence 层级：

- 单独成行的说话人标签：短文本，可带中文译名（``Neil 尼尔``）、可带冒号（``Beth:``），
  兼容行内形式（``Beth: Hello...``）；
- 英文正文按 ``. ? ! ;`` 切句，归属当前说话人；
- 中文字符占比过半的行判为译文，挂到最近一个英文段落块（多块按原序拼接）；
- 无标签材料全文视为单一说话人（speakerName=None），按空行划分话轮；
- 既不像标签也不像正文/译文的行按英文正文兜底，绝不丢内容。
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from ..models import Block, Sentence, Turn

MAX_LABEL_LEN = 40

_SENT_SPLIT = re.compile(r"[^.?!;。！？]*[.?!;。！？]+|[^.?!;。！？]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CJK_FULL_RE = re.compile(r"^[\u4e00-\u9fff·]+$")
_NAME_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.'’\-]*$")
_BARE_NAME_RE = re.compile(r"^[A-Z][a-z]{1,19}$")
_INLINE_LABEL_RE = re.compile(r"^([^:：]{1,40})[:：]\s*(\S.*)$")


_DOMAIN_RE = re.compile(
    r"\b[\w-]+\.(?:com|org|net|edu|gov|io|app|dev|co\.uk)(?:/[\w./-]*)?\b", re.IGNORECASE
)
_PROTECT = "@@DOT@@"


def split_sentences(text: str) -> list[str]:
    """按 ``. ? ! ;`` 及中文句号切句，保留句末标点；保护域名/URL 中的点不被误切。"""

    def _mask(m: re.Match) -> str:
        return m.group(0).replace(".", _PROTECT)

    masked = _DOMAIN_RE.sub(_mask, text or "")
    parts = [m.group(0).strip() for m in _SENT_SPLIT.finditer(masked) if m.group(0).strip()]
    return [p.replace(_PROTECT, ".") for p in parts]


def _is_cjk_token(token: str) -> bool:
    return bool(_CJK_FULL_RE.match(token))


def _split_name(text: str) -> Optional[tuple[str, Optional[str]]]:
    """校验说话人名片段，返回 (英文名, 中文译名|None)；不像名字返回 None。"""
    text = text.strip()
    if not text or len(text) > MAX_LABEL_LEN:
        return None
    if text[-1] in ".?!;":
        return None
    tokens = text.split()
    if not tokens:
        return None
    name_zh = None
    core = tokens
    if len(tokens) >= 2 and _is_cjk_token(tokens[-1]):
        name_zh = tokens[-1]
        core = tokens[:-1]
    if not core or len(core) > 2:
        return None
    for token in core:
        if not _NAME_TOKEN_RE.match(token):
            return None
    if not any(re.search(r"[A-Za-z]", token) for token in core):
        return None
    return " ".join(core), name_zh


def _classify_label(line: str) -> Optional[tuple[str, Optional[str], str]]:
    """识别说话人标签行，返回 (name, nameZh, 行内剩余正文)；非标签返回 None。"""
    s = line.strip()
    if not s:
        return None
    # 行内形式：Beth: Hello...
    m = _INLINE_LABEL_RE.match(s)
    if m and not s.endswith((":", "：")):
        name = _split_name(m.group(1))
        if name is not None:
            return name[0], name[1], m.group(2).strip()
        return None
    # 带冒号的独立标签：Beth:
    if s.endswith((":", "：")):
        name = _split_name(s[:-1])
        if name is not None:
            return name[0], name[1], ""
        return None
    # 带中文译名的独立标签：Neil 尼尔
    name = _split_name(s)
    if name is not None and name[1] is not None:
        return name[0], name[1], ""
    # 裸名单词独立成行（Title Case 短词），如 Neil / Georgie
    if _BARE_NAME_RE.match(s):
        return s, None, ""
    return None


def _chinese_ratio(line: str) -> float:
    compact = re.sub(r"\s", "", line)
    if not compact:
        return 0.0
    return len(_CJK_RE.findall(compact)) / len(compact)


@dataclass
class SentenceData:
    id: str
    text: str


@dataclass
class BlockData:
    id: str
    index: int
    translationLines: list[str] = field(default_factory=list)
    sentences: list[SentenceData] = field(default_factory=list)


@dataclass
class TurnData:
    id: str
    index: int
    speakerName: Optional[str] = None
    speakerNameZh: Optional[str] = None
    blocks: list[BlockData] = field(default_factory=list)


@dataclass
class ParseResult:
    turns: list[TurnData]

    @property
    def stats(self) -> dict:
        speakers: list[dict] = []
        seen = set()
        for turn in self.turns:
            if turn.speakerName is None or turn.speakerName in seen:
                continue
            seen.add(turn.speakerName)
            speakers.append({"name": turn.speakerName, "nameZh": turn.speakerNameZh})
        return {
            "speakers": speakers,
            "turnCount": len(self.turns),
            "blockCount": sum(len(t.blocks) for t in self.turns),
            "translationLineCount": sum(
                len(b.translationLines) for t in self.turns for b in t.blocks
            ),
        }

    def to_dict(self) -> dict:
        """供 /api/import/parse 预览序列化（FR-008）。"""
        return {
            **self.stats,
            "turns": [
                {
                    "id": t.id,
                    "index": t.index,
                    "speakerName": t.speakerName,
                    "speakerNameZh": t.speakerNameZh,
                    "blocks": [
                        {
                            "id": b.id,
                            "index": b.index,
                            "translationLines": list(b.translationLines),
                            "sentences": [{"id": s.id, "text": s.text} for s in b.sentences],
                        }
                        for b in t.blocks
                    ],
                }
                for t in self.turns
            ],
        }


def _new_id() -> str:
    from ..models import new_id

    return new_id()


def _parse_labeled(lines: list[str]) -> list[TurnData]:
    turns: list[TurnData] = []
    current_turn: Optional[TurnData] = None
    current_block: Optional[BlockData] = None
    last_text_block: Optional[BlockData] = None

    def start_turn(name: Optional[str], name_zh: Optional[str]) -> None:
        nonlocal current_turn, current_block
        current_turn = TurnData(id=_new_id(), index=len(turns), speakerName=name, speakerNameZh=name_zh)
        turns.append(current_turn)
        current_block = None

    for line in lines:
        if not line.strip():
            current_block = None  # 空行分段：下一段英文开新段落块
            continue
        label = _classify_label(line)
        if label is not None:
            name, name_zh, rest = label
            start_turn(name, name_zh)
            if rest:
                current_block = BlockData(id=_new_id(), index=0)
                current_turn.blocks.append(current_block)
                for frag in split_sentences(rest):
                    if _chinese_ratio(frag) > 0.5:
                        current_block.translationLines.append(frag)
                    else:
                        current_block.sentences.append(SentenceData(id=_new_id(), text=frag))
                last_text_block = current_block
            continue
        if _chinese_ratio(line) > 0.5:
            # 译文挂最近英文段落块（当前块优先，空行后回溯到最近有正文的块）
            target = current_block if current_block is not None else last_text_block
            if target is None:
                # 文首无英文块，按正文兜底
                if current_turn is None:
                    start_turn(None, None)
                current_block = BlockData(id=_new_id(), index=len(current_turn.blocks))
                current_turn.blocks.append(current_block)
                target = current_block
                last_text_block = current_block
            target.translationLines.append(line.strip())
            continue
        # 英文正文（兜底路径同样走到这里）；逐片段分类：中文片段进译文，英文片段进句子
        if current_turn is None:
            start_turn(None, None)
        # 译文行之后的英文行开新段落块（BBC 粘贴格式：段落间无空行，靠"英-译-英"换段）
        if current_block is None or current_block.translationLines:
            current_block = BlockData(id=_new_id(), index=len(current_turn.blocks))
            current_turn.blocks.append(current_block)
        for frag in split_sentences(line):
            if _chinese_ratio(frag) > 0.5:
                current_block.translationLines.append(frag)
            else:
                current_block.sentences.append(SentenceData(id=_new_id(), text=frag))
        last_text_block = current_block

    return turns


def _parse_untagged(lines: list[str]) -> list[TurnData]:
    # 无标签材料：空行划分话轮，每个非空段落 = 一个话轮（单一说话人 speakerName=None）
    turns: list[TurnData] = []
    paragraph: list[str] = []

    def flush() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        turn = TurnData(id=_new_id(), index=len(turns))
        block = BlockData(id=_new_id(), index=0)
        turn.blocks.append(block)
        for line in paragraph:
            for frag in split_sentences(line):
                if _chinese_ratio(frag) > 0.5:
                    block.translationLines.append(frag.strip())
                else:
                    block.sentences.append(SentenceData(id=_new_id(), text=frag.strip()))
        turns.append(turn)
        paragraph = []

    for line in lines:
        if line.strip():
            paragraph.append(line)
        else:
            flush()
    flush()
    return turns


def parse(text: str) -> ParseResult:
    """解析文稿，返回 ParseResult（turns + stats）。"""
    lines = unicodedata.normalize("NFC", text or "").splitlines()
    labeled = any(_classify_label(line) is not None for line in lines if line.strip())
    if labeled:
        return ParseResult(turns=_parse_labeled(lines))
    return ParseResult(turns=_parse_untagged(lines))


def to_models(result: ParseResult, material_id: str) -> dict:
    """把解析结果转成 models.Turn/Block/Sentence（入库用，aligned=False 待对齐）。"""
    turns: list[Turn] = []
    blocks: list[Block] = []
    sentences: list[Sentence] = []
    index = 0
    for t in result.turns:
        turn = Turn(
            id=t.id,
            materialId=material_id,
            index=t.index,
            speakerName=t.speakerName,
            speakerNameZh=t.speakerNameZh,
        )
        turns.append(turn)
        for b in t.blocks:
            block = Block(id=b.id, turnId=turn.id, index=b.index, translationLines=list(b.translationLines))
            blocks.append(block)
            for s in b.sentences:
                sentences.append(
                    Sentence(
                        id=s.id,
                        materialId=material_id,
                        turnId=turn.id,
                        blockId=block.id,
                        index=index,
                        text=s.text,
                        aligned=False,
                    )
                )
                index += 1
    return {"turns": turns, "blocks": blocks, "sentences": sentences}
