"""学习标记接口（contracts/api.md「学习标记 Markings」节，FR-019/FR-020）。

- POST   /api/materials/{id}/sentences/{sid}/vocab        创建 ReviewItem（去重，释义可空）
- DELETE /api/materials/{id}/sentences/{sid}/vocab        删除对应 ReviewItem
- PUT    /api/materials/{id}/sentences/{sid}/not-understood  置/取消没听懂标记并同步 sentence 条目

错误约定：400 校验失败；404 材料/句子/条目不存在；409 重复标记。
"""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import material_store, review_store
from ..models import Sentence

router = APIRouter()


class VocabMarkIn(BaseModel):
    text: str = Field(min_length=1)
    wordStart: int = Field(ge=0)
    wordEnd: int = Field(ge=0)
    type: Literal["word", "phrase"]
    meaning: Optional[str] = None


class VocabDeleteIn(BaseModel):
    text: str = Field(min_length=1)
    type: Literal["word", "phrase"]


class NotUnderstoodIn(BaseModel):
    marked: bool


def _get_sentence(material_id: str, sentence_id: str) -> tuple[Sentence, list[Sentence]]:
    loaded = material_store.load(material_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    _material, _turns, _blocks, sentences = loaded
    for sentence in sentences:
        if sentence.id == sentence_id:
            return sentence, sentences
    raise HTTPException(status_code=404, detail="句子不存在")


def _save_sentence_flag(material_id: str, sentences: list[Sentence], target: Sentence) -> None:
    loaded = material_store.load(material_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    material, turns, blocks, _ = loaded
    replaced = [target if s.id == target.id else s for s in sentences]
    material_store.save(material, turns, blocks, replaced)


@router.post("/api/materials/{material_id}/sentences/{sentence_id}/vocab", status_code=201)
def create_vocab(material_id: str, sentence_id: str, body: VocabMarkIn):
    sentence, _ = _get_sentence(material_id, sentence_id)
    item, created = review_store.create(
        material_id=material_id,
        sentence_id=sentence_id,
        text=body.text,
        rtype=body.type,
        context_text=sentence.text,
        meaning=body.meaning,
    )
    if not created:
        raise HTTPException(status_code=409, detail="该词/短语已标记")
    return item


@router.delete("/api/materials/{material_id}/sentences/{sentence_id}/vocab")
def delete_vocab(material_id: str, sentence_id: str, body: VocabDeleteIn):
    _get_sentence(material_id, sentence_id)
    item = review_store.find(material_id, sentence_id, body.text, body.type)
    if item is None:
        raise HTTPException(status_code=404, detail="标记不存在")
    review_store.delete(item.id)
    return {"deleted": True}


@router.put("/api/materials/{material_id}/sentences/{sentence_id}/not-understood")
def set_not_understood(material_id: str, sentence_id: str, body: NotUnderstoodIn):
    sentence, sentences = _get_sentence(material_id, sentence_id)
    if body.marked:
        sentence.notUnderstood = True
        _save_sentence_flag(material_id, sentences, sentence)
        item, _created = review_store.create(
            material_id=material_id,
            sentence_id=sentence_id,
            rtype="sentence",
            text=sentence.text,
            context_text=sentence.text,
        )
        return {"notUnderstood": True, "reviewItemId": item.id}
    sentence.notUnderstood = False
    _save_sentence_flag(material_id, sentences, sentence)
    review_store.delete_by_sentence_type(material_id, sentence_id, "sentence")
    return {"notUnderstood": False}
