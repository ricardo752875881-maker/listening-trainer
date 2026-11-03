"""合约测试：导入接口（contracts/api.md「导入 Import」节，FR-010/012）。

自行装配 FastAPI + import router（复刻 main.py 的 400 handler）；
强制对齐经 monkeypatch jobs.forced_aligner.align 注入假实现（不依赖真实模型）；
合约测试不依赖 main.py 接线。
"""

import importlib
import io
import os
import time
import wave

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app import jobs
from backend.app.core import material_store, review_store
from backend.app.core.forced_aligner import JobCancelled, TranscribeError

import_api = importlib.import_module("backend.app.api.import")

TRANSCRIPT = "Hello world."
FAKE_WORDS = [
    {"w": "Hello", "start": 0.0, "end": 0.5},
    {"w": "world.", "start": 0.5, "end": 1.0},
]


def fake_align(audio_path, text, model_size="base", should_cancel=None, on_progress=None):
    """可配置词序列的假强制对齐。"""
    return {"words": [dict(w) for w in FAKE_WORDS], "durationSec": 2.0}


def failing_align(audio_path, text, model_size="base", should_cancel=None, on_progress=None):
    raise TranscribeError("模拟对齐失败")


def slow_align(audio_path, text, model_size="base", should_cancel=None, on_progress=None):
    """慢速对齐：循环内检查取消标志（与真实对齐器相同的契约）。"""
    for _ in range(500):
        time.sleep(0.02)
        if should_cancel is not None and should_cancel():
            raise JobCancelled()
    return {"words": [dict(w) for w in FAKE_WORDS], "durationSec": 2.0}


def make_wav_bytes(seconds=0.5, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = str(tmp_path / "data")
    monkeypatch.setattr(material_store, "DATA_DIR", data_dir)
    monkeypatch.setattr(review_store, "DATA_DIR", data_dir)
    monkeypatch.setattr(jobs, "DATA_DIR", data_dir)
    monkeypatch.setattr(jobs.forced_aligner, "align", fake_align)

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(import_api.router)

    with TestClient(app) as test_client:
        yield test_client


def start_import(client, content=None, filename="audio.wav", title="测试材料",
                 transcript=TRANSCRIPT):
    body = content if content is not None else make_wav_bytes()
    files = {"audio": (filename, body, "audio/wav" if filename.endswith("wav") else "application/octet-stream")}
    data = {"title": title, "transcript": transcript}
    return client.post("/api/import/start", files=files, data=data)


def wait_terminal(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/import/jobs/{job_id}").json()
        if body["stage"] in ("done", "cancelled", "error"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"任务 {job_id} 未在限时内到达终态")


def wait_stage(client, job_id, stage, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/import/jobs/{job_id}").json()
        if body["stage"] == stage:
            return body
        if body["stage"] in ("done", "cancelled", "error"):
            raise AssertionError(f"任务提前进入终态 {body['stage']}，期望 {stage}")
        time.sleep(0.02)
    raise AssertionError(f"任务未进入阶段 {stage}")


# ---------- /api/import/parse ----------

def test_parse_preview_returns_stats_and_structure(client):
    transcript = "Neil 尼尔\nHello there. How are you?\n你们好啊。\n"
    res = client.post("/api/import/parse", json={"transcript": transcript})
    assert res.status_code == 200
    body = res.json()
    assert body["speakers"] == [{"name": "Neil", "nameZh": "尼尔"}]
    assert body["turnCount"] == 1
    assert body["blockCount"] >= 1
    assert body["translationLineCount"] == 1
    turn = body["turns"][0]
    assert turn["speakerName"] == "Neil"
    assert turn["speakerNameZh"] == "尼尔"
    texts = [s["text"] for b in turn["blocks"] for s in b["sentences"]]
    assert texts == ["Hello there.", "How are you?"]
    # 预览不落库
    assert material_store.list_materials() == []


def test_parse_empty_transcript_400(client):
    res = client.post("/api/import/parse", json={"transcript": ""})
    assert res.status_code == 400


# ---------- /api/import/start + 轮询 ----------

def test_start_polls_to_done_and_persists_material(client):
    res = start_import(client)
    assert res.status_code == 201
    job_id = res.json()["jobId"]

    done = wait_terminal(client, job_id)
    assert done["stage"] == "done"
    assert done["progressPct"] == 100.0
    assert done["audioOnly"] is False
    material_id = done["materialId"]
    assert material_id

    loaded = material_store.load(material_id)
    assert loaded is not None
    material, turns, blocks, sentences = loaded
    assert material.title == "测试材料"
    assert material.audioOnly is False
    assert material.engineUsed == "wav2vec2"
    assert material.durationSec == 2.0  # 对齐器探测的时长
    assert len(turns) == 1 and len(blocks) == 1 and len(sentences) == 1
    sentence = sentences[0]
    assert sentence.text == "Hello world."
    assert sentence.aligned is True
    assert sentence.startSec == 0.0
    assert sentence.endSec == 1.0
    assert [w.w for w in sentence.words] == ["Hello", "world."]
    # 音频保存在 data/materials/<id>/audio.<ext>
    audio_path = os.path.join(material_store.DATA_DIR, "materials", material_id, "audio.wav")
    assert os.path.isfile(audio_path)


def test_start_rejects_undecodable_audio_with_400(client):
    res = start_import(client, content=b"this is definitely not audio", filename="audio.mp3")
    assert res.status_code == 400
    assert "无法解码的音频文件" in res.json()["detail"]
    assert material_store.list_materials() == []


def test_start_rejects_bad_extension_with_400(client):
    res = start_import(client, filename="audio.txt")
    assert res.status_code == 400


def test_start_rejects_empty_title_with_400(client):
    res = start_import(client, title="   ")
    assert res.status_code == 400
    assert res.json()["detail"] == "标题不能为空"


def test_align_failure_falls_back_to_audio_only(client, monkeypatch):
    monkeypatch.setattr(jobs.forced_aligner, "align", failing_align)
    res = start_import(client)
    assert res.status_code == 201
    done = wait_terminal(client, res.json()["jobId"])
    # FR-012：对齐失败仍入库（done），但标记为仅音频模式
    assert done["stage"] == "done"
    assert done["audioOnly"] is True
    material_id = done["materialId"]

    material, turns, blocks, sentences = material_store.load(material_id)
    assert material.audioOnly is True
    assert material.engineUsed == "wav2vec2"
    assert turns == [] and blocks == [] and sentences == []
    # 音频文件仍在，可播放
    audio_path = os.path.join(material_store.DATA_DIR, "materials", material_id, "audio.wav")
    assert os.path.isfile(audio_path)


def test_cancel_marks_cancelled_and_cleans_up(client, monkeypatch):
    monkeypatch.setattr(jobs.forced_aligner, "align", slow_align)
    res = start_import(client)
    assert res.status_code == 201
    job_id = res.json()["jobId"]

    wait_stage(client, job_id, "aligning")
    res = client.post(f"/api/import/jobs/{job_id}/cancel")
    assert res.status_code == 200

    terminal = wait_terminal(client, job_id)
    assert terminal["stage"] == "cancelled"
    assert "materialId" not in terminal  # 不入库
    # 无残留：材料目录已清理
    root = os.path.join(material_store.DATA_DIR, "materials")
    assert not os.path.isdir(root) or os.listdir(root) == []


def test_job_endpoints_404_for_unknown_job(client):
    assert client.get("/api/import/jobs/no-such-job").status_code == 404
    assert client.post("/api/import/jobs/no-such-job/cancel").status_code == 404
