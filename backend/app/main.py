import importlib
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import materials, markings, quiz, review, settings as settings_api, settings_extra, shadowing

# "import" 是 Python 保留字，api/import.py 需用 importlib 导入
import_api = importlib.import_module("backend.app.api.import")

logger = logging.getLogger(__name__)

app = FastAPI(title="精听工坊")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/api/health")
def health():
    return {"ok": True}


app.include_router(settings_api.router)
app.include_router(settings_extra.router)
app.include_router(import_api.router)
app.include_router(materials.router)
app.include_router(markings.router)
app.include_router(quiz.router)
app.include_router(review.router)
app.include_router(shadowing.router)

# 伺服前端构建产物（frontend/dist）；目录不存在时跳过（如纯后端开发阶段）
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
