"""全局复习队列存储（data/review-queue.json，跨材料汇总，data-model.md ReviewItem）。

提供 CRUD、(materialId, sentenceId, text, type) 去重创建、按材料级联清除。
新条目 intervalDays=1、dueAt=创建日 +1 天。
"""

import os
from datetime import date, timedelta
from typing import Optional

from ..models import ReviewItem, ReviewType
from ..storage.json_store import read_json, write_json_atomic

DATA_DIR = os.environ.get("DATA_DIR", os.path.join("data"))


def _queue_path() -> str:
    return os.path.join(DATA_DIR, "review-queue.json")


def list_items() -> list[ReviewItem]:
    raw = read_json(_queue_path(), default=[])
    if not isinstance(raw, list):
        return []
    return [ReviewItem(**item) for item in raw]


def _write(items: list[ReviewItem]) -> None:
    write_json_atomic(_queue_path(), [item.model_dump(mode="json") for item in items])


def find(material_id: str, sentence_id: str, text: str, rtype: ReviewType) -> Optional[ReviewItem]:
    for item in list_items():
        if (
            item.materialId == material_id
            and item.sentenceId == sentence_id
            and item.text == text
            and item.type == rtype
        ):
            return item
    return None


def create(
    material_id: str,
    sentence_id: str,
    text: str,
    rtype: ReviewType,
    context_text: str,
    meaning: Optional[str] = None,
) -> tuple[ReviewItem, bool]:
    """创建复习条目；按 (materialId, sentenceId, text, type) 去重。

    返回 (item, created)：重复标记时返回既有条目与 False。
    """
    existing = find(material_id, sentence_id, text, rtype)
    if existing is not None:
        return existing, False
    item = ReviewItem(
        type=rtype,
        text=text,
        meaning=meaning,
        materialId=material_id,
        sentenceId=sentence_id,
        contextText=context_text,
        intervalDays=1,
        dueAt=date.today() + timedelta(days=1),
    )
    items = list_items()
    items.append(item)
    _write(items)
    return item, True


def update(item: ReviewItem) -> None:
    """整条写回（复习调度自评后更新 intervalDays/dueAt 等）。"""
    items = list_items()
    for i, old in enumerate(items):
        if old.id == item.id:
            items[i] = item
            _write(items)
            return
    raise KeyError(f"review item not found: {item.id}")


def delete(item_id: str) -> bool:
    items = list_items()
    remaining = [item for item in items if item.id != item_id]
    if len(remaining) == len(items):
        return False
    _write(remaining)
    return True


def delete_by_sentence_type(material_id: str, sentence_id: str, rtype: ReviewType) -> int:
    """删除指定句子的某类型全部条目（取消没听懂标记路径）。"""
    items = list_items()
    remaining = [
        item
        for item in items
        if not (
            item.materialId == material_id
            and item.sentenceId == sentence_id
            and item.type == rtype
        )
    ]
    removed = len(items) - len(remaining)
    if removed:
        _write(remaining)
    return removed


def cascade_by_material(material_id: str) -> int:
    """材料删除级联：清除该材料的全部复习条目，返回清除数。"""
    items = list_items()
    remaining = [item for item in items if item.materialId != material_id]
    removed = len(items) - len(remaining)
    if removed:
        _write(remaining)
    return removed
