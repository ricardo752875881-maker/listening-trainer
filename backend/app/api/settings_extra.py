"""设置扩展接口（contracts/api.md「设置 Settings」节）。

- POST /api/settings/test-llm              openai 兼容 models.list 验证三服务商 → {ok, message}
- GET  /api/models/align-status            base/large 对齐模型下载状态 → {models: {size: {status, error}}}
- POST /api/models/align/{size}/download   后台触发模型预下载（状态机流转）
"""

import os
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import forced_aligner  # noqa: F401 镜像默认值环境变量副作用
from ..llm.recommend import PROVIDER_BASE_URLS
from . import settings as settings_api

router = APIRouter()


def _is_usable_key(value: str) -> bool:
    return bool(value) and not value.startswith("****")


class TestLlmIn(BaseModel):
    provider: str | None = None
    apiKey: str | None = None
    model: str | None = None


@router.post("/api/settings/test-llm")
def test_llm(body: TestLlmIn | None = None):
    """openai 兼容 client.models.list() 验证三服务商连通性。

    优先使用请求体里的表单值（未保存即可测），为空时回退到已保存设置。
    """
    settings = settings_api._read_settings()
    llm = settings.llm
    provider = (body.provider if body and body.provider else llm.provider) or ""
    key = (body.apiKey if body and body.apiKey else llm.apiKey) or ""
    if provider not in PROVIDER_BASE_URLS:
        return {"ok": False, "message": f"未知服务商: {provider}"}
    if not _is_usable_key(key):
        return {"ok": False, "message": "未配置大模型 API Key"}
    try:
        from openai import OpenAI

        client = OpenAI(api_key=key, base_url=PROVIDER_BASE_URLS[provider])
        client.models.list()
        return {"ok": True, "message": "连接成功"}
    except Exception as exc:  # noqa: BLE001 - 连通性测试统一返回 {ok, message}
        return {"ok": False, "message": str(exc)}


# ---------- 对齐模型下载状态机（前端轮询 /api/models/align-status） ----------

_MODEL_STATUS: dict[str, dict] = {}


def _find_align_model(size: str) -> str | None:
    """在 HF hub 缓存中探测 wav2vec2 对齐模型是否已下载；返回快照目录。"""
    repo = forced_aligner.MODEL_IDS.get(size)
    if repo is None:
        return None
    slug = "models--" + repo.replace("/", "--")
    roots: list[Path] = []
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        roots.append(Path(hf_home) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    for root in roots:
        snapshots = root / slug / "snapshots"
        if not snapshots.is_dir():
            continue
        for snapshot in sorted(snapshots.iterdir()):
            if snapshot.is_dir() and any(snapshot.iterdir()):
                return str(snapshot)
    return None


def _model_entry(size: str) -> dict:
    reg = _MODEL_STATUS.get(size)
    if reg:
        return {"status": reg["status"], "error": reg.get("error")}
    if _find_align_model(size):
        return {"status": "downloaded", "error": None}
    return {"status": "not_downloaded", "error": None}


@router.get("/api/models/align-status")
def align_models():
    return {"models": {size: _model_entry(size) for size in forced_aligner.MODEL_IDS}}


@router.post("/api/models/align/{size}/download")
def download_align_model(size: str):
    if size not in forced_aligner.MODEL_IDS:
        raise HTTPException(status_code=400, detail="对齐模型规格仅支持 base / large")
    _MODEL_STATUS[size] = {"status": "downloading", "error": None}
    threading.Thread(target=_download_worker, args=(size,), daemon=True).start()
    return {"status": "downloading"}


def _download_worker(size: str) -> None:
    """snapshot_download 预下载（含分词器）；完成置 downloaded，异常置 error 供前端显示重试。"""
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(forced_aligner.MODEL_IDS[size])
        _MODEL_STATUS[size] = {"status": "downloaded", "error": None}
    except Exception as exc:  # noqa: BLE001
        _MODEL_STATUS[size] = {"status": "error", "error": str(exc)[:300]}
