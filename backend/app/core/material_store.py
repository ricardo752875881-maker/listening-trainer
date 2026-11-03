"""材料存储（data/materials/<id>/，data-model.md「存储落地」）。

material.json 为 Material + turns[]（嵌套 blocks[]，再嵌套 sentences[]）；
写入走临时文件 + os.replace 原子替换。list 返回材料库卡片（含派生统计：
vocab = word/phrase 复习条目数，notUnderstood = 标记句数）。delete 级联清除
目录（含 shadowing.json / quizzes.json / 音频）与全局复习队列条目。
"""

import os
import shutil
from typing import Optional

from ..models import Block, Material, Sentence, Turn
from ..storage.json_store import read_json, write_json_atomic
from . import review_store

DATA_DIR = os.environ.get("DATA_DIR", os.path.join("data"))


def _materials_root() -> str:
    return os.path.join(DATA_DIR, "materials")


def _material_dir(material_id: str) -> str:
    return os.path.join(_materials_root(), material_id)


def _material_path(material_id: str) -> str:
    return os.path.join(_material_dir(material_id), "material.json")


def ensure_material_dir(material_id: str) -> str:
    path = _material_dir(material_id)
    os.makedirs(path, exist_ok=True)
    return path


def save(material: Material, turns: list[Turn], blocks: list[Block], sentences: list[Sentence]) -> None:
    """嵌套保存 material.json：turn → blocks → sentences。"""
    ensure_material_dir(material.id)
    turn_payloads = {t.id: {**t.model_dump(), "blocks": []} for t in sorted(turns, key=lambda t: t.index)}
    block_payloads: dict[str, dict] = {}
    for b in sorted(blocks, key=lambda b: (b.turnId, b.index)):
        payload = {**b.model_dump(), "sentences": []}
        block_payloads[b.id] = payload
        turn_payloads[b.turnId]["blocks"].append(payload)
    for s in sorted(sentences, key=lambda s: s.index):
        block_payloads[s.blockId]["sentences"].append(s.model_dump())
    payload = material.model_dump()
    payload["turns"] = list(turn_payloads.values())
    write_json_atomic(_material_path(material.id), payload)


def load(material_id: str) -> Optional[tuple[Material, list[Turn], list[Block], list[Sentence]]]:
    """加载材料全量数据；不存在返回 None，损坏抛 DataError。"""
    raw = read_json(_material_path(material_id), default=None)
    if raw is None:
        return None
    material = Material(**{k: v for k, v in raw.items() if k != "turns"})
    turns: list[Turn] = []
    blocks: list[Block] = []
    sentences: list[Sentence] = []
    for t in raw.get("turns", []):
        b_list = t.pop("blocks", [])
        turns.append(Turn(**t))
        for b in b_list:
            s_list = b.pop("sentences", [])
            blocks.append(Block(**b))
            sentences.extend(Sentence(**s) for s in s_list)
    sentences.sort(key=lambda s: s.index)
    blocks.sort(key=lambda b: (b.turnId, b.index))
    turns.sort(key=lambda t: t.index)
    return material, turns, blocks, sentences


def list_materials() -> list[dict]:
    """材料库卡片：id/title/durationSec/stage/bestScore/stats/createdAt。"""
    root = _materials_root()
    if not os.path.isdir(root):
        return []
    vocab_counts: dict[str, int] = {}
    for item in review_store.list_items():
        if item.type in ("word", "phrase"):
            vocab_counts[item.materialId] = vocab_counts.get(item.materialId, 0) + 1
    cards: list[dict] = []
    for entry in sorted(os.listdir(root)):
        loaded = load(entry)
        if loaded is None:
            continue
        material, _, _, sentences = loaded
        cards.append(
            {
                "id": material.id,
                "title": material.title,
                "durationSec": material.durationSec,
                "stage": material.stage,
                "bestScore": material.bestScore,
                "stats": {
                    "vocab": vocab_counts.get(material.id, 0),
                    "notUnderstood": sum(1 for s in sentences if s.notUnderstood),
                },
                "createdAt": material.createdAt,
            }
        )
    return cards


def delete(material_id: str) -> bool:
    """级联删除：材料目录（音频/material.json/shadowing.json/quizzes.json）+ 复习条目。"""
    existed = os.path.isdir(_material_dir(material_id))
    if existed:
        shutil.rmtree(_material_dir(material_id), ignore_errors=True)
    review_store.cascade_by_material(material_id)
    return existed
