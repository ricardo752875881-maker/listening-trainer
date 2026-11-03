"""全局复习队列接口（contracts/api.md「全局复习队列 Review Queue」节，FR-038~044）。

- GET    /api/review/due              今日到期：{count, items}（≤20 张，FR-039 会话规则）
- POST   /api/review/items/{rid}/rate 自评调度（通过升档 / 未通过重置，FR-038）
- GET    /api/review/items             总览：materialId?/type?/sort=familiarity（FR-039）
- DELETE /api/review/items/{rid}       手动删除（唯一移除方式，FR-044）

错误约定：400 校验失败；404 条目不存在。
"""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import review_store, scheduler

router = APIRouter()


class RateIn(BaseModel):
    passed: bool


def _dump(item) -> dict:
    return item.model_dump(mode="json")


@router.get("/api/review/due")
def get_due():
    result = scheduler.due_items(limit=scheduler.SESSION_LIMIT)
    return {"count": result["count"], "items": [_dump(item) for item in result["items"]]}


@router.post("/api/review/items/{rid}/rate")
def rate_item(rid: str, body: RateIn):
    try:
        item = scheduler.rate(rid, body.passed)
    except KeyError:
        raise HTTPException(status_code=404, detail="复习条目不存在")
    return _dump(item)


@router.get("/api/review/items")
def list_items(
    materialId: Optional[str] = None,
    type: Optional[Literal["word", "phrase", "sentence"]] = None,
    sort: Optional[str] = None,
):
    items = review_store.list_items()
    if materialId is not None:
        items = [item for item in items if item.materialId == materialId]
    if type is not None:
        items = [item for item in items if item.type == type]
    if sort == "familiarity":
        items = sorted(items, key=lambda item: (item.knownCount, item.dueAt))
    return [_dump(item) for item in items]


@router.delete("/api/review/items/{rid}")
def delete_item(rid: str):
    if not review_store.delete(rid):
        raise HTTPException(status_code=404, detail="复习条目不存在")
    return {"deleted": True}
