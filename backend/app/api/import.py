"""导入接口（contracts/api.md「导入 Import」节，FR-007/008/010/012）。

- POST /api/import/parse                     文稿结构预览（不落库）
- POST /api/import/start                     multipart 上传音频+文稿，创建后台导入任务
- GET  /api/import/jobs/{jobId}              轮询进度（任务常驻内存，重开可查）
- POST /api/import/jobs/{jobId}/cancel       取消并清理临时文件（不入库、无残留）

流水线：parsing（文稿解析）→ aligning（wav2vec2 CTC 强制对齐，官方文稿直接钉到音频）
→ done；对齐失败降级为"仅音频模式"（audioOnly=true，可 retry-transcribe 补齐）。

错误约定：400 参数/校验失败（含音频损坏探测：av 打不开即拒）；404 任务不存在。
"""

import io
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import jobs
from ..core import material_store, transcript_parser
from ..models import AUDIO_EXTS, new_id

router = APIRouter()


class ParseIn(BaseModel):
    transcript: str = Field(min_length=1)


def _fix_encoding(s: str) -> str:
    """multipart 表单字段未声明 charset 时会被按 latin-1 解码导致中文乱码，这里无损还原。"""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _probe_audio(content: bytes) -> None:
    """上传即探测可解码性：av 打不开的损坏文件直接 400，不进后台任务。"""
    try:
        import av

        with av.open(io.BytesIO(content)):
            pass
    except Exception:
        raise HTTPException(status_code=400, detail="无法解码的音频文件，请更换文件")


@router.post("/api/import/parse")
def parse_preview(body: ParseIn):
    """结构预览：{speakers, turnCount, blockCount, translationLineCount, turns}，不落库。"""
    return transcript_parser.parse(body.transcript).to_dict()


@router.post("/api/import/start", status_code=201)
async def start_import(
    audio: UploadFile = File(...),
    title: str = Form(min_length=1, max_length=200),
    transcript: str = Form(min_length=1),
):
    filename = audio.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in AUDIO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频格式，仅支持: {'/'.join(sorted(AUDIO_EXTS))}",
        )
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=400, detail="音频文件内容为空")
    _probe_audio(content)
    clean_title = _fix_encoding(title).strip()
    transcript = _fix_encoding(transcript)
    if not clean_title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    material_id = new_id()
    audio_dir = material_store.ensure_material_dir(material_id)
    audio_path = os.path.join(audio_dir, f"audio.{ext}")
    with open(audio_path, "wb") as f:
        f.write(content)

    job = jobs.create_job(
        material_id=material_id,
        title=clean_title,
        transcript=transcript,
        audio_path=audio_path,
    )
    jobs.start_job(job)
    return {"jobId": job["id"]}


@router.get("/api/import/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return jobs.snapshot(job)


@router.post("/api/import/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return jobs.snapshot(job)
