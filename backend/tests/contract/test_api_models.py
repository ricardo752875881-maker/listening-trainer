"""对齐模型状态/预下载端点合约测试（settings_extra 的 /api/models/align-*）。

无网络：HF 缓存探测用临时目录打补丁，下载 worker 用假 snapshot_download。
"""

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api import settings_extra
from backend.app.core import forced_aligner


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 隔离 HF 缓存与下载状态机
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
    settings_extra._MODEL_STATUS.clear()

    app = FastAPI()

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.errors()})

    app.include_router(settings_extra.router)
    return TestClient(app)


def test_align_status_not_downloaded(client):
    res = client.get("/api/models/align-status")
    assert res.status_code == 200
    models = res.json()["models"]
    assert set(models) == set(forced_aligner.MODEL_IDS)
    for entry in models.values():
        assert entry == {"status": "not_downloaded", "error": None}


def test_align_status_downloaded(client, tmp_path):
    hub = (
        tmp_path
        / "hf" / "hub" / "models--facebook--wav2vec2-base-960h" / "snapshots" / "abc"
    )
    hub.mkdir(parents=True)
    (hub / "model.bin").write_bytes(b"bin")
    res = client.get("/api/models/align-status")
    assert res.status_code == 200
    assert res.json()["models"]["base"]["status"] == "downloaded"
    assert res.json()["models"]["large"]["status"] == "not_downloaded"


def test_download_status_transitions(client, monkeypatch):
    # 先打桩再触发端点：POST 会启动真实后台下载线程
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download", lambda repo_id: f"/fake/{repo_id}"
    )

    res = client.post("/api/models/align/base/download")
    assert res.status_code == 200
    assert res.json() == {"status": "downloading"}

    # 后台线程可能已先完成（假下载极快），这里只验证 worker 本身的状态机流转
    settings_extra._download_worker("base")
    assert settings_extra._MODEL_STATUS["base"]["status"] == "downloaded"

    def _boom(repo_id):
        raise RuntimeError("network down")

    monkeypatch.setattr("huggingface_hub.snapshot_download", _boom)
    settings_extra._download_worker("large")
    assert settings_extra._MODEL_STATUS["large"]["status"] == "error"
    assert "network down" in settings_extra._MODEL_STATUS["large"]["error"]


def test_download_rejects_unknown_size(client):
    res = client.post("/api/models/align/xl/download")
    assert res.status_code == 400
