"""导入任务注册表与后台流水线（data-model.md ImportJob，FR-010/FR-012）。

任务常驻进程内 dict（页面关闭重开可续查，contracts/api.md「导入 Import」）；
流水线在独立线程执行（``asyncio.to_thread``），轮询/取消请求不被长对齐阻塞。
阶段推进：parsing → aligning → done；
取消 → cancelled（清理音频目录、不入库、无残留）；
对齐失败（TranscribeError，含文稿与音频不匹配）→ 降级为"仅音频模式"材料入库
（仍 done，audioOnly=true，可经 retry-transcribe 用文稿重新对齐补齐）。
"""

import asyncio
import logging
import os
import shutil
from typing import Callable, Optional

from .core import forced_aligner, material_store, transcript_parser
from .core.forced_aligner import JobCancelled, TranscribeError, probe_duration_sec
from .models import Material, Settings, new_id

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("DATA_DIR", os.path.join("data"))

TERMINAL_STAGES = ("done", "cancelled", "error")

# 进程内任务注册表：id → job dict；常驻内存，重开可查（FR-010）
_jobs: dict[str, dict] = {}


def read_settings() -> Settings:
    """读取 settings.json（对齐模型默认值）；缺失/损坏回退默认设置。"""
    try:
        from .storage.json_store import read_json

        raw = read_json(os.path.join(DATA_DIR, "settings.json"), default=None)
        return Settings() if raw is None else Settings(**raw)
    except Exception:  # noqa: BLE001 - 设置不可用时流水线按默认设置继续
        logger.warning("settings unreadable, falling back to defaults", exc_info=True)
        return Settings()


def _material_dir(material_id: str) -> str:
    return os.path.join(material_store.DATA_DIR, "materials", material_id)


def create_job(
    material_id: str,
    title: str,
    transcript: str,
    audio_path: str,
) -> dict:
    job = {
        "id": new_id(),
        "stage": "parsing",
        "progressPct": 0.0,
        "materialId": None,
        "audioOnly": None,
        "error": None,
        "cancelRequested": False,
        "material_id": material_id,
        "title": title,
        "transcript": transcript,
        "audioPath": audio_path,
    }
    _jobs[job["id"]] = job
    return job


def get_job(job_id: str) -> Optional[dict]:
    return _jobs.get(job_id)


def cancel(job_id: str) -> Optional[dict]:
    """请求取消；终态任务幂等返回。流水线在下一个检查点响应（清理+置 cancelled）。"""
    job = _jobs.get(job_id)
    if job is None:
        return None
    if job["stage"] not in TERMINAL_STAGES:
        job["cancelRequested"] = True
    return job


def snapshot(job: dict) -> dict:
    """轮询响应形状：{stage, progressPct, materialId?, audioOnly?}。"""
    out = {"stage": job["stage"], "progressPct": job["progressPct"]}
    if job.get("materialId"):
        out["materialId"] = job["materialId"]
    if job.get("audioOnly") is not None:
        out["audioOnly"] = job["audioOnly"]
    if job["stage"] == "error" and job.get("error"):
        out["error"] = job["error"]
    return out


def start_job(job: dict) -> None:
    """后台启动流水线（调用方须处于 running event loop，如 FastAPI 端点内）。"""
    loop = asyncio.get_running_loop()
    loop.create_task(_run(job))


async def _run(job: dict) -> None:
    try:
        await asyncio.to_thread(_pipeline, job)
    except Exception:  # noqa: BLE001 - _pipeline 内已分类处理，这里兜底防泄漏
        logger.exception("import pipeline crashed: %s", job["id"])
        if job["stage"] not in TERMINAL_STAGES:
            job["stage"] = "error"
            job["error"] = "internal pipeline error"


def _check_cancel(job: dict) -> None:
    if job["cancelRequested"]:
        raise JobCancelled()


def _progress_hooks(job: dict) -> tuple[Callable[[], bool], Callable[[float], None]]:
    """对齐回调：取消检查点 + 进度（对齐阶段占 10%→80%）。"""

    def should_cancel() -> bool:
        if job["cancelRequested"]:
            raise JobCancelled()
        return False

    def on_progress(frac: float) -> None:
        job["progressPct"] = round(10.0 + 70.0 * min(max(frac, 0.0), 1.0), 1)

    return should_cancel, on_progress


def _cleanup(job: dict) -> None:
    """取消/失败清理：目录内尚无 material.json 时整个移除（音频无残留）。"""
    directory = _material_dir(job["material_id"])
    if os.path.isdir(directory) and not os.path.exists(os.path.join(directory, "material.json")):
        shutil.rmtree(directory, ignore_errors=True)


def apply_alignment(models: dict, aligned_words: list[dict]) -> None:
    """强制对齐词序列按句分组写回 Sentence 模型（入库前）。"""
    forced_aligner.group_words_to_sentences(models["sentences"], aligned_words)


def _pipeline(job: dict) -> None:
    settings = read_settings()
    duration_sec: Optional[float] = None
    try:
        _check_cancel(job)
        job["stage"] = "parsing"
        job["progressPct"] = 5.0
        parsed = transcript_parser.parse(job["transcript"])
        models = transcript_parser.to_models(parsed, job["material_id"])
        text = " ".join(s.text for s in models["sentences"])

        _check_cancel(job)
        job["stage"] = "aligning"
        job["progressPct"] = 10.0
        duration_sec = probe_duration_sec(job["audioPath"])
        should_cancel, on_progress = _progress_hooks(job)
        result = forced_aligner.align(
            job["audioPath"],
            text,
            model_size=settings.alignModel,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
        duration_sec = float(result.get("durationSec") or duration_sec)

        _check_cancel(job)
        job["progressPct"] = 85.0
        apply_alignment(models, result.get("words", []))

        _check_cancel(job)
        material = Material(
            id=job["material_id"],
            title=job["title"],
            audioFileName=os.path.basename(job["audioPath"]),
            durationSec=duration_sec,
            engineUsed="wav2vec2",
        )
        material_store.save(material, models["turns"], models["blocks"], models["sentences"])
        job.update(stage="done", progressPct=100.0, materialId=material.id, audioOnly=False)
    except JobCancelled:
        _cleanup(job)
        job["stage"] = "cancelled"
    except TranscribeError as exc:
        if duration_sec is None:
            # 时长探测失败（/start 解码校验之后的防御路径）：无法构造有效材料
            _cleanup(job)
            job["stage"] = "error"
            job["error"] = str(exc)
            return
        _fallback_audio_only(job, duration_sec)
    except Exception as exc:  # noqa: BLE001 - 解析/对齐等意外失败统一为 error 阶段
        logger.exception("import pipeline failed: %s", job["id"])
        _cleanup(job)
        job["stage"] = "error"
        job["error"] = str(exc)


def _fallback_audio_only(job: dict, duration_sec: float) -> None:
    """FR-012 降级：对齐失败仍入库为仅音频模式（仅播放可用），支持后续重试补齐。"""
    try:
        _check_cancel(job)
        material = Material(
            id=job["material_id"],
            title=job["title"],
            audioFileName=os.path.basename(job["audioPath"]),
            durationSec=duration_sec,
            audioOnly=True,
            engineUsed="wav2vec2",
        )
        material_store.save(material, [], [], [])
        job.update(stage="done", progressPct=100.0, materialId=material.id, audioOnly=True)
    except JobCancelled:
        _cleanup(job)
        job["stage"] = "cancelled"
    except Exception as exc:  # noqa: BLE001 - 降级入库本身失败则无可再降
        logger.exception("audio-only fallback save failed: %s", job["id"])
        job["stage"] = "error"
        job["error"] = str(exc)
