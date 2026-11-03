"""测验接口（contracts/api.md「测验 Quiz」节，FR-029~033）。

- POST /api/materials/{id}/quiz/generate  按优先级抽题，创建 in_progress 草稿
                                          （data/materials/<id>/quizzes.json，刷新可恢复）
- GET  /api/quiz/{quizId}                 恢复测验：items 保留已答内容，answers 为原句对照
- POST /api/materials/{id}/quiz/submit    归一化判分，草稿转 completed，
                                          ≥90 流转 mastered、bestScore 取历史最大（不降级）

错误约定：400 校验失败；404 材料/测验/句子不存在；409 仅音频模式或已有未完成草稿。
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import material_store, quiz_selector, review_store, scoring
from ..llm import quiz_pick
from ..models import Quiz, QuizItem, now_iso
from .settings import _read_settings
from ..storage.json_store import read_json, write_json_atomic

router = APIRouter()


class QuizGenerateIn(BaseModel):
    count: int = Field(default=10, ge=1, le=100)


class QuizSubmitItemIn(BaseModel):
    sentenceId: str
    userInput: Optional[str] = None


class QuizSubmitIn(BaseModel):
    quizId: str
    items: list[QuizSubmitItemIn] = Field(default_factory=list)


def _quizzes_path(material_id: str) -> str:
    return os.path.join(material_store.DATA_DIR, "materials", material_id, "quizzes.json")


def _load_quizzes(material_id: str) -> list[Quiz]:
    raw = read_json(_quizzes_path(material_id), default=[])
    if not isinstance(raw, list):
        return []
    return [Quiz(**q) for q in raw]


def _save_quizzes(material_id: str, quizzes: list[Quiz]) -> None:
    write_json_atomic(
        _quizzes_path(material_id), [q.model_dump(mode="json") for q in quizzes]
    )


def _find_quiz(quiz_id: str) -> Optional[tuple[str, Quiz]]:
    root = os.path.join(material_store.DATA_DIR, "materials")
    if not os.path.isdir(root):
        return None
    for entry in sorted(os.listdir(root)):
        for quiz in _load_quizzes(entry):
            if quiz.id == quiz_id:
                return entry, quiz
    return None


def _get_material(material_id: str):
    loaded = material_store.load(material_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    return loaded


@router.post("/api/materials/{material_id}/quiz/generate", status_code=201)
def generate_quiz(material_id: str, body: QuizGenerateIn):
    material, _turns, _blocks, sentences = _get_material(material_id)
    if material.audioOnly:
        raise HTTPException(status_code=409, detail="材料为仅音频模式，无法生成测验")

    quizzes = _load_quizzes(material_id)
    existing = next((q for q in quizzes if q.status == "in_progress"), None)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"message": "存在未完成的测验", "quizId": existing.id},
        )

    count = body.count or 10
    review_items = review_store.list_items()
    loaded = material_store.load(material_id)
    shadow_ids = set()
    if loaded is not None:
        try:
            from .shadowing import _load_items

            shadow_ids = {
                it.anchorStart.sentenceId
                for it in _load_items(material_id)
                if it.status == "active"
            }
        except Exception:  # noqa: BLE001 - 跟读清单缺失不影响出题
            shadow_ids = set()

    rule_ids = quiz_selector.select(
        sentences, review_items, count=count, shadowing_sentence_ids=shadow_ids
    )

    # LLM 主旨选题（缓存于材料；失败/未配置静默回退纯规则）
    focus_ids = list(material.quizFocusIds or [])
    if not focus_ids:
        try:
            focus_ids = quiz_pick.pick(sentences, review_items, count, _read_settings())
        except Exception:  # noqa: BLE001
            focus_ids = []
        if focus_ids:
            material.quizFocusIds = focus_ids
            if loaded is not None:
                material_store.save(material, loaded[1], loaded[2], sentences)

    pool_ids = set(quiz_selector.select(sentences, review_items, count=len(sentences)))
    merged: list[str] = []
    seen: set[str] = set()
    for sid in focus_ids + rule_ids:
        if len(merged) >= count:
            break
        if sid in pool_ids and sid not in seen:
            merged.append(sid)
            seen.add(sid)

    sentence_ids = merged or rule_ids
    quiz = Quiz(
        materialId=material_id,
        items=[QuizItem(sentenceId=sid) for sid in sentence_ids],
    )
    quizzes.append(quiz)
    _save_quizzes(material_id, quizzes)
    return {"quizId": quiz.id, "items": [{"sentenceId": sid} for sid in sentence_ids]}


@router.get("/api/quiz/{quiz_id}")
def get_quiz(quiz_id: str):
    found = _find_quiz(quiz_id)
    if found is None:
        raise HTTPException(status_code=404, detail="测验不存在")
    material_id, quiz = found
    loaded = material_store.load(material_id)
    texts = {s.id: s.text for s in loaded[3]} if loaded is not None else {}
    return {
        "quizId": quiz.id,
        "materialId": quiz.materialId,
        "status": quiz.status,
        "items": [item.model_dump() for item in quiz.items],
        "answers": {item.sentenceId: texts.get(item.sentenceId) for item in quiz.items},
    }


@router.post("/api/materials/{material_id}/quiz/submit")
def submit_quiz(material_id: str, body: QuizSubmitIn):
    material, turns, blocks, sentences = _get_material(material_id)
    quizzes = _load_quizzes(material_id)
    quiz = next((q for q in quizzes if q.id == body.quizId), None)
    if quiz is None:
        raise HTTPException(status_code=404, detail="测验不存在")

    texts = {s.id: s.text for s in sentences}
    results = []
    correct_count = 0
    for item in body.items:
        reference = texts.get(item.sentenceId)
        if reference is None:
            raise HTTPException(status_code=404, detail="句子不存在")
        correct = scoring.grade(item.userInput or "", reference)
        correct_count += 1 if correct else 0
        results.append(
            {"sentenceId": item.sentenceId, "userInput": item.userInput, "correct": correct}
        )

    total = len(results)
    quiz.status = "completed"
    quiz.completedAt = now_iso()
    quiz.items = [
        QuizItem(sentenceId=r["sentenceId"], userInput=r["userInput"], correct=r["correct"])
        for r in results
    ]
    quiz.correctCount = correct_count
    quiz.totalCount = total
    quiz.score = round(correct_count / total * 100, 2) if total else 0.0
    _save_quizzes(material_id, quizzes)

    material.bestScore = max(material.bestScore or 0.0, quiz.score)
    if quiz.score >= 90:
        material.stage = "mastered"
    material.updatedAt = now_iso()
    material_store.save(material, turns, blocks, sentences)

    return {
        "correctCount": quiz.correctCount,
        "totalCount": quiz.totalCount,
        "score": quiz.score,
        "results": results,
        "material": {"stage": material.stage, "bestScore": material.bestScore},
    }
