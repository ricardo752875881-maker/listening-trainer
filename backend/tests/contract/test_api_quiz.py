"""T026: Quiz 合约测试（contracts/api.md「测验 Quiz」节）。

自行装配 FastAPI + quiz.router（main.py 接线由主控负责，本测试不依赖它）。
覆盖：generate 草稿持久化 / 409（仅音频、未完成草稿）/ GET 恢复 /
submit 归一化判分、≥90 流转 mastered、bestScore 取最大、<90 不降级。
"""

import json
import os

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api import quiz as quiz_api
from backend.app.api import settings as settings_api
from backend.app.core import material_store, review_store
from backend.app.models import Block, LlmSettings, Material, Sentence, Settings, Turn

S1_TEXT = "Hello and welcome to the programme."
S2_TEXT = "What do you make of it?"
S3_TEXT = "A third sentence appears."


def _save_material(material, sentences, turn, block):
    material_store.save(material, [turn], [block], sentences)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    monkeypatch.setattr(material_store, "DATA_DIR", data_dir)
    monkeypatch.setattr(review_store, "DATA_DIR", data_dir)
    # 隔离真实设置（含用户已配置的大模型 Key），防止测验出题意外调用真实 LLM
    monkeypatch.setattr(settings_api, "DATA_DIR", data_dir)
    monkeypatch.setattr(settings_api, "SETTINGS_PATH", os.path.join(data_dir, "settings.json"))

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(quiz_api.router)

    material = Material(title="Quiz Material", audioFileName="audio.mp3", durationSec=60.0)
    turn = Turn(materialId=material.id, index=0)
    block = Block(turnId=turn.id, index=0, translationLines=[])
    s1 = Sentence(
        materialId=material.id, turnId=turn.id, blockId=block.id, index=0,
        text=S1_TEXT, aligned=True, startSec=0.0, endSec=2.0,
    )
    s2 = Sentence(
        materialId=material.id, turnId=turn.id, blockId=block.id, index=1,
        text=S2_TEXT, aligned=True, notUnderstood=True, startSec=2.0, endSec=4.0,
    )
    s3 = Sentence(
        materialId=material.id, turnId=turn.id, blockId=block.id, index=2,
        text=S3_TEXT, aligned=True, startSec=4.0, endSec=6.0,
    )
    s4 = Sentence(
        materialId=material.id, turnId=turn.id, blockId=block.id, index=3,
        text="Unaligned sentence.", aligned=False,
    )
    _save_material(material, [s1, s2, s3, s4], turn, block)

    audio_only = Material(
        title="Audio Only", audioFileName="audio.mp3", durationSec=30.0, audioOnly=True
    )
    ao_turn = Turn(materialId=audio_only.id, index=0)
    ao_block = Block(turnId=ao_turn.id, index=0, translationLines=[])
    _save_material(audio_only, [], ao_turn, ao_block)

    # s1 含生词标记 → 抽题优先级：s2（没听懂）> s1（生词）> s3（随机）
    review_store.create(material.id, s1.id, "welcome", "word", S1_TEXT)

    return TestClient(app), material, audio_only, {"s1": s1, "s2": s2, "s3": s3, "s4": s4}


def _quizzes_on_disk(material_id):
    path = os.path.join(material_store.DATA_DIR, "materials", material_id, "quizzes.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_generate_creates_in_progress_draft(client):
    test_client, material, _, sids = client
    res = test_client.post(f"/api/materials/{material.id}/quiz/generate", json={"count": 10})
    assert res.status_code == 201
    body = res.json()
    assert body["quizId"]
    # 池仅含对齐句；优先级：没听懂 > 含生词 > 其余
    assert [i["sentenceId"] for i in body["items"]] == [sids["s2"].id, sids["s1"].id, sids["s3"].id]
    assert sids["s4"].id not in [i["sentenceId"] for i in body["items"]]

    stored = _quizzes_on_disk(material.id)
    assert len(stored) == 1
    assert stored[0]["id"] == body["quizId"]
    assert stored[0]["status"] == "in_progress"
    assert all(item["userInput"] is None for item in stored[0]["items"])
    assert stored[0]["items"][0]["correct"] is None


def test_generate_existing_draft_returns_409_with_quiz_id(client):
    test_client, material, _, _ = client
    first = test_client.post(f"/api/materials/{material.id}/quiz/generate", json={"count": 10})
    assert first.status_code == 201
    res = test_client.post(f"/api/materials/{material.id}/quiz/generate", json={"count": 5})
    assert res.status_code == 409
    assert res.json()["detail"]["quizId"] == first.json()["quizId"]


def test_generate_audio_only_material_409(client):
    test_client, _, audio_only, _ = client
    res = test_client.post(f"/api/materials/{audio_only.id}/quiz/generate", json={"count": 10})
    assert res.status_code == 409


def test_generate_unknown_material_404(client):
    test_client, _, _, _ = client
    res = test_client.post("/api/materials/no-such/quiz/generate", json={"count": 10})
    assert res.status_code == 404


def test_get_quiz_restores_draft_with_answers(client):
    test_client, material, _, sids = client
    quiz_id = test_client.post(
        f"/api/materials/{material.id}/quiz/generate", json={"count": 10}
    ).json()["quizId"]

    res = test_client.get(f"/api/quiz/{quiz_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "in_progress"
    assert [i["sentenceId"] for i in body["items"]] == [sids["s2"].id, sids["s1"].id, sids["s3"].id]
    assert all(i["userInput"] is None for i in body["items"])
    assert body["answers"][sids["s1"].id] == S1_TEXT
    assert body["answers"][sids["s2"].id] == S2_TEXT

    assert test_client.get("/api/quiz/no-such-quiz").status_code == 404


def test_submit_grades_normalizes_and_masters_material(client):
    test_client, material, _, sids = client
    quiz_id = test_client.post(
        f"/api/materials/{material.id}/quiz/generate", json={"count": 2}
    ).json()["quizId"]

    res = test_client.post(
        f"/api/materials/{material.id}/quiz/submit",
        json={
            "quizId": quiz_id,
            "items": [
                # 归一化：忽略大小写/首尾空格/全部标点/全角转半角
                {"sentenceId": sids["s2"].id, "userInput": f"  {S2_TEXT.upper()}　"},
                {"sentenceId": sids["s1"].id, "userInput": "　Hello， and welcome to the programme！"},
            ],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["correctCount"] == 2
    assert body["totalCount"] == 2
    assert body["score"] == 100.0
    assert all(r["correct"] for r in body["results"])
    assert body["material"] == {"stage": "mastered", "bestScore": 100.0}

    loaded = material_store.load(material.id)
    assert loaded[0].stage == "mastered"
    assert loaded[0].bestScore == 100.0

    stored = _quizzes_on_disk(material.id)[0]
    assert stored["status"] == "completed"
    assert stored["completedAt"]
    assert stored["correctCount"] == 2
    assert stored["score"] == 100.0
    assert all(i["correct"] is True for i in stored["items"])
    assert stored["items"][0]["userInput"] is not None


def test_submit_below_90_records_score_without_mastering(client):
    test_client, material, _, sids = client
    quiz_id = test_client.post(
        f"/api/materials/{material.id}/quiz/generate", json={"count": 2}
    ).json()["quizId"]

    res = test_client.post(
        f"/api/materials/{material.id}/quiz/submit",
        json={
            "quizId": quiz_id,
            "items": [
                {"sentenceId": sids["s2"].id, "userInput": S2_TEXT},
                {"sentenceId": sids["s1"].id, "userInput": "completely wrong"},
            ],
        },
    )
    body = res.json()
    assert body["correctCount"] == 1
    assert body["score"] == 50.0
    assert body["material"]["stage"] == "learning"
    assert body["material"]["bestScore"] == 50.0

    loaded = material_store.load(material.id)
    assert loaded[0].stage == "learning"
    assert loaded[0].bestScore == 50.0


def test_retake_low_score_keeps_best_score_and_no_downgrade(client):
    test_client, material, _, sids = client
    base = f"/api/materials/{material.id}/quiz"

    first_id = test_client.post(f"{base}/generate", json={"count": 2}).json()["quizId"]
    perfect = test_client.post(
        f"{base}/submit",
        json={
            "quizId": first_id,
            "items": [
                {"sentenceId": sids["s2"].id, "userInput": S2_TEXT},
                {"sentenceId": sids["s1"].id, "userInput": S1_TEXT},
            ],
        },
    ).json()
    assert perfect["material"] == {"stage": "mastered", "bestScore": 100.0}

    # 已完成后可再测；低分只记成绩，不降级、bestScore 取最大
    second_id = test_client.post(f"{base}/generate", json={"count": 1}).json()["quizId"]
    assert second_id != first_id
    res = test_client.post(
        f"{base}/submit",
        json={"quizId": second_id, "items": [{"sentenceId": sids["s2"].id, "userInput": "bad"}]},
    )
    body = res.json()
    assert body["score"] == 0.0
    assert body["material"] == {"stage": "mastered", "bestScore": 100.0}


def test_get_quiz_after_submit_preserves_user_inputs(client):
    test_client, material, _, sids = client
    quiz_id = test_client.post(
        f"/api/materials/{material.id}/quiz/generate", json={"count": 1}
    ).json()["quizId"]
    test_client.post(
        f"/api/materials/{material.id}/quiz/submit",
        json={"quizId": quiz_id, "items": [{"sentenceId": sids["s2"].id, "userInput": "my answer"}]},
    )

    res = test_client.get(f"/api/quiz/{quiz_id}")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "completed"
    assert body["items"][0]["userInput"] == "my answer"
    assert body["items"][0]["correct"] is False
    assert body["answers"][sids["s2"].id] == S2_TEXT


def test_submit_unknown_quiz_or_sentence_404(client):
    test_client, material, _, sids = client
    quiz_id = test_client.post(
        f"/api/materials/{material.id}/quiz/generate", json={"count": 1}
    ).json()["quizId"]

    res = test_client.post(
        f"/api/materials/{material.id}/quiz/submit",
        json={"quizId": "no-such", "items": [{"sentenceId": sids["s2"].id, "userInput": "x"}]},
    )
    assert res.status_code == 404

    res = test_client.post(
        f"/api/materials/{material.id}/quiz/submit",
        json={"quizId": quiz_id, "items": [{"sentenceId": "no-such", "userInput": "x"}]},
    )
    assert res.status_code == 404


def test_submit_unknown_material_404(client):
    test_client, _, _, _ = client
    res = test_client.post(
        "/api/materials/no-such/quiz/submit",
        json={"quizId": "q", "items": [{"sentenceId": "s", "userInput": "x"}]},
    )
    assert res.status_code == 404


# ---------- 2026-11-03 LLM 主旨选题（quiz_pick） ----------


class _QPCompletions:
    def __init__(self, content):
        self._content = content
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))]
        )


def test_quiz_pick_validates_and_dedupes_ids():
    from backend.app.llm import quiz_pick

    content = '{"sentence_ids": ["s1", "bogus", "s1", "s2"]}'
    ids = quiz_pick._extract_ids(content, {"s1", "s2"}, count=10)
    assert ids == ["s1", "s2"]


def test_quiz_pick_respects_count():
    from backend.app.llm import quiz_pick

    content = '{"sentence_ids": ["s1", "s2", "s3"]}'
    assert quiz_pick._extract_ids(content, {"s1", "s2", "s3"}, count=2) == ["s1", "s2"]


def test_quiz_pick_not_configured_returns_empty():
    from backend.app.llm import quiz_pick

    sentences = [
        Sentence(
            materialId="m", turnId="t", blockId="b", index=0,
            text="A long enough sentence for the quiz.", aligned=True,
        )
    ]
    settings = Settings(llm=LlmSettings(provider="kimi", apiKey="", model="", enabled=False))
    assert quiz_pick.pick(sentences, [], 10, settings) == []


def test_generate_merges_llm_focus_with_rule_fill(client, monkeypatch):
    """LLM 选题为主干；没听懂/生词句经规则补缺进入（用户标记优先不丢）。"""
    from types import SimpleNamespace

    from backend.app.llm import quiz_pick
    from backend.app.models import LlmSettings, Settings
    from backend.app.storage.json_store import write_json_atomic

    test_client, material, _, sids = client
    # 隔离设置中启用 LLM（Key 为假；客户端随后被替换为假实现）
    write_json_atomic(
        os.path.join(settings_api.DATA_DIR, "settings.json"),
        Settings(
            llm=LlmSettings(provider="kimi", apiKey="sk-test", model="k2", enabled=True)
        ).model_dump(),
    )
    # LLM 只选中 s3；规则给出 [s2(没听懂), s1(生词), s3]
    monkeypatch.setattr(
        quiz_pick,
        "_create_client",
        lambda *a, **k: SimpleNamespace(
            chat=SimpleNamespace(
                completions=_QPCompletions(
                    json.dumps({"sentence_ids": [sids["s3"].id]})
                )
            )
        ),
    )
    res = test_client.post(f"/api/materials/{material.id}/quiz/generate", json={"count": 3})
    assert res.status_code == 201
    picked = [i["sentenceId"] for i in res.json()["items"]]
    assert len(picked) == 3
    assert sids["s2"].id in picked  # 没听懂句经规则补缺保留
    assert sids["s3"].id in picked  # LLM 主旨选中
