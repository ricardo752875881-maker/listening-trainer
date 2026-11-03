"""T039: Review Queue 合约测试（contracts/api.md「全局复习队列 Review Queue」节）。

自行装配 FastAPI + review.router（main.py 接线由主控负责，本测试不依赖它）。
覆盖：GET due（≤20 张、count 总数、按到期升序）/ rate（升档、重置、404）/
GET items（materialId/type 筛选、familiarity 排序、400）/ DELETE。
"""

import os
from datetime import date, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api import review as review_api
from backend.app.core import review_store
from backend.app.models import ReviewItem
from backend.app.storage.json_store import write_json_atomic


def make_item(rid, material_id, rtype, due_at, known=0):
    return ReviewItem(
        id=rid,
        type=rtype,
        text=rid,
        materialId=material_id,
        sentenceId=f"s-{rid}",
        contextText=f"ctx {rid}",
        knownCount=known,
        intervalDays=1,
        dueAt=due_at,
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    os.makedirs(data_dir, exist_ok=True)
    monkeypatch.setattr(review_store, "DATA_DIR", data_dir)

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(review_api.router)
    return TestClient(app), data_dir


def seed(data_dir, items):
    os.makedirs(data_dir, exist_ok=True)
    write_json_atomic(
        os.path.join(data_dir, "review-queue.json"),
        [item.model_dump(mode="json") for item in items],
    )


def test_due_returns_count_and_sorted_capped_items(client):
    test_client, data_dir = client
    today = date.today()
    seed(
        data_dir,
        [
            make_item("today", "m1", "word", today),
            make_item("past3", "m1", "phrase", today - timedelta(days=3)),
            make_item("past1", "m2", "sentence", today - timedelta(days=1)),
            make_item("future", "m1", "word", today + timedelta(days=1)),
        ],
    )
    res = test_client.get("/api/review/due")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 3
    assert [i["id"] for i in body["items"]] == ["past3", "past1", "today"]
    assert all(i["dueAt"] <= today.isoformat() for i in body["items"])


def test_due_caps_at_20_but_count_is_total(client):
    test_client, data_dir = client
    today = date.today()
    seed(data_dir, [make_item(f"r{i:02d}", "m1", "word", today) for i in range(25)])
    body = test_client.get("/api/review/due").json()
    assert body["count"] == 25
    assert len(body["items"]) == 20


def test_rate_passed_upgrades_interval(client):
    test_client, _ = client
    item, _ = review_store.create("m1", "s1", "welcome", "word", "Hello and welcome.")
    assert item.intervalDays == 1

    res = test_client.post(f"/api/review/items/{item.id}/rate", json={"passed": True})
    assert res.status_code == 200
    body = res.json()
    assert body["intervalDays"] == 3
    assert body["dueAt"] == (date.today() + timedelta(days=3)).isoformat()
    assert body["knownCount"] == 1
    assert body["reviewCount"] == 1
    assert body["lastReviewAt"] is not None

    assert review_store.find("m1", "s1", "welcome", "word").intervalDays == 3


def test_rate_failed_resets_interval(client):
    test_client, data_dir = client
    today = date.today()
    item = make_item("r1", "m1", "word", today, known=2)
    item.intervalDays = 15
    seed(data_dir, [item])

    res = test_client.post(f"/api/review/items/r1/rate", json={"passed": False})
    assert res.status_code == 200
    body = res.json()
    assert body["intervalDays"] == 1
    assert body["dueAt"] == (today + timedelta(days=1)).isoformat()
    assert body["knownCount"] == 2
    assert body["reviewCount"] == 1


def test_rate_unknown_item_404(client):
    test_client, _ = client
    res = test_client.post("/api/review/items/no-such/rate", json={"passed": True})
    assert res.status_code == 404


def test_list_items_filters_by_material_and_type(client):
    test_client, data_dir = client
    today = date.today()
    seed(
        data_dir,
        [
            make_item("a1", "m1", "word", today),
            make_item("a2", "m1", "phrase", today),
            make_item("b1", "m2", "word", today),
            make_item("b2", "m2", "sentence", today),
        ],
    )
    res = test_client.get("/api/review/items", params={"materialId": "m1"})
    assert [i["id"] for i in res.json()] == ["a1", "a2"]

    res = test_client.get("/api/review/items", params={"type": "word"})
    assert [i["id"] for i in res.json()] == ["a1", "b1"]

    res = test_client.get(
        "/api/review/items", params={"materialId": "m2", "type": "sentence"}
    )
    assert [i["id"] for i in res.json()] == ["b2"]

    res = test_client.get("/api/review/items")
    assert len(res.json()) == 4


def test_list_items_invalid_type_400(client):
    test_client, data_dir = client
    seed(data_dir, [make_item("a1", "m1", "word", date.today())])
    res = test_client.get("/api/review/items", params={"type": "bogus"})
    assert res.status_code == 400


def test_list_items_familiarity_sort(client):
    test_client, data_dir = client
    today = date.today()
    seed(
        data_dir,
        [
            make_item("known2", "m1", "word", today, known=2),
            make_item("known0-due-later", "m1", "word", today + timedelta(days=5), known=0),
            make_item("known0-due-earlier", "m1", "word", today, known=0),
            make_item("known1", "m1", "word", today, known=1),
        ],
    )
    res = test_client.get("/api/review/items", params={"sort": "familiarity"})
    assert [i["id"] for i in res.json()] == [
        "known0-due-earlier",
        "known0-due-later",
        "known1",
        "known2",
    ]


def test_delete_item(client):
    test_client, data_dir = client
    seed(data_dir, [make_item("a1", "m1", "word", date.today())])

    res = test_client.delete("/api/review/items/a1")
    assert res.status_code == 200
    assert res.json() == {"deleted": True}
    assert review_store.list_items() == []

    assert test_client.delete("/api/review/items/a1").status_code == 404
