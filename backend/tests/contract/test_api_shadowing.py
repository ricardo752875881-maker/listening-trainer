"""T031 后端部分: Shadowing 合约测试（contracts/api.md「跟读 Shadowing」节）。

自行装配 FastAPI + shadowing.router / settings_extra.router（main.py 接线由主控负责）。
错误约定：400 校验失败/未配置大模型；404 不存在；409 范围含未对齐句/重复范围；
502 大模型调用失败。
"""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api import settings as settings_api
from backend.app.api import settings_extra, shadowing
from backend.app.core import material_store
from backend.app.llm import recommend as llm_recommend
from backend.app.models import Block, LlmSettings, Material, Sentence, Settings, Turn, Word
from backend.app.storage.json_store import write_json_atomic


def _words(text: str, start: float, step: float = 0.4) -> list[Word]:
    return [
        Word(w=w, start=start + i * step, end=start + i * step + step * 0.8)
        for i, w in enumerate(text.split())
    ]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    monkeypatch.setattr(material_store, "DATA_DIR", data_dir)
    settings_path = str(tmp_path / "data" / "settings.json")
    monkeypatch.setattr(settings_api, "SETTINGS_PATH", settings_path)

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(shadowing.router)
    app.include_router(settings_extra.router)

    material = Material(title="Shadow Material", audioFileName="audio.mp3", durationSec=30.0)
    turn = Turn(materialId=material.id, index=0, speakerName="Neil")
    block = Block(turnId=turn.id, index=0, translationLines=[])
    s0 = Sentence(
        materialId=material.id,
        turnId=turn.id,
        blockId=block.id,
        index=0,
        text="Hello and welcome to the programme.",
        aligned=True,
        startSec=0.0,
        endSec=2.5,
        words=_words("Hello and welcome to the programme", 0.0),
    )
    s1 = Sentence(
        materialId=material.id,
        turnId=turn.id,
        blockId=block.id,
        index=1,
        text="Today we discuss the economy.",
        aligned=True,
        startSec=5.0,
        endSec=7.5,
        words=_words("Today we discuss the economy", 5.0),
    )
    s2 = Sentence(
        materialId=material.id,
        turnId=turn.id,
        blockId=block.id,
        index=2,
        text="Second sentence here.",
        aligned=False,
    )
    material_store.save(material, [turn], [block], [s0, s1, s2])

    return TestClient(app), settings_path, material, s0, s1, s2


def _write_settings(settings_path: str, llm: LlmSettings) -> None:
    write_json_atomic(settings_path, Settings(llm=llm).model_dump())


def _fake_llm_client(payload, raise_exc=None):
    def create(**_kwargs):
        if raise_exc is not None:
            raise raise_exc
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_create_and_list(client):
    test_client, _, material, s0, _, _ = client
    url = f"/api/materials/{material.id}/shadowing"
    res = test_client.post(
        url,
        json={
            "text": "welcome to",
            "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
            "anchorEnd": {"sentenceId": s0.id, "wordIndex": 3},
            "source": "manual",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["text"] == "welcome to"
    assert body["source"] == "manual"
    assert body["status"] == "active"
    assert body["anchorStart"] == {"sentenceId": s0.id, "wordIndex": 2}
    assert body["audioStartSec"] == pytest.approx(0.8)
    assert body["audioEndSec"] == pytest.approx(0.4 * 3 + 0.4 * 0.8)

    res = test_client.get(url)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    assert items[0]["id"] == body["id"]


def test_create_unaligned_in_range_returns_409(client):
    test_client, _, material, s0, _, s2 = client
    res = test_client.post(
        f"/api/materials/{material.id}/shadowing",
        json={
            "text": "welcome to Second",
            "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
            "anchorEnd": {"sentenceId": s2.id, "wordIndex": 0},
            "source": "manual",
        },
    )
    assert res.status_code == 409
    assert "未对齐" in res.json()["detail"]


def test_create_duplicate_range_returns_409(client):
    test_client, _, material, s0, _, _ = client
    url = f"/api/materials/{material.id}/shadowing"
    payload = {
        "text": "welcome to",
        "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
        "anchorEnd": {"sentenceId": s0.id, "wordIndex": 3},
        "source": "manual",
    }
    assert test_client.post(url, json=payload).status_code == 201
    res = test_client.post(url, json=payload)
    assert res.status_code == 409
    res = test_client.get(url)
    assert len(res.json()) == 1


def test_create_partial_overlap_allowed(client):
    test_client, _, material, s0, _, _ = client
    url = f"/api/materials/{material.id}/shadowing"
    first = {
        "text": "welcome to",
        "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
        "anchorEnd": {"sentenceId": s0.id, "wordIndex": 3},
        "source": "manual",
    }
    overlap = {
        "text": "and welcome to the",
        "anchorStart": {"sentenceId": s0.id, "wordIndex": 1},
        "anchorEnd": {"sentenceId": s0.id, "wordIndex": 4},
        "source": "manual",
    }
    assert test_client.post(url, json=first).status_code == 201
    assert test_client.post(url, json=overlap).status_code == 201
    assert len(test_client.get(url).json()) == 2


def test_create_unknown_sentence_returns_404(client):
    test_client, _, material, s0, _, _ = client
    res = test_client.post(
        f"/api/materials/{material.id}/shadowing",
        json={
            "text": "x",
            "anchorStart": {"sentenceId": "no-such", "wordIndex": 0},
            "anchorEnd": {"sentenceId": s0.id, "wordIndex": 0},
            "source": "manual",
        },
    )
    assert res.status_code == 404


def test_create_word_index_out_of_range_returns_400(client):
    test_client, _, material, s0, _, _ = client
    res = test_client.post(
        f"/api/materials/{material.id}/shadowing",
        json={
            "text": "x",
            "anchorStart": {"sentenceId": s0.id, "wordIndex": 99},
            "anchorEnd": {"sentenceId": s0.id, "wordIndex": 99},
            "source": "manual",
        },
    )
    assert res.status_code == 400


def test_cross_sentence_range_derives_audio_times(client):
    test_client, _, material, s0, s1, _ = client
    res = test_client.post(
        f"/api/materials/{material.id}/shadowing",
        json={
            "text": "to the programme. Today we",
            "anchorStart": {"sentenceId": s0.id, "wordIndex": 3},
            "anchorEnd": {"sentenceId": s1.id, "wordIndex": 1},
            "source": "manual",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["audioStartSec"] == pytest.approx(0.4 * 3)
    assert body["audioEndSec"] == pytest.approx(5.0 + 0.4 * 1 + 0.4 * 0.8)


def test_delete_shadowing(client):
    test_client, _, material, s0, _, _ = client
    url = f"/api/materials/{material.id}/shadowing"
    created = test_client.post(
        url,
        json={
            "text": "welcome to",
            "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
            "anchorEnd": {"sentenceId": s0.id, "wordIndex": 3},
            "source": "manual",
        },
    ).json()

    res = test_client.request("DELETE", f"{url}/{created['id']}")
    assert res.status_code == 200
    assert test_client.get(url).json() == []

    res = test_client.request("DELETE", f"{url}/{created['id']}")
    assert res.status_code == 404


def test_ignore_marks_status_and_hides_from_recommend(client, monkeypatch):
    test_client, settings_path, material, s0, _, _ = client
    url = f"/api/materials/{material.id}/shadowing"
    created = test_client.post(
        url,
        json={
            "text": "welcome to",
            "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
            "anchorEnd": {"sentenceId": s0.id, "wordIndex": 3},
            "source": "manual",
        },
    ).json()

    res = test_client.post(f"{url}/{created['id']}/ignore")
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    items = test_client.get(url).json()
    assert [i["status"] for i in items] == ["ignored"]

    # ignored 范围不再出现于推荐候选
    _write_settings(
        settings_path,
        LlmSettings(provider="openai", apiKey="sk-test", model="gpt-4o-mini", enabled=True),
    )
    monkeypatch.setattr(
        llm_recommend,
        "_create_client",
        lambda _s: _fake_llm_client([{"text": "welcome to"}]),
    )
    res = test_client.post(f"{url}/recommend")
    assert res.status_code == 200
    assert res.json() == {"candidates": []}


def test_ignore_unknown_returns_404(client):
    test_client, _, material, _, _, _ = client
    res = test_client.post(f"/api/materials/{material.id}/shadowing/no-such/ignore")
    assert res.status_code == 404


def test_recommend_not_configured_returns_400(client):
    test_client, settings_path, material, _, _, _ = client
    _write_settings(settings_path, LlmSettings())  # 默认未启用
    res = test_client.post(f"/api/materials/{material.id}/shadowing/recommend")
    assert res.status_code == 400
    assert res.json()["detail"] == "未配置大模型"


def test_recommend_llm_failure_returns_502(client, monkeypatch):
    test_client, settings_path, material, _, _, _ = client
    _write_settings(
        settings_path,
        LlmSettings(provider="deepseek", apiKey="sk-test", model="deepseek-chat", enabled=True),
    )
    monkeypatch.setattr(
        llm_recommend,
        "_create_client",
        lambda _s: _fake_llm_client([], raise_exc=RuntimeError("boom")),
    )
    res = test_client.post(f"/api/materials/{material.id}/shadowing/recommend")
    assert res.status_code == 502
    assert "boom" in res.json()["detail"]


def test_recommend_success_maps_anchors_and_skips_unlocatable(client, monkeypatch):
    test_client, settings_path, material, s0, s1, s2 = client
    _write_settings(
        settings_path,
        LlmSettings(provider="kimi", apiKey="sk-test", model="kimi-k2", enabled=True),
    )
    payload = [
        {"text": "welcome to the programme"},  # 单句内命中
        {"text": "the programme Today we discuss"},  # 跨句命中（相邻已对齐句拼接）
        {"text": "Second sentence"},  # 未对齐句内容 → 跳过
        {"text": "completely unrelated text"},  # 定位失败 → 跳过
    ]
    monkeypatch.setattr(
        llm_recommend, "_create_client", lambda _s: _fake_llm_client(payload)
    )
    res = test_client.post(f"/api/materials/{material.id}/shadowing/recommend")
    assert res.status_code == 200
    candidates = res.json()["candidates"]
    assert len(candidates) == 2
    assert candidates[0] == {
        "text": "welcome to the programme",
        "reason": "",
        "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
        "anchorEnd": {"sentenceId": s0.id, "wordIndex": 5},
    }
    assert candidates[1] == {
        "text": "the programme Today we discuss",
        "reason": "",
        "anchorStart": {"sentenceId": s0.id, "wordIndex": 4},
        "anchorEnd": {"sentenceId": s1.id, "wordIndex": 2},
    }
    anchor_sentences = {
        c["anchorStart"]["sentenceId"] for c in candidates
    } | {c["anchorEnd"]["sentenceId"] for c in candidates}
    assert s2.id not in anchor_sentences  # 未对齐句不会进入候选锚点


def test_recommend_filters_existing_active_range(client, monkeypatch):
    test_client, settings_path, material, s0, _, _ = client
    url = f"/api/materials/{material.id}/shadowing"
    test_client.post(
        url,
        json={
            "text": "welcome to",
            "anchorStart": {"sentenceId": s0.id, "wordIndex": 2},
            "anchorEnd": {"sentenceId": s0.id, "wordIndex": 3},
            "source": "manual",
        },
    )
    _write_settings(
        settings_path,
        LlmSettings(provider="openai", apiKey="sk-test", model="gpt-4o-mini", enabled=True),
    )
    monkeypatch.setattr(
        llm_recommend,
        "_create_client",
        lambda _s: _fake_llm_client([{"text": "welcome to"}]),
    )
    res = test_client.post(f"{url}/recommend")
    assert res.status_code == 200
    assert res.json()["candidates"] == []


# ---------- settings_extra 端点（无网络，隔离存储） ----------


def test_test_llm_without_key_returns_not_ok(client):
    test_client, settings_path, *_ = client
    _write_settings(settings_path, LlmSettings())
    res = test_client.post("/api/settings/test-llm")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "API Key" in body["message"]


# ---------- 2026-11-02 推荐三标准 + reason 标注 ----------


def test_recommend_passes_reason_tags(client, monkeypatch):
    """LLM 候选的 reason（三条标准命中编号）随候选透传给前端展示。"""
    test_client, settings_path, material, s0, _, _ = client
    url = f"/api/materials/{material.id}/shadowing"
    _write_settings(
        settings_path,
        LlmSettings(provider="openai", apiKey="sk-test", model="gpt-4o-mini", enabled=True),
    )
    monkeypatch.setattr(
        llm_recommend,
        "_create_client",
        lambda _s: _fake_llm_client([{"text": "welcome to", "reason": "1,2"}]),
    )
    res = test_client.post(f"{url}/recommend")
    assert res.status_code == 200
    candidates = res.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["reason"] == "1,2"
