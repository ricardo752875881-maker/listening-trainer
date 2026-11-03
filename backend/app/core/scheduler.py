"""全局复习队列调度（FR-038/039，data-model.md「调度状态机」「会话规则」）。

到期查询：dueAt ≤ today，按到期升序，单次会话最多取 20 张（count 为到期总数）。
rate 自评：通过 intervalDays 升一档（1→3→7→15→30，30 档保持 30 循环），
未通过重置 1 天；reviewCount 每次 +1、lastReviewAt = now。
"""

from datetime import date, timedelta
from typing import Optional

from ..models import INTERVALS, ReviewItem, now_iso
from . import review_store

SESSION_LIMIT = 20


def due_items(limit: int = SESSION_LIMIT, today: Optional[date] = None) -> dict:
    """今日到期条目：{count: 到期总数, items: 本次会话卡片（≤ limit，按 dueAt 升序）}。"""
    today = today or date.today()
    due = [item for item in review_store.list_items() if item.dueAt <= today]
    due.sort(key=lambda item: (item.dueAt, item.createdAt))
    return {"count": len(due), "items": due[:limit]}


def rate(item_id: str, passed: bool, today: Optional[date] = None) -> ReviewItem:
    """间隔重复自评调度；条目不存在抛 KeyError。"""
    today = today or date.today()
    item = next((i for i in review_store.list_items() if i.id == item_id), None)
    if item is None:
        raise KeyError(f"review item not found: {item_id}")

    if passed:
        index = INTERVALS.index(item.intervalDays)
        item.intervalDays = INTERVALS[min(index + 1, len(INTERVALS) - 1)]
        item.knownCount += 1
    else:
        item.intervalDays = INTERVALS[0]
    item.dueAt = today + timedelta(days=item.intervalDays)
    item.reviewCount += 1
    item.lastReviewAt = now_iso()
    review_store.update(item)
    return item
