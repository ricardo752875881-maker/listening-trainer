"""T022 后端部分: Markings 合约测试（contracts/api.md「学习标记 Markings」节）。

自行装配 FastAPI + markings.router（main.py 接线由主控负责，本测试不依赖它）。
错误约定：400 校验失败 / 404 不存在 / 409 重复标记。
"""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api import markings
from backend.app.core import material_store, review_store
from backend.app.models import Block, Material, Sentence, Turn


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    monkeypatch.setattr(material_store, "DATA_DIR", data_dir)
    monkeypatch.setattr(review_store, "DATA_DIR", data_dir)

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(markings.router)

    material = Material(title="Test Material", audioFileName="audio.mp3", durationSec=60.0)
    turn = Turn(materialId=material.id, index=0, speakerName="Neil", speakerNameZh="尼尔")
    block = Block(turnId=turn.id, index=0, translationLines=[])
    sentence = Sentence(
        materialId=material.id,
        turnId=turn.id,
        blockId=block.id,
        index=0,
        text="Hello and welcome to the programme.",
        aligned=True,
        startSec=0.0,
        endSec=2.5,
    )
    sentence2 = Sentence(
        materialId=material.id,
        turnId=turn.id,
        blockId=block.id,
        index=1,
        text="Second sentence here.",
        aligned=False,
    )
    material_store.save(material, [turn], [block], [sentence, sentence2])

    return TestClient(app), material, sentence, sentence2


def test_post_vocab_creates_review_item(client):
    test_client, material, sentence, _ = client
    res = test_client.post(
        f"/api/materials/{material.id}/sentences/{sentence.id}/vocab",
        json={"text": "welcome", "wordStart": 2, "wordEnd": 2, "type": "word", "meaning": "欢迎"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["text"] == "welcome"
    assert body["type"] == "word"
    assert body["meaning"] == "欢迎"
    assert body["materialId"] == material.id
    assert body["sentenceId"] == sentence.id
    assert body["contextText"] == "Hello and welcome to the programme."
    assert body["intervalDays"] == 1
    assert body["dueAt"] == (date.today() + timedelta(days=1)).isoformat()

    items = review_store.list_items()
    assert len(items) == 1
    assert items[0].knownCount == 0
    assert items[0].reviewCount == 0


def test_post_vocab_duplicate_returns_409(client):
    test_client, material, sentence, _ = client
    url = f"/api/materials/{material.id}/sentences/{sentence.id}/vocab"
    payload = {"text": "welcome", "wordStart": 2, "wordEnd": 2, "type": "word"}
    assert test_client.post(url, json=payload).status_code == 201
    res = test_client.post(url, json=payload)
    assert res.status_code == 409
    assert len(review_store.list_items()) == 1


def test_post_vocab_phrase_type(client):
    test_client, material, sentence, _ = client
    res = test_client.post(
        f"/api/materials/{material.id}/sentences/{sentence.id}/vocab",
        json={"text": "welcome to", "wordStart": 2, "wordEnd": 3, "type": "phrase"},
    )
    assert res.status_code == 201
    assert res.json()["type"] == "phrase"
    assert res.json()["meaning"] is None


def test_post_vocab_validation_error_400(client):
    test_client, material, sentence, _ = client
    res = test_client.post(
        f"/api/materials/{material.id}/sentences/{sentence.id}/vocab",
        json={"text": "welcome", "wordStart": 2, "wordEnd": 2, "type": "invalid-type"},
    )
    assert res.status_code == 400


def test_post_vocab_unknown_material_or_sentence_404(client):
    test_client, material, sentence, _ = client
    payload = {"text": "x", "wordStart": 0, "wordEnd": 0, "type": "word"}
    res = test_client.post(
        f"/api/materials/no-such-material/sentences/{sentence.id}/vocab", json=payload
    )
    assert res.status_code == 404
    res = test_client.post(
        f"/api/materials/{material.id}/sentences/no-such-sentence/vocab", json=payload
    )
    assert res.status_code == 404


def test_delete_vocab_removes_review_item(client):
    test_client, material, sentence, _ = client
    url = f"/api/materials/{material.id}/sentences/{sentence.id}/vocab"
    test_client.post(
        url, json={"text": "welcome", "wordStart": 2, "wordEnd": 2, "type": "word"}
    )
    res = test_client.request(
        "DELETE", url, json={"text": "welcome", "type": "word"}
    )
    assert res.status_code == 200
    assert review_store.list_items() == []

    res = test_client.request("DELETE", url, json={"text": "welcome", "type": "word"})
    assert res.status_code == 404


def test_put_not_understood_marks_and_creates_sentence_item(client):
    test_client, material, sentence, _ = client
    url = f"/api/materials/{material.id}/sentences/{sentence.id}/not-understood"
    res = test_client.put(url, json={"marked": True})
    assert res.status_code == 200
    assert res.json()["notUnderstood"] is True

    loaded = material_store.load(material.id)
    sentences = loaded[3]
    target = next(s for s in sentences if s.id == sentence.id)
    assert target.notUnderstood is True

    items = review_store.list_items()
    assert len(items) == 1
    assert items[0].type == "sentence"
    assert items[0].text == "Hello and welcome to the programme."
    assert items[0].contextText == "Hello and welcome to the programme."
    assert items[0].intervalDays == 1


def test_put_not_understood_idempotent_no_duplicate(client):
    test_client, material, sentence, _ = client
    url = f"/api/materials/{material.id}/sentences/{sentence.id}/not-understood"
    test_client.put(url, json={"marked": True})
    test_client.put(url, json={"marked": True})
    assert len(review_store.list_items()) == 1


def test_put_not_understood_unmark_removes_item_and_flag(client):
    test_client, material, sentence, _ = client
    url = f"/api/materials/{material.id}/sentences/{sentence.id}/not-understood"
    test_client.put(url, json={"marked": True})
    res = test_client.put(url, json={"marked": False})
    assert res.status_code == 200
    assert res.json()["notUnderstood"] is False

    loaded = material_store.load(material.id)
    target = next(s for s in loaded[3] if s.id == sentence.id)
    assert target.notUnderstood is False
    assert review_store.list_items() == []


def test_put_not_understood_unknown_sentence_404(client):
    test_client, material, _, _ = client
    res = test_client.put(
        f"/api/materials/{material.id}/sentences/no-such/not-understood", json={"marked": True}
    )
    assert res.status_code == 404


def test_material_delete_cascades_review_items(client):
    test_client, material, sentence, _ = client
    url = f"/api/materials/{material.id}/sentences/{sentence.id}/vocab"
    test_client.post(url, json={"text": "welcome", "wordStart": 2, "wordEnd": 2, "type": "word"})
    assert len(review_store.list_items()) == 1
    assert material_store.delete(material.id) is True
    assert review_store.list_items() == []
    assert material_store.load(material.id) is None


def test_material_stats_counts_vocab_and_not_understood(client):
    test_client, material, sentence, sentence2 = client
    vocab_url = f"/api/materials/{material.id}/sentences/{sentence.id}/vocab"
    test_client.post(vocab_url, json={"text": "welcome", "wordStart": 2, "wordEnd": 2, "type": "word"})
    test_client.post(vocab_url, json={"text": "welcome to", "wordStart": 2, "wordEnd": 3, "type": "phrase"})
    nu_url = f"/api/materials/{material.id}/sentences/{sentence2.id}/not-understood"
    test_client.put(nu_url, json={"marked": True})

    cards = material_store.list_materials()
    assert len(cards) == 1
    card = cards[0]
    assert card["id"] == material.id
    assert card["title"] == "Test Material"
    assert card["stats"] == {"vocab": 2, "notUnderstood": 1}
