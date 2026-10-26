"""表情包：按语义从梗图库里检索最匹配的一张。

索引来自 assets/emo_index.json（tools/fetch_memes.py 生成），
每张图的台词会被向量化并缓存到 assets/emo_vectors.npy，
之后启动直接加载，不重复计算。
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import numpy as np

from . import embedding as E

ROOT = Path(__file__).resolve().parent.parent.parent
EMO_DIR = ROOT / "assets" / "emo"
INDEX_PATH = ROOT / "assets" / "emo_index.json"
VEC_PATH = ROOT / "assets" / "emo_vectors.npy"

# 相似度低于这个值就不发，宁可不发也不发不相关的
MIN_SCORE = 0.42
TOP_K = 6

_items: list[dict] | None = None
_matrix: np.ndarray | None = None
_by_emotion: dict[str, list[dict]] = {}

# 台词格式：「台词」情绪词表情包 —— 情绪词才是检索该用的部分
_EMO_TAIL = re.compile(r"[』」]\s*([^』」]{1,12}?)表情包\s*$")
_EMO_ONLY = re.compile(r"^(.{1,12}?)表情包\s*$")


def _search_text(caption: str) -> str:
    """从台词里抽出情绪描述，抽不到就用整句。"""
    for pat in (_EMO_TAIL, _EMO_ONLY):
        m = pat.search(caption)
        if m:
            label = m.group(1).strip()
            if label and not re.search(r"[『』「」]|DeepSeek|GPT|Claude|娘", label):
                return label
    return caption


def _build_vectors(items: list[dict]) -> np.ndarray:
    texts = [_search_text(it["caption"]) for it in items]
    vecs = []
    batch = 64
    for i in range(0, len(texts), batch):
        vecs.extend(E.embed_passages(texts[i : i + batch]))
    return np.vstack(vecs)


def _load() -> bool:
    """加载索引和向量。返回是否可用。"""
    global _items, _matrix
    if _items is not None:
        return _matrix is not None and len(_items) > 0

    if not INDEX_PATH.exists():
        _items = []
        _matrix = None
        return False

    try:
        raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        _items = [it for it in raw if (EMO_DIR / f"{it['id']}.webp").exists()]
    except Exception:
        _items = []
        _matrix = None
        return False

    if not _items:
        _matrix = None
        return False

    _by_emotion.clear()
    for it in _items:
        emo = (it.get("emotion") or "").strip()
        if emo:
            _by_emotion.setdefault(emo, []).append(it)

    try:
        if VEC_PATH.exists():
            mat = np.load(VEC_PATH)
            if mat.shape[0] == len(_items):
                _matrix = mat
                return True
        mat = _build_vectors(_items)
        np.save(VEC_PATH, mat)
        _matrix = mat
        return True
    except Exception:
        _matrix = None
        return False


def available() -> bool:
    return _load()


def count() -> int:
    _load()
    return len(_items or [])


def pick(reply_text: str, emotion: str | None = None) -> Path | None:
    """挑一张表情包。

    优先按情绪标签精确匹配（模型自己判断的情绪最准），
    没有对应情绪时退回向量检索，两者都不中就不发。
    """
    if not _load():
        return None

    # 1. 按情绪标签选
    if emotion:
        pool = _by_emotion.get(emotion.strip().lower())
        if pool:
            item = random.choice(pool)
            path = EMO_DIR / f"{item['id']}.webp"
            if path.exists():
                return path

    # 2. 向量检索兜底
    if _matrix is None or not reply_text.strip():
        return None

    try:
        qv = E.embed_query(reply_text)
        hits = E.top_k(qv, _matrix, TOP_K, MIN_SCORE)
    except Exception:
        return None

    if not hits:
        return None

    idx, _ = random.choice(hits[:3])
    item = _items[idx]
    path = EMO_DIR / f"{item['id']}.webp"
    return path if path.exists() else None


def emotion_count() -> dict[str, int]:
    _load()
    return {k: len(v) for k, v in _by_emotion.items()}
