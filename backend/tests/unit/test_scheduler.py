"""T038: scheduler 单元测试（FR-038/039 间隔重复调度与会话取卡）。

新条目 1 天后到期；通过升档 1→3→7→15→30→30 循环；未通过重置 1 天；
到期查询 dueAt ≤ today、按到期升序、单次 ≤20 张且 count 为到期总数。
"""

from datetime import date, timedelta
import os

import pytest

from backend.app.core import review_store, scheduler
from backend.app.models import ReviewItem
from backend.app.storage.json_store import write_json_atomic


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    path = str(tmp_path / "data")
    os.makedirs(path, exist_ok=True)
    monkeypatch.setattr(review_store, "DATA_DIR", path)
    return path


def make_item(rid, due_at, known=0, interval=1):
    return ReviewItem(
        id=rid,
        type="word",
        text=rid,
        materialId="m1",
        sentenceId="s1",
        contextText="ctx",
        knownCount=known,
        intervalDays=interval,
        dueAt=due_at,
    )


def seed(path, items):
    os.makedirs(path, exist_ok=True)
    write_json_atomic(
        str(os.path.join(path, "review-queue.json")),
        [item.model_dump(mode="json") for item in items],
    )


def test_new_item_due_tomorrow_via_review_store(data_dir):
    item, created = review_store.create("m1", "s1", "hello", "word", "Hello world.")
    assert created is True
    assert item.intervalDays == 1
    assert item.dueAt == date.today() + timedelta(days=1)


def test_rate_passed_moves_up_ladder(data_dir):
    seed(data_dir, [make_item("r1", date.today())])
    expected = [(1, 3), (3, 7), (7, 15), (15, 30), (30, 30)]
    for before, after in expected:
        item = review_store.list_items()[0]
        assert item.intervalDays == before
        result = scheduler.rate("r1", passed=True, today=date.today())
        assert result.intervalDays == after
        assert result.dueAt == date.today() + timedelta(days=after)
        assert result.knownCount == 1 + expected.index((before, after))
        assert result.reviewCount == 1 + expected.index((before, after))
        assert result.lastReviewAt is not None


def test_rate_failed_resets_to_one_day(data_dir):
    seed(data_dir, [make_item("r1", date.today(), known=2, interval=15)])
    result = scheduler.rate("r1", passed=False, today=date.today())
    assert result.intervalDays == 1
    assert result.dueAt == date.today() + timedelta(days=1)
    assert result.knownCount == 2  # 未通过不累加
    assert result.reviewCount == 1
    assert result.lastReviewAt is not None


def test_rate_unknown_item_raises_key_error(data_dir):
    with pytest.raises(KeyError):
        scheduler.rate("no-such", passed=True)


def test_due_items_filters_sorts_and_caps(data_dir):
    today = date.today()
    items = [
        make_item("future", today + timedelta(days=1)),
        make_item("due-later", today),
        make_item("due-earlier", today - timedelta(days=3)),
        make_item("due-mid", today - timedelta(days=1)),
    ]
    seed(data_dir, items)
    result = scheduler.due_items(limit=20, today=today)
    assert result["count"] == 3
    assert [i.id for i in result["items"]] == ["due-earlier", "due-mid", "due-later"]


def test_due_items_caps_at_limit_but_count_is_total(data_dir):
    today = date.today()
    seed(data_dir, [make_item(f"r{i:02d}", today) for i in range(25)])
    result = scheduler.due_items(limit=20, today=today)
    assert result["count"] == 25
    assert len(result["items"]) == 20
