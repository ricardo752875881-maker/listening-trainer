"""材料库接口（contracts/api.md「材料 Materials」节，FR-001/012/026）。

- GET    /api/materials                     卡片列表（含派生统计 stats.vocab/notUnderstood）
- GET    /api/materials/{id}                全量学习数据（material/turns/blocks/sentences/shadowingItems）
- PATCH  /api/materials/{id}                {title?, stage?, playheadSec?}（校验失败 400）
- DELETE /api/materials/{id}                级联清除目录 + 复习条目 + 跟读 + 测验
- GET    /api/materials/{id}/audio          音频流（FileResponse 原生 Range 206）
- POST   /api/materials/{id}/retry-transcribe  仅音频模式重试对齐（成功补齐文稿，失败 502 保持 audioOnly）
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import jobs
from ..core import forced_aligner, material_store, review_store, transcript_parser
from ..core.forced_aligner import JobCancelled, TranscribeError
from ..models import Stage, now_iso
from ..storage.json_store import read_json

router = APIRouter()

_MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
}


def _material_dir(material_id: str) -> str:
    return os.path.join(material_store.DATA_DIR, "materials", material_id)


def _load_or_404(material_id: str):
    loaded = material_store.load(material_id)
    if loaded is None:
        raise HTTPException(status_code=404, detail="材料不存在")
    return loaded


def _read_shadowing(material_id: str) -> list:
    """shadowing.json 由跟读模块维护；缺失/损坏按空清单返回。"""
    raw = read_json(os.path.join(_material_dir(material_id), "shadowing.json"), default=[])
    return raw if isinstance(raw, list) else []


def _detail_payload(material, turns, blocks, sentences, shadowing_items) -> dict:
    return {
        "material": material.model_dump(),
        "turns": [t.model_dump() for t in turns],
        "blocks": [b.model_dump() for b in blocks],
        "sentences": [s.model_dump() for s in sentences],
        "shadowingItems": shadowing_items,
        # 学习界面载入时还原既有标记高亮（reviewItems 为前端回退读取路径）
        "reviewItems": [
            item.model_dump(mode="json")
            for item in review_store.list_items()
            if item.materialId == material.id
        ],
    }


@router.get("/api/materials")
def list_materials():
    """材料库卡片：[{id, title, durationSec, stage, bestScore, stats, createdAt}]。"""
    return material_store.list_materials()


@router.get("/api/materials/{material_id}")
def get_material(material_id: str):
    material, turns, blocks, sentences = _load_or_404(material_id)
    return _detail_payload(material, turns, blocks, sentences, _read_shadowing(material_id))


class PatchIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    stage: Optional[Stage] = None
    playheadSec: Optional[float] = Field(default=None, ge=0)


@router.patch("/api/materials/{material_id}")
def patch_material(material_id: str, body: PatchIn):
    material, turns, blocks, sentences = _load_or_404(material_id)
    data = body.model_dump(exclude_unset=True)
    if "title" in data:
        title = data["title"].strip()
        if not title:
            raise HTTPException(status_code=400, detail="标题不能为空")
        material.title = title
    if "stage" in data:
        material.stage = data["stage"]
    if "playheadSec" in data:
        material.playheadSec = data["playheadSec"]
    material.updatedAt = now_iso()
    material_store.save(material, turns, blocks, sentences)
    return material.model_dump()


@router.delete("/api/materials/{material_id}")
def delete_material(material_id: str):
    """级联删除：材料目录（音频/material.json/shadowing.json/quizzes.json）+ 复习条目。"""
    if not material_store.delete(material_id):
        raise HTTPException(status_code=404, detail="材料不存在")
    return {"deleted": True}


@router.get("/api/materials/{material_id}/audio")
def get_audio(material_id: str):
    """音频流；FileResponse 原生支持 Range（Starlette ≥0.39 返回 206），供 <audio> 拖动。"""
    material, _turns, _blocks, _sentences = _load_or_404(material_id)
    path = os.path.join(_material_dir(material_id), material.audioFileName)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="音频文件不存在")
    ext = material.audioFileName.rsplit(".", 1)[-1].lower()
    return FileResponse(path, media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"))


class RetryIn(BaseModel):
    transcript: str = Field(min_length=1)


@router.post("/api/materials/{material_id}/retry-transcribe")
def retry_transcribe(material_id: str, body: RetryIn):
    """仅音频模式材料重试对齐：同步执行 强制对齐(音频+文稿) → 补齐文稿数据。

    对齐失败保持 audioOnly 并返回 502 + detail（合约约定 502 上游失败）。
    """
    material, _turns, _blocks, _sentences = _load_or_404(material_id)
    if not material.audioOnly:
        raise HTTPException(status_code=409, detail="该材料已有文稿数据，无需重试对齐")
    settings = jobs.read_settings()
    audio_path = os.path.join(_material_dir(material_id), material.audioFileName)
    parsed = transcript_parser.parse(body.transcript)
    models = transcript_parser.to_models(parsed, material_id)
    text = " ".join(s.text for s in models["sentences"])
    try:
        result = forced_aligner.align(audio_path, text, model_size=settings.alignModel)
    except (TranscribeError, JobCancelled) as exc:
        raise HTTPException(status_code=502, detail=f"对齐失败: {exc}")

    jobs.apply_alignment(models, result.get("words", []))
    material.audioOnly = False
    material.engineUsed = "wav2vec2"
    if result.get("durationSec"):
        material.durationSec = float(result["durationSec"])
    material.updatedAt = now_iso()
    material_store.save(material, models["turns"], models["blocks"], models["sentences"])
    _m, turns, blocks, sentences = material_store.load(material_id)
    return _detail_payload(material, turns, blocks, sentences, _read_shadowing(material_id))
