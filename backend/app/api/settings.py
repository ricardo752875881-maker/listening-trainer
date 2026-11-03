import os

from fastapi import APIRouter

from ..models import LlmSettings, Settings, mask_secret
from ..storage.json_store import read_json, write_json_atomic

router = APIRouter()

DATA_DIR = os.environ.get("DATA_DIR", os.path.join("data"))
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")


def _read_settings() -> Settings:
    raw = read_json(SETTINGS_PATH, default=None)
    if raw is None:
        return Settings()
    return Settings(**raw)


def _masked(s: Settings) -> dict:
    data = s.model_dump()
    data["llm"] = s.llm.model_dump()
    data["llm"]["apiKey"] = mask_secret(s.llm.apiKey)
    return data


def _is_masked(value: str) -> bool:
    return value.startswith("****")


@router.get("/api/settings")
def get_settings():
    return _masked(_read_settings())


@router.put("/api/settings")
def put_settings(body: Settings):
    # 全量更新；掩码值（"****" 开头）表示未修改，保留原值
    current = _read_settings()
    if _is_masked(body.llm.apiKey):
        body.llm = LlmSettings(**body.llm.model_dump(exclude={"apiKey"}), apiKey=current.llm.apiKey)
    write_json_atomic(SETTINGS_PATH, body.model_dump())
    return _masked(body)
