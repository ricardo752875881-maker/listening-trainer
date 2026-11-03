"""T013/T019 合约测试：材料接口（contracts/api.md「材料 Materials」节）。

自行装配 FastAPI + materials router（复刻 main.py 的 400 handler）：
CRUD + PATCH 校验 400 + DELETE 级联（目录/复习条目/跟读/测验）+ audio Range 206
+ retry-transcribe（成功补齐 / 非 audioOnly 409 / 失败 502）。
"""

import json
import os

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api import materials as materials_api
from backend.app.core import material_store, review_store
from backend.app.core.forced_aligner import TranscribeError
from backend.app.models import Block, Material, Sentence, Turn

FAKE_WORDS = [
    {"w": "Hello", "start": 0.0, "end": 0.5},
    {"w": "world.", "start": 0.5, "end": 1.0},
]


def fake_align(audio_path, text, model_size="base", should_cancel=None, on_progress=None):
    """假强制对齐：返回固定词序列（与转写时代 Provider 假实现等价）。"""
    return {"words": [dict(w) for w in FAKE_WORDS], "durationSec": 2.0}


def failing_align(audio_path, text, model_size="base", should_cancel=None, on_progress=None):
    raise TranscribeError("模拟对齐失败")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    monkeypatch.setattr(material_store, "DATA_DIR", data_dir)
    monkeypatch.setattr(review_store, "DATA_DIR", data_dir)
    monkeypatch.setattr(materials_api.forced_aligner, "align", fake_align)

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(materials_api.router)

    material = Material(title="测试材料", audioFileName="audio.mp3", durationSec=60.0)
    turn = Turn(materialId=material.id, index=0, speakerName="Neil", speakerNameZh="尼尔")
    block = Block(turnId=turn.id, index=0, translationLines=["你好，世界。"])
    sentence = Sentence(
        materialId=material.id,
        turnId=turn.id,
        blockId=block.id,
        index=0,
        text="Hello world.",
        aligned=True,
        startSec=0.0,
        endSec=1.0,
        words=[{"w": "Hello", "start": 0.0, "end": 0.5}, {"w": "world.", "start": 0.5, "end": 1.0}],
    )
    material_store.save(material, [turn], [block], [sentence])
    # 假音频字节：本组用例只做文件服务（Range），不解码内容
    audio_dir = os.path.join(data_dir, "materials", material.id)
    with open(os.path.join(audio_dir, "audio.mp3"), "wb") as f:
        f.write(os.urandom(4096))

    with TestClient(app) as test_client:
        yield test_client, material, turn, block, sentence


# ---------- GET /api/materials ----------

def test_list_returns_cards_with_derived_stats(client):
    test_client, material, _turn, _block, sentence = client
    review_store.create(material.id, sentence.id, "Hello", "word", sentence.text)
    review_store.create(material.id, sentence.id, "Hello world", "phrase", sentence.text)
    review_store.create(material.id, sentence.id, "长句", "sentence", sentence.text)

    res = test_client.get("/api/materials")
    assert res.status_code == 200
    cards = res.json()
    assert len(cards) == 1
    card = cards[0]
    assert card["id"] == material.id
    assert card["title"] == "测试材料"
    assert card["durationSec"] == 60.0
    assert card["stage"] == "learning"
    assert card["bestScore"] is None
    assert card["createdAt"]
    # 派生统计：vocab = word/phrase 条目数；notUnderstood = 标记句数
    assert card["stats"] == {"vocab": 2, "notUnderstood": 0}


def test_get_detail_returns_full_learning_data(client):
    test_client, material, turn, block, sentence = client
    res = test_client.get(f"/api/materials/{material.id}")
    assert res.status_code == 200
    body = res.json()

    assert body["material"]["id"] == material.id
    assert body["material"]["title"] == "测试材料"
    assert body["turns"][0]["speakerName"] == "Neil"
    assert body["turns"][0]["speakerNameZh"] == "尼尔"
    assert body["blocks"][0]["translationLines"] == ["你好，世界。"]
    sent = body["sentences"][0]
    assert sent["text"] == "Hello world."
    assert sent["notUnderstood"] is False
    assert sent["words"][0] == {"w": "Hello", "start": 0.0, "end": 0.5}
    assert body["shadowingItems"] == []


def test_get_detail_unknown_material_404(client):
    test_client, *_ = client
    assert test_client.get("/api/materials/no-such-material").status_code == 404


# ---------- PATCH /api/materials/{id} ----------

def test_patch_title_stage_playhead(client):
    test_client, material, *_ = client
    res = test_client.patch(
        f"/api/materials/{material.id}",
        json={"title": "改名了", "stage": "reviewing", "playheadSec": 12.5},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "改名了"
    assert body["stage"] == "reviewing"
    assert body["playheadSec"] == 12.5

    saved = material_store.load(material.id)[0]
    assert saved.title == "改名了"
    assert saved.stage == "reviewing"
    assert saved.playheadSec == 12.5


def test_patch_partial_fields_only_updates_given(client):
    test_client, material, *_ = client
    res = test_client.patch(f"/api/materials/{material.id}", json={"playheadSec": 3.0})
    assert res.status_code == 200
    saved = material_store.load(material.id)[0]
    assert saved.title == "测试材料"  # 未提供字段不变
    assert saved.playheadSec == 3.0


@pytest.mark.parametrize(
    "payload",
    [
        {"stage": "bogus"},
        {"title": ""},
        {"title": "   "},
        {"playheadSec": -1},
        {"playheadSec": "abc"},
    ],
)
def test_patch_invalid_body_400(client, payload):
    test_client, material, *_ = client
    res = test_client.patch(f"/api/materials/{material.id}", json=payload)
    assert res.status_code == 400, payload


def test_patch_unknown_material_404(client):
    test_client, *_ = client
    res = test_client.patch("/api/materials/no-such-material", json={"title": "x"})
    assert res.status_code == 404


# ---------- DELETE /api/materials/{id} ----------

def test_delete_cascades_directory_review_shadowing_quizzes(client):
    test_client, material, _turn, _block, sentence = client
    review_store.create(material.id, sentence.id, "Hello", "word", sentence.text)
    review_store.create(material.id, sentence.id, sentence.text, "sentence", sentence.text)
    material_dir = os.path.join(material_store.DATA_DIR, "materials", material.id)
    with open(os.path.join(material_dir, "shadowing.json"), "w", encoding="utf-8") as f:
        json.dump([{"id": "sh1", "status": "active"}], f)
    with open(os.path.join(material_dir, "quizzes.json"), "w", encoding="utf-8") as f:
        json.dump([{"id": "q1", "status": "in_progress"}], f)

    res = test_client.delete(f"/api/materials/{material.id}")
    assert res.status_code == 200

    assert test_client.get(f"/api/materials/{material.id}").status_code == 404
    assert test_client.get("/api/materials").json() == []
    assert review_store.list_items() == []
    assert not os.path.exists(material_dir)  # 音频/跟读/测验随目录清除


def test_delete_unknown_material_404(client):
    test_client, *_ = client
    assert test_client.delete("/api/materials/no-such-material").status_code == 404


# ---------- GET /api/materials/{id}/audio ----------

def test_audio_stream_supports_range_206(client):
    test_client, material, *_ = client
    res = test_client.get(f"/api/materials/{material.id}/audio", headers={"Range": "bytes=0-99"})
    assert res.status_code == 206
    assert res.headers["accept-ranges"] == "bytes"
    assert res.headers["content-range"].startswith("bytes 0-99/")
    assert len(res.content) == 100


def test_audio_stream_full_get_200(client):
    test_client, material, *_ = client
    res = test_client.get(f"/api/materials/{material.id}/audio")
    assert res.status_code == 200
    assert len(res.content) == 4096


def test_audio_unknown_material_404(client):
    test_client, *_ = client
    assert test_client.get("/api/materials/no-such-material/audio").status_code == 404


# ---------- POST /api/materials/{id}/retry-transcribe ----------

def test_retry_transcribe_success_completes_material(client):
    test_client, *_ = client
    audio_only = Material(
        title="仅音频材料", audioFileName="audio.mp3", durationSec=30.0, audioOnly=True
    )
    material_store.save(audio_only, [], [], [])
    audio_dir = os.path.join(material_store.DATA_DIR, "materials", audio_only.id)
    with open(os.path.join(audio_dir, "audio.mp3"), "wb") as f:
        f.write(os.urandom(1024))

    res = test_client.post(
        f"/api/materials/{audio_only.id}/retry-transcribe", json={"transcript": "Hello world."}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["material"]["audioOnly"] is False
    assert body["material"]["engineUsed"] == "wav2vec2"
    assert len(body["sentences"]) == 1
    assert body["sentences"][0]["aligned"] is True
    assert body["sentences"][0]["words"][0]["w"] == "Hello"

    saved = material_store.load(audio_only.id)[0]
    assert saved.audioOnly is False  # 持久化补齐


def test_retry_transcribe_rejects_non_audio_only(client):
    test_client, material, *_ = client
    res = test_client.post(
        f"/api/materials/{material.id}/retry-transcribe", json={"transcript": "Hello world."}
    )
    assert res.status_code == 409


def test_retry_transcribe_failure_returns_502_and_stays_audio_only(client, monkeypatch):
    test_client, *_ = client
    audio_only = Material(
        title="仅音频材料", audioFileName="audio.mp3", durationSec=30.0, audioOnly=True
    )
    material_store.save(audio_only, [], [], [])
    audio_dir = os.path.join(material_store.DATA_DIR, "materials", audio_only.id)
    with open(os.path.join(audio_dir, "audio.mp3"), "wb") as f:
        f.write(os.urandom(1024))

    monkeypatch.setattr(materials_api.forced_aligner, "align", failing_align)
    res = test_client.post(
        f"/api/materials/{audio_only.id}/retry-transcribe", json={"transcript": "Hello world."}
    )
    assert res.status_code == 502
    assert "对齐失败" in res.json()["detail"]

    saved = material_store.load(audio_only.id)[0]
    assert saved.audioOnly is True  # 失败保持仅音频模式


def test_retry_transcribe_unknown_material_404(client):
    test_client, *_ = client
    res = test_client.post(
        "/api/materials/no-such-material/retry-transcribe", json={"transcript": "Hello world."}
    )
    assert res.status_code == 404
