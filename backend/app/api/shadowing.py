"""跟读片段接口（contracts/api.md「跟读 Shadowing」节，FR-023~026）。

- GET    /api/materials/{id}/shadowing                 清单（active/ignored）
- POST   /api/materials/{id}/shadowing                 手动创建（范围含未对齐句 → 409）
- DELETE /api/materials/{id}/shadowing/{sid}           移除
- POST   /api/materials/{id}/shadowing/{sid}/ignore    忽略推荐（不再重复出现）
- POST   /api/materials/{id}/shadowing/recommend       大模型候选（未配置 → 400，失败 → 502）

数据存 data/materials/<id>/shadowing.json（ShadowingItem 数组）。
错误约定：400 校验失败；404 材料/片段不存在；409 范围含未对齐句或重复范围。
"""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import material_store
from ..llm import recommend as llm_recommend
from ..models import Anchor, ShadowingItem, ShadowingSource
from ..storage.json_store import read_json, write_json_atomic
from . import settings as settings_api

router = APIRouter()


class ShadowingCreateIn(BaseModel):
    text: str = Field(min_length=1)
    anchorStart: Anchor
    anchorEnd: Anchor
    source: ShadowingSource = "manual"


def _shadowing_path(material_id: str) -> str:
    return os.path.join(material_store.DATA_DIR, "materials", material_id, "shadowing.json")


def _load_items(material_id: str) -> list[ShadowingItem]:
    raw = read_json(_shadowing_path(material_id), default=[])
    return [ShadowingItem(**item) for item in raw]


def _save_items(material_id: str, items: list[ShadowingItem]) -> None:
    write_json_atomic(_shadowing_path(material_id), [item.model_dump() for item in items])


def _anchor_key(item: ShadowingItem) -> tuple:
    return (
        item.anchorStart.sentenceId,
        item.anchorStart.wordIndex,
        item.anchorEnd.sentenceId,
        item.anchorEnd.wordIndex,
    )


def _derive_range(sentences, body: ShadowingCreateIn) -> tuple[float, float]:
    """校验锚点范围（句子存在、顺序合法、含未对齐句 409、词索引越界 400），
    返回 (audioStartSec, audioEndSec) = 起词 start / 止词 end。"""
    by_id = {s.id: s for s in sentences}
    start_sentence = by_id.get(body.anchorStart.sentenceId)
    end_sentence = by_id.get(body.anchorEnd.sentenceId)
    if start_sentence is None or end_sentence is None:
        raise HTTPException(status_code=404, detail="句子不存在")
    if (start_sentence.index, body.anchorStart.wordIndex) > (
        end_sentence.index,
        body.anchorEnd.wordIndex,
    ):
        raise HTTPException(status_code=400, detail="锚点范围无效：起点位于终点之后")
    in_range = [s for s in sentences if start_sentence.index <= s.index <= end_sentence.index]
    if any(not s.aligned for s in in_range):
        raise HTTPException(status_code=409, detail="范围包含未对齐句子")
    for sentence, word_index in (
        (start_sentence, body.anchorStart.wordIndex),
        (end_sentence, body.anchorEnd.wordIndex),
    ):
        if not sentence.words or word_index >= len(sentence.words):
            raise HTTPException(status_code=400, detail="wordIndex 超出句子词数")
    audio_start = start_sentence.words[body.anchorStart.wordIndex].start
    audio_end = end_sentence.words[body.anchorEnd.wordIndex].end
    if audio_start is None or audio_end is None:
        raise HTTPException(status_code=400, detail="锚点词缺少时间戳（该词未映射到音频）")
    return audio_start, audio_end


@router.get("/api/materials/{material_id}/shadowing")
def list_shadowing(material_id: str):
    if material_store.load(material_id) is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    items = [item for item in _load_items(material_id) if item.status in ("active", "ignored")]
    # 播放区间随锚点 + 当前句子时间戳重新推导（AI 对齐升级后旧条目自动获得新时间）
    loaded = material_store.load(material_id)
    if loaded is not None:
        sentences = loaded[3]
        by_id = {s.id: s for s in sentences}
        for item in items:
            try:
                start_w = by_id[item.anchorStart.sentenceId].words[item.anchorStart.wordIndex]
                end_w = by_id[item.anchorEnd.sentenceId].words[item.anchorEnd.wordIndex]
            except (KeyError, IndexError):
                continue
            if start_w.start is not None and end_w.end is not None:
                item.audioStartSec = float(start_w.start)
                item.audioEndSec = float(end_w.end)
    return [item.model_dump() for item in items]


@router.post("/api/materials/{material_id}/shadowing", status_code=201)
def create_shadowing(material_id: str, body: ShadowingCreateIn):
    loaded = material_store.load(material_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    _, _, _, sentences = loaded
    audio_start, audio_end = _derive_range(sentences, body)

    items = _load_items(material_id)
    probe = ShadowingItem(
        materialId=material_id,
        text=body.text,
        anchorStart=body.anchorStart,
        anchorEnd=body.anchorEnd,
        audioStartSec=audio_start,
        audioEndSec=audio_end,
        source=body.source,
    )
    active_keys = {_anchor_key(item) for item in items if item.status == "active"}
    if _anchor_key(probe) in active_keys:
        raise HTTPException(status_code=409, detail="该范围已存在跟读片段")
    items.append(probe)
    _save_items(material_id, items)
    return probe.model_dump()


@router.delete("/api/materials/{material_id}/shadowing/{shadowing_id}")
def delete_shadowing(material_id: str, shadowing_id: str):
    if material_store.load(material_id) is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    items = _load_items(material_id)
    remaining = [item for item in items if item.id != shadowing_id]
    if len(remaining) == len(items):
        raise HTTPException(status_code=404, detail="跟读片段不存在")
    _save_items(material_id, remaining)
    return {"deleted": True}


@router.post("/api/materials/{material_id}/shadowing/{shadowing_id}/ignore")
def ignore_shadowing(material_id: str, shadowing_id: str):
    if material_store.load(material_id) is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    items = _load_items(material_id)
    for item in items:
        if item.id == shadowing_id:
            item.status = "ignored"
            _save_items(material_id, items)
            return item.model_dump()
    raise HTTPException(status_code=404, detail="跟读片段不存在")


@router.post("/api/materials/{material_id}/shadowing/recommend")
def recommend_shadowing(material_id: str):
    loaded = material_store.load(material_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    _, _, _, sentences = loaded
    settings = settings_api._read_settings()
    try:
        candidates = llm_recommend.recommend(sentences, settings)
    except llm_recommend.LlmNotConfiguredError:
        raise HTTPException(status_code=400, detail="未配置大模型")
    except llm_recommend.LlmCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # 已存在（active/ignored）的范围不再推荐（FR-024：忽略的不再重复出现）
    existing = _load_items(material_id)
    taken = {_anchor_key(item) for item in existing if item.status in ("active", "ignored")}
    fresh: list[dict] = []
    for candidate in candidates:
        key = (
            candidate["anchorStart"]["sentenceId"],
            candidate["anchorStart"]["wordIndex"],
            candidate["anchorEnd"]["sentenceId"],
            candidate["anchorEnd"]["wordIndex"],
        )
        if key in taken:
            continue
        taken.add(key)
        fresh.append(candidate)
    return {"candidates": fresh}
